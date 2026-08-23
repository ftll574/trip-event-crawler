"""搶購日曆 .ics 端點。

路由：GET /api/ics?market=tw（market 可省略＝全部市場）
讓用戶以 webcal:// 或下載方式加到手機日曆（瀏覽不吃 LINE 配額，【03】§4(c)）。
UID 固定為 {event_key}@tripbot → 活動異動時日曆端可自動更新。
"""

from __future__ import annotations

import sys
import urllib.parse
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler
from pathlib import Path

# Vercel 以檔案路徑載入本檔：手動把 api/ 與 repo 根目錄放進 sys.path
_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tripbot.publish import load_published  # noqa: E402

PUBLISHED = str(ROOT / "data" / "events.json")


def _esc(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\n", "\\n"))


def _dt(ms: int | None, default_offset_ms: int = 0) -> str | None:
    if not ms:
        return None
    dt = datetime.fromtimestamp((ms + default_offset_ms) / 1000,
                                tz=UTC)
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _fold(line: str) -> str:
    """RFC5545 75-octet 折行（保守用字元數近似）。"""
    out: list[str] = []
    while len(line.encode("utf-8")) > 73:
        cut = 70
        while len(line[:cut].encode("utf-8")) > 73 and cut > 10:
            cut -= 1
        out.append(line[:cut])
        line = " " + line[cut:]
    out.append(line)
    return "\r\n".join(out)


def build_ics(events: list[dict], market: str | None = None) -> str:
    if market:
        events = [e for e in events if e.get("market") == market]
    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//tripbot//Trip.com promo calendar//TW",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Trip.com 搶購日曆",
        "X-WR-TIMEZONE:Asia/Taipei",
    ]
    now = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    for e in events:
        start = _dt(e.get("start_ms"))
        end = _dt(e.get("end_ms"))
        if not start:
            continue
        uid = f"{e['event_key']}@tripbot"
        summary = f"[{e.get('market', '').upper()}] {_esc(e.get('title', '活動'))}"
        desc_bits = [e.get("discount_text", ""),
                     f"開賣：{start}（{_esc(e.get('tz_label', ''))}）",
                     e.get("sale_note", "")]
        desc = _esc("\n".join(b for b in desc_bits if b))[:900]
        url = e.get("url", "")
        lines += [
            "BEGIN:VEVENT",
            _fold(f"UID:{uid}"),
            _fold(f"DTSTAMP:{now}"),
            _fold(f"DTSTART:{start}"),
        ]
        if end:
            lines.append(_fold(f"DTEND:{end}"))
        lines += [
            _fold(f"SUMMARY:{summary}"),
            _fold(f"DESCRIPTION:{desc}"),
            _fold(f"URL:{url}"),
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


class handler(BaseHTTPRequestHandler):  # noqa: N801 - Vercel 慣例
    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        market = (qs.get("market") or [None])[0]

        pub = load_published(PUBLISHED)
        ics = build_ics(pub.get("events", []), market)
        body = ics.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type",
                         "text/calendar; charset=utf-8")
        self.send_header("Content-Disposition",
                         'attachment; filename="trip-deals.ics"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
