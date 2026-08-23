"""提醒排程掃描（Vercel Cron：每分鐘，Pro 方案）。

路由：GET /api/cron_remind
- Vercel 會自動帶 Authorization: Bearer $CRON_SECRET（有設定時）
- 讀 data/events.json（crawl workflow 每輪 commit）＋解密 data/subscriptions.enc
- 到期訂閱 → multicast 提醒卡（X-Line-Retry-Key 冪等，防 cron 重疊重發）
- 送出後 fire-and-forget 派發 mark-sent 給 GitHub workflow 落盤
"""

from __future__ import annotations

import contextlib
import json
import sys
import time
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
from tripbot.flex import build_bubble  # noqa: E402
from tripbot.line_client import LineClient  # noqa: E402
from tripbot.publish import load_published  # noqa: E402
from tripbot.subs import load_subs, mark_sent, prune, save_subs  # noqa: E402

PUBLISHED = str(ROOT / "data" / "events.json")
SUBS = str(ROOT / "data" / "subscriptions.enc")
GRACE_MS = 10 * 60 * 1000  # 開賣後 10 分鐘內仍可補送


class handler(BaseHTTPRequestHandler):  # noqa: N801 - Vercel 慣例
    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        settings = Settings.from_env()
        auth = self.headers.get("Authorization", "")
        if settings.cron_secret and auth != f"Bearer {settings.cron_secret}":
            self._json(401, {"error": "unauthorized"})
            return

        now_ms = int(time.time() * 1000)
        events = {e["event_key"]: e
                  for e in load_published(PUBLISHED).get("events", [])}
        key = settings.subs_fernet_key
        if not key:
            self._json(500, {"error": "SUBS_FERNET_KEY 未設定"})
            return
        subs = load_subs(SUBS, key)

        due_by_event: dict[str, list[dict]] = {}
        for s in subs:
            if s.get("sent"):
                continue
            ev = events.get(s["k"])
            if ev is None:
                continue
            start_ms = ev.get("start_ms") or s["at"] + GRACE_MS
            if s["at"] <= now_ms < start_ms + GRACE_MS:
                due_by_event.setdefault(s["k"], []).append(s)

        sent_total = 0
        errors: list[str] = []
        if due_by_event and settings.line_channel_access_token:
            lc = LineClient(settings.line_channel_access_token)
            try:
                for event_key, group in due_by_event.items():
                    users = [s["u"] for s in group][:500]
                    remind_at = int(group[0]["at"])
                    card = build_bubble(events[event_key])
                    card["altText"] = (
                        f"⏰ 快開賣了！{events[event_key].get('title', '')}"
                    )[:400]
                    card.setdefault("footer", {}).setdefault(
                        "contents", []
                    ).append({
                        "type": "button",
                        "action": {
                            "type": "uri",
                            "label": "立即前往",
                            "uri": events[event_key].get("url"),
                        },
                        "style": "primary",
                    })
                    try:
                        lc.multicast(users, [card])
                        mark_sent(subs, event_key, remind_at)
                        sent_total += len(users)
                        _dispatch_mark_sent(settings, subs)
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"{event_key[:8]}: {exc}")
            finally:
                lc.close()

        save_subs(SUBS, key, prune(subs))
        self._json(200, {"ok": not errors, "sent": sent_total,
                         "due_events": len(due_by_event),
                         "errors": errors})


def _dispatch_mark_sent(settings: Settings, subs: list[dict]) -> None:
    """把 sent 狀態落盤（fire-and-forget；retry-key 已防短期重複推播）。"""
    if not (settings.gh_token and settings.gh_repo):
        return
    from tripbot.subs import _fernet

    blob = _fernet(settings.subs_fernet_key).encrypt(
        json.dumps({"version": 1, "subs": subs}, ensure_ascii=False).encode()
    ).decode()
    with contextlib.suppress(httpx.HTTPError):
        httpx.post(
            f"https://api.github.com/repos/{settings.gh_repo}/dispatches",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {settings.gh_token}",
            },
            json={"event_type": "sub-update",
                  "client_payload": {"blob": blob}},
            timeout=10.0,
        )
