from __future__ import annotations

from tripbot.detect import classify, classify_market_scan
from tripbot.models import Event


def _mk(cid="1", title="t", start=1000) -> Event:
    return Event(market="tw", campaign_id=cid, url="u", title=title,
                 start_ms=start)


def test_classify_states() -> None:
    old = _mk()
    assert classify(None, old)[0] == "new"
    assert classify(old, _mk())[0] == "same"
    status, diff = classify(old, _mk(title="new title"))
    assert status == "modified" and "title" in diff
    # start_ms 刻意不參與 content_hash（渲染錨點防誤報）
    status, _diff = classify(old, _mk(start=9999))
    assert status == "same"


def test_market_scan() -> None:
    prev = {"a": _mk(cid="a"), "b": _mk(cid="b")}
    cur = {"a": _mk(cid="a"), "c": _mk(cid="c", title="fresh")}
    out = classify_market_scan(cur, prev)
    assert [e.campaign_id for e in out["new"]] == ["c"]
    assert [e.campaign_id for e in out["modified"]] == []
    assert [e.campaign_id for e in out["same"]] == ["a"]
    assert [e.campaign_id for e in out["missing"]] == ["b"]
