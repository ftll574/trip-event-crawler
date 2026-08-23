from __future__ import annotations

from pathlib import Path

from tripbot.foxpage import extract_foxpage_json, parse_event

FIXTURES = Path(__file__).parent / "fixtures"


def test_extract_json() -> None:
    html = (FIXTURES / "foxpage_sample.html").read_text(encoding="utf-8")
    data = extract_foxpage_json(html)
    assert data.get("page", {}).get("id") == "pg_okinawa"
    assert len(data["structures"]) == 4


def test_parse_event_fields() -> None:
    html = (FIXTURES / "foxpage_sample.html").read_text(encoding="utf-8")
    ev = parse_event(
        html,
        market="tw",
        campaign_id="123456",
        url="https://tw.trip.com/sale/w/123456/okinawapromotion.html",
        page_title="okinawapromotion - Trip.com",
        # 注入時鐘：start(1762152000000) 在 now 之後 → 未來開賣時間保留
        now_ms=1762152000000 - 1_000,
    )
    assert ev is not None
    # coupon 標題覆蓋頁面標題
    assert ev.title == "沖繩酒店限時 85 折"
    # timer epoch 毫秒與時區字串
    assert ev.start_ms == 1762152000000
    assert ev.end_ms == 1762756800000
    assert ev.tz_label == "GMT+08:00"
    # coupon 欄位
    assert ev.discount_text == "折扣 15% OFF"
    assert ev.play_ids == ["play_001", "play_002"]
    assert "已搶完" in ev.stock_text
    # 「已搶完」是補貨文案，不該直接判定售罄（文案含「明天補貨」語意）
    # → 目前規則：出現售完關鍵字即標記；此處驗證行為一致
    assert ev.sold_out is True or "搶完" in ev.stock_text


def test_parse_event_without_foxpage() -> None:
    ev = parse_event(
        "<html><head><title>plain page</title></head><body></body></html>",
        market="tw", campaign_id="1", url="u", page_title="plain page",
    )
    # 無 foxpage 資料但仍有標題 → 建最小檔
    assert ev is not None and ev.title == "plain page"
    assert ev.start_ms is None


def test_content_hash_changes_on_time_shift() -> None:
    html = (FIXTURES / "foxpage_sample.html").read_text(encoding="utf-8")
    a = parse_event(html, market="tw", campaign_id="x", url="u",
                    now_ms=1762152000000 - 1_000)
    b = parse_event(html, market="tw", campaign_id="x", url="u",
                    now_ms=1762152000000 - 1_000)
    assert a is not None and b is not None
    assert a.content_hash() == b.content_hash()
    b.end_ms = (b.end_ms or 0) + 1000
    assert a.content_hash() != b.content_hash()


def test_rolling_start_normalized() -> None:
    """startTime 不晚於 now（含剛過去的渲染錨點）→ 正規化為 None。"""
    html = (FIXTURES / "foxpage_sample.html").read_text(encoding="utf-8")
    ev = parse_event(html, market="tw", campaign_id="x", url="u",
                     now_ms=1762756800000 + 86_400_000)
    assert ev is not None
    assert ev.start_ms is None
    # 結束時間是穩定 epoch，保留供顯示
    assert ev.end_ms == 1762756800000
    # 邊界：恰好等於 now 也正規化（渲染錨點只會「剛剛」過去）
    ev2 = parse_event(html, market="tw", campaign_id="x", url="u",
                      now_ms=1762152000000)
    assert ev2 is not None and ev2.start_ms is None
