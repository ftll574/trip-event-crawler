"""L4 Flex Message 卡片組裝。

依【03】§3：carousel ≤12 bubbles；altText 必寫；折扣大字色塊；倒數為純文字；
footer uri 開活動頁＋postback「開賣前提醒我」。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .line_client import MAX_CAROUSEL_BUBBLES

ACCENT = "#EB471E"      # Trip.com 品牌橘
MUTED = "#8C8C8C"


def _fmt_ms(ms: int | None, tz_label: str) -> str:
    if not ms:
        return "時間未定"
    dt = datetime.fromtimestamp(ms / 1000, tz=UTC)
    base = dt.strftime("%m-%d %H:%M")
    return f"{base} UTC（{tz_label or '見活動頁'}）"


def _countdown_text(end_ms: int | None) -> str:
    if not end_ms:
        return ""
    delta = end_ms - int(datetime.now(UTC).timestamp() * 1000)
    if delta <= 0:
        return "⏰ 已結束"
    days = delta // 86_400_000
    if days >= 1:
        return f"⏰ 倒數 {days} 天"
    hours = delta // 3_600_000
    return f"⏰ 倒數 {hours} 小時" if hours >= 1 else "⏰ 即將結束！"


def build_bubble(ev: dict) -> dict:
    """單一活動 bubble。輸入為 events.json 的公開欄位 dict。"""
    title = ev.get("title") or "(未命名活動)"
    if len(title) > 60:
        title = title[:57] + "…"
    sale_line = _fmt_ms(ev.get("start_ms"), ev.get("tz_label", ""))
    end_line = _fmt_ms(ev.get("end_ms"), ev.get("tz_label", ""))
    discount = ev.get("discount_text") or "限時優惠"
    stock = ev.get("stock_text") or ""

    body_contents: list[dict] = [
        {"type": "text", "text": discount, "size": "xxl",
         "color": ACCENT, "weight": "bold", "wrap": True},
        {"type": "text", "text": title, "size": "md", "weight": "bold",
         "wrap": True, "margin": "sm"},
        {"type": "separator", "margin": "md"},
        {"type": "box", "layout": "baseline", "margin": "md", "contents": [
            {"type": "text", "text": "開賣", "size": "xs", "color": MUTED,
             "flex": 2},
            {"type": "text", "text": sale_line, "size": "sm", "flex": 5,
             "wrap": True},
        ]},
        {"type": "box", "layout": "baseline", "margin": "sm", "contents": [
            {"type": "text", "text": "結束", "size": "xs", "color": MUTED,
             "flex": 2},
            {"type": "text", "text": end_line, "size": "sm", "flex": 5,
             "wrap": True},
        ]},
    ]
    countdown = _countdown_text(ev.get("end_ms"))
    if countdown:
        body_contents.append(
            {"type": "text", "text": countdown, "size": "sm",
             "color": ACCENT if "即將" in countdown or "小時" in countdown
             else MUTED, "margin": "md"})
    if stock and not ev.get("sold_out"):
        body_contents.append(
            {"type": "text", "text": stock, "size": "xs", "color": MUTED,
             "wrap": True, "margin": "sm"})

    event_key = ev.get("event_key", "")
    footer_buttons: list[dict[str, Any]] = [
        {
            "type": "button",
            "action": {
                "type": "uri",
                "label": "前往活動頁",
                "uri": ev.get("url") or "https://tw.trip.com/sale/deals/",
            },
            "style": "primary",
            "color": ACCENT,
        },
    ]
    if event_key:
        footer_buttons.append({
            "type": "button",
            "action": {
                "type": "postback",
                "label": "開賣前提醒我",
                "data": f"action=subscribe&k={event_key}",
                "displayText": "好，幫我設定開賣提醒！",
            },
            "style": "link",
        })
    footer = {"type": "box", "layout": "vertical", "contents": footer_buttons}

    return {
        "type": "bubble",
        "header": {
            "type": "box", "layout": "vertical",
            "backgroundColor": ACCENT, "paddingAll": "md",
            "contents": [
                {"type": "text", "text": f"[{ev.get('market', '').upper()}] "
                 "Trip.com 快報", "color": "#FFFFFF", "size": "sm",
                 "weight": "bold"},
            ],
        },
        "body": {"type": "box", "layout": "vertical",
                 "contents": body_contents},
        "footer": footer,
    }


def build_carousel(events: list[dict]) -> dict | None:
    """組 carousel；超過上限截斷。空清單回 None。"""
    if not events:
        return None
    bubbles = [build_bubble(e) for e in events[:MAX_CAROUSEL_BUBBLES]]
    head = events[0].get("title") or "Trip.com 活動"
    alt = f"[Trip快報] {head}" + (f" 等 {len(events)} 個活動"
                                 if len(events) > 1 else "")
    return {
        "type": "flex",
        "altText": alt[:400],
        "contents": {"type": "carousel", "contents": bubbles},
    }


def chunk_events(events: list[dict], per_message: int = MAX_CAROUSEL_BUBBLES
                 ) -> list[list[dict]]:
    return [events[i:i + per_message]
            for i in range(0, len(events), per_message)]
