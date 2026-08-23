from __future__ import annotations

from pathlib import Path

from tripbot.subs import load_subs, mark_sent, prune, save_subs, upsert


def test_roundtrip(tmp_path):
    key = "test-key"
    path = str(tmp_path / "subscriptions.enc")
    subs = upsert([], "U123", "K1", 1700000000000)
    subs = upsert(subs, "U456", "K2", 1700000100000)
    save_subs(path, key, subs)

    loaded = load_subs(path, key)
    assert len(loaded) == 2
    assert loaded[0]["u"] == "U123"
    # 明文不落盤
    raw = Path(path).read_text(encoding="utf-8")
    assert "U123" not in raw


def test_upsert_updates_existing() -> None:
    subs = upsert([], "U1", "K1", 1000)
    subs = upsert(subs, "U1", "K1", 2000)
    assert len(subs) == 1 and subs[0]["at"] == 2000
    assert subs[0]["sent"] is False


def test_mark_sent() -> None:
    subs = upsert([], "U1", "K1", 1000)
    n = mark_sent(subs, "K1", 1000)
    assert n == 1 and subs[0]["sent"] is True


def test_prune_drops_old_and_dupes() -> None:
    import time

    old_at = int((time.time() - 40 * 86400) * 1000)
    subs = [
        {"u": "U1", "k": "K1", "at": old_at, "sent": False},
        {"u": "U2", "k": "K2", "at": int(time.time() * 1000), "sent": False},
        {"u": "U2", "k": "K2", "at": int(time.time() * 1000), "sent": False},
    ]
    kept = prune(subs)
    assert len(kept) == 1
    assert kept[0]["u"] == "U2"
