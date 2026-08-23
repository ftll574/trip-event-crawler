"""營運告警：healthchecks.io 死人開關 ＋ ntfy.sh 通知。依【02】§7。"""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)


def ping_healthchecks(url: str, *, ok: bool = True) -> None:
    """成功 ping 主 URL；失敗 ping /fail 端點（逾時未收到即告警）。"""
    if not url:
        return
    target = url if ok else url.rstrip("/") + "/fail"
    try:
        httpx.get(target, timeout=10.0)
    except httpx.HTTPError as exc:
        log.warning("healthchecks ping 失敗: %s", exc)


def ntfy(topic_url: str, title: str, message: str,
         *, priority: str = "default") -> None:
    """推營運通知到 ntfy topic（可裝 App 收推播）。"""
    if not topic_url:
        return
    try:
        httpx.post(
            topic_url,
            content=message.encode("utf-8"),
            headers={"Title": title, "Priority": priority},
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        log.warning("ntfy 推送失敗: %s", exc)
