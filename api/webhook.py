"""LINE Webhook 接收端（Vercel Python Function）。

路由：POST /api/webhook
- 驗 x-line-signature（HMAC-SHA256，見 tripbot/linesec.py）
- follow   → Reply API 回 Flex 活動清單歡迎訊息（免費、不吃配額）
- postback → 訂閱/取消提醒：加密 payload → GitHub repository_dispatch →
             workflows/subs.yml 更新 data/subscriptions.enc

依【03】§6.1：先快速回 200；本 handler 全程同步但夠快（<數秒）。
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler
from pathlib import Path

# Vercel 以檔案路徑載入本檔：手動把 api/ 與 repo 根目錄放進 sys.path
_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
for _p in (str(_HERE), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import httpx  # noqa: E402

from tripbot.config import Settings  # noqa: E402
from tripbot.flex import build_carousel  # noqa: E402
from tripbot.linesec import verify_signature  # noqa: E402
from tripbot.publish import load_published  # noqa: E402
from tripbot.subs import _fernet  # noqa: E402

PUBLISHED = str(ROOT / "data" / "events.json")
REMIND_OFFSET_MS = 15 * 60 * 1000  # T-15min（Q4 可調）


class handler(BaseHTTPRequestHandler):  # noqa: N801 - Vercel 慣例
    def _reply_json(self, code: int, payload: dict | list | None = None) -> None:
        body = json.dumps(payload or {}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        self._reply_json(200, {"ok": True})

    def do_POST(self) -> None:  # noqa: N802
        settings = Settings.from_env()
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        sig = self.headers.get("x-line-signature", "")

        if not settings.line_channel_secret:
            self._reply_json(500, {"error": "LINE_CHANNEL_SECRET 未設定"})
            return
        if not verify_signature(settings.line_channel_secret, raw, sig):
            self._reply_json(403, {"error": "invalid signature"})
            return

        # 先盡快回 200（驗章已完成，後續處理同步進行但很短）
        self._reply_json(200)

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return
        self._handle_events(payload, settings)

    # ---------- 事件處理 ----------

    def _handle_events(self, payload: dict, settings: Settings) -> None:
        token = settings.line_channel_access_token
        if not token:
            return
        for ev in payload.get("events", []):
            etype = ev.get("type")
            if etype == "follow":
                self._welcome(settings, ev.get("replyToken", ""))
            elif etype == "postback":
                self._postback(settings, ev)


def _welcome(settings: Settings, reply_token: str) -> None:
    from tripbot.line_client import LineClient

    pub = load_published(PUBLISHED)
    card = build_carousel(pub.get("events", [])[:8])
    if card is None:
        card = {
            "type": "text",
            "text": "歡迎加入！目前尚無活動資料，稍後再來看看 🎉",
        }
    lc = LineClient(settings.line_channel_access_token)
    try:
        lc.reply(reply_token, [card])
    finally:
        lc.close()


def _gh_dispatch(settings: Settings, inner: dict) -> bool:
    """把加密後的訂閱變更丟給 GitHub workflow（fire-and-forget）。"""
    if not (settings.gh_token and settings.gh_repo):
        return False
    blob = _fernet(settings.subs_fernet_key).encrypt(
        json.dumps(inner, ensure_ascii=False).encode()
    ).decode()
    resp = httpx.post(
        f"https://api.github.com/repos/{settings.gh_repo}/dispatches",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {settings.gh_token}",
        },
        json={"event_type": "sub-update",
              "client_payload": {"blob": blob}},
        timeout=10.0,
    )
    return resp.status_code == 204


def _postback(settings: Settings, ev: dict) -> None:
    data = urllib.parse.parse_qs(ev.get("postback", {}).get("data", ""))
    action = (data.get("action") or [""])[0]
    key = (data.get("k") or [""])[0]
    user_id = ev.get("source", {}).get("userId", "")
    reply_token = ev.get("replyToken", "")
    if not (action and key and user_id):
        return

    if action == "subscribe":
        pub_events = load_published(PUBLISHED).get("events", [])
        target = next((e for e in pub_events if e["event_key"] == key), None)
        if target is None:
            _safe_reply(settings, reply_token,
                        {"type": "text", "text": "這個活動已經下架囉 🙏"})
            return
        start_ms = int(target.get("start_ms") or time.time() * 1000)
        remind_at = max(0, start_ms - REMIND_OFFSET_MS)
        ok = _gh_dispatch(
            settings, {"op": "subscribe", "u": user_id, "k": key,
                       "at": remind_at}
        )
        msg = ("✅ 已設定開賣前 15 分鐘提醒！"
               if ok else "⚠️ 提醒服務設定中，請稍候再試。")
        _safe_reply(settings, reply_token, {"type": "text", "text": msg})
    elif action == "unsubscribe":
        _gh_dispatch(settings, {"op": "unsubscribe", "u": user_id, "k": key})
        _safe_reply(settings, reply_token,
                    {"type": "text", "text": "已取消這個活動的提醒。"})


def _safe_reply(settings: Settings, reply_token: str, message: dict) -> None:
    if not reply_token:
        return
    from tripbot.line_client import LineClient

    lc = LineClient(settings.line_channel_access_token)
    try:
        lc.reply(reply_token, [message])
    except Exception:  # noqa: BLE001 - webhook 內回覆失敗不影響主流程
        pass
    finally:
        lc.close()
