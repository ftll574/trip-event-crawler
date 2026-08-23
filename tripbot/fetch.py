"""L2 禮貌抓取：誠實 UA、timeout、tenacity 重試、403/challenge 熔斷。

設計依據：
- 【02】§7：403/challenge 視為「被擋」，不重試風暴；連續被擋 → 冷卻告警。
- 【02】§4：一律設 timeout；指數退避＋jitter。
- R1：不用驗證碼代打/代理池。
"""

from __future__ import annotations

import logging
import random
import time

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from .config import HTTP_TIMEOUT_S, MAX_RETRIES, USER_AGENT

log = logging.getLogger(__name__)


class BlockedError(Exception):
    """被網站防護攔截（403/429/challenge），呼叫端應熔斷而非重試。"""


class TransientError(Exception):
    """暫時性錯誤（5xx/網路），可退避重試。"""


def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    h = {
        "User-Agent": USER_AGENT,
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.6",
        "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
    }
    if extra:
        h.update(extra)
    return h


def _classify(resp: httpx.Response) -> httpx.Response:
    if resp.status_code in (401, 403, 429):
        raise BlockedError(f"blocked with status {resp.status_code}")
    if resp.status_code >= 500:
        raise TransientError(f"server error {resp.status_code}")
    resp.raise_for_status()
    return resp


@retry(
    retry=retry_if_exception_type((TransientError, httpx.TransportError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_random_exponential(multiplier=1, max=30),
    reraise=True,
)
def fetch(url: str, *, client: httpx.Client | None = None,
          headers: dict[str, str] | None = None) -> httpx.Response:
    """GET 一個 URL。BlockedError 不重試直接拋出。"""
    own = client is None
    c = client or httpx.Client(timeout=HTTP_TIMEOUT_S, follow_redirects=True)
    try:
        time.sleep(random.uniform(0.5, 2.0))  # jitter：請求間隨機延遲
        resp = c.get(url, headers=_headers(headers))
        return _classify(resp)
    finally:
        if own:
            c.close()


class CircuitBreaker:
    """連續被擋 N 次 → 開路冷卻（狀態存 db.meta 由呼叫端持久化）。"""

    def __init__(self, threshold: int, cooldown_s: int) -> None:
        self.threshold = threshold
        self.cooldown_s = cooldown_s

    def should_skip(self, consecutive_blocked: int,
                    last_blocked_ts: float | None) -> bool:
        if consecutive_blocked < self.threshold:
            return False
        if last_blocked_ts is None:
            return True
        return (time.time() - last_blocked_ts) < self.cooldown_s

    def record_success(self) -> tuple[int, None]:
        return 0, None

    def record_blocked(self, prev: int) -> int:
        return prev + 1
