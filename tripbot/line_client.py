"""L4 LINE Messaging API 客戶端（httpx 直連，刻意不依賴官方 SDK）。

不用 SDK 的理由（記錄於 README）：
1. 我們只用 5 個 endpoint（broadcast/multicast/reply/push/quota），SDK 體積與
   版本漂移在 serverless 冷啟動上不划算。
2. X-Line-Retry-Key 冪等重試需要精確控制（【03】§2.3）。

配額治理依【03】§2：訊息數＝收件人數；每輪推播前可查 quota/consumption。
"""

from __future__ import annotations

import json
import logging
import uuid

import httpx

log = logging.getLogger(__name__)

API_BASE = "https://api.line.me"
MAX_MULTICAST_IDS = 500          # 【03】§2.3
MAX_CAROUSEL_BUBBLES = 12        # Flex carousel 上限


class LineError(Exception):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"LINE API error {status}: {body[:300]}")
        self.status = status
        self.body = body


class LineClient:
    def __init__(self, channel_access_token: str) -> None:
        self._token = channel_access_token
        self._client = httpx.Client(
            base_url=API_BASE,
            timeout=15.0,
            headers={"Authorization": f"Bearer {channel_access_token}"},
        )

    def close(self) -> None:
        self._client.close()

    # ---------- 低階 ----------

    def _post(self, path: str, payload: dict,
              retry_key: str | None = None) -> dict:
        headers = {"Content-Type": "application/json"}
        if retry_key:
            headers["X-Line-Retry-Key"] = retry_key  # 冪等：同 key 不重複送
        resp = self._client.post(path, json=payload, headers=headers)
        if resp.status_code >= 400:
            raise LineError(resp.status_code, resp.text)
        return resp.json() if resp.content else {}

    # ---------- 發送 ----------

    def broadcast(self, messages: list[dict],
                  *, retry_key: str | None = None,
                  notification_disabled: bool = False) -> dict:
        """推給全部好友。messages ≤ 5 則/req（計費＝收件人數）。"""
        assert 1 <= len(messages) <= 5
        return self._post(
            "/v2/bot/message/broadcast",
            {"messages": messages},
            retry_key=retry_key or _rk(
                "bc", json.dumps(messages, sort_keys=True, ensure_ascii=False)),
        )

    def multicast(self, user_ids: list[str], messages: list[dict], *,
                  notification_disabled: bool = False) -> dict:
        """精準推給指定 userIds（≤500/req）。提醒走這裡省配額。"""
        assert 1 <= len(user_ids) <= MAX_MULTICAST_IDS
        assert 1 <= len(messages) <= 5
        return self._post(
            "/v2/bot/message/multicast",
            {"to": user_ids, "messages": messages},
            retry_key=_rk("mc", "".join(user_ids[:5]) + str(len(user_ids))
                          + messages[0].get("altText", "")),
        )

    def push(self, user_id: str, messages: list[dict]) -> dict:
        return self._post(
            "/v2/bot/message/push",
            {"to": user_id, "messages": messages},
        )

    def reply(self, reply_token: str, messages: list[dict]) -> dict:
        """Reply API 免費不吃配額 → 所有互動回覆都走這裡。"""
        assert 1 <= len(messages) <= 5
        return self._post(
            "/v2/bot/message/reply",
            {"replyToken": reply_token, "messages": messages},
        )

    # ---------- 配額 ----------

    def quota_consumption(self) -> dict:
        resp = self._client.get("/v2/bot/message/quota/consumption")
        if resp.status_code >= 400:
            raise LineError(resp.status_code, resp.text)
        return resp.json()


def _rk(kind: str, seed: str) -> str:
    """穩定 UUID（同邏輯事件重跑不會重複推播）。"""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"tripbot:{kind}:{seed}"))
