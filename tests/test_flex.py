from __future__ import annotations

from tripbot.flex import build_bubble, build_carousel, chunk_events

EVENT = {
    "event_key": "k" * 64,
    "market": "tw",
    "campaign_id": "123456",
    "url": "https://tw.trip.com/sale/w/123456/okinawapromotion.html",
    "title": "沖繩酒店限時 85 折",
    "start_ms": 1762152000000,
    "end_ms": 1762756800000,
    "tz_label": "GMT+08:00",
    "discount_text": "折扣 15% OFF",
    "stock_text": "限量 500 組",
}


def test_carousel_structure() -> None:
    card = build_carousel([EVENT] * 3)
    assert card is not None
    assert card["type"] == "flex"
    assert len(card["altText"]) <= 400
    bubbles = card["contents"]["contents"]
    assert len(bubbles) == 3
    b0 = bubbles[0]
    assert b0["type"] == "bubble"
    buttons = b0["footer"]["contents"]
    kinds = {btn["action"]["type"] for btn in buttons}
    assert kinds == {"uri", "postback"}
    postback = next(b for b in buttons if b["action"]["type"] == "postback")
    assert postback["action"]["data"].startswith("action=subscribe&k=")


def test_carousel_empty_returns_none() -> None:
    assert build_carousel([]) is None


def test_chunking_caps_at_12() -> None:
    chunks = chunk_events([EVENT] * 25)
    assert all(len(c) <= 12 for c in chunks)
    assert sum(len(c) for c in chunks) == 25


def test_long_title_truncated() -> None:
    long_ev = dict(EVENT, title="長" * 100)
    bubble = build_bubble(long_ev)
    texts = str(bubble["body"])
    assert "…" in texts or len("長" * 100) < 60
