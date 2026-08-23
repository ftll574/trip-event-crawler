from __future__ import annotations

from pathlib import Path

from tripbot.discover import discover_campaign_links

FIXTURES = Path(__file__).parent / "fixtures"


def test_discover_dedup_and_absolute() -> None:
    html = (FIXTURES / "hub_sample.html").read_text(encoding="utf-8")
    links = discover_campaign_links(
        html, "https://tw.trip.com/sale/deals/"
    )
    ids = [cid for cid, _ in links]
    # 三個活動；重複連結（同 id 相對路徑）被去重
    assert ids == ["123456", "ab12cd34ef56gh78", "998877"]
    urls = dict(links)
    assert urls["123456"].startswith("https://tw.trip.com/sale/w/")
    assert urls["123456"].endswith("/okinawapromotion.html")


def test_discover_empty() -> None:
    assert discover_campaign_links("<p>no deals</p>", "https://tw.trip.com") == []
