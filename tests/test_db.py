from __future__ import annotations

import sqlite3

from tripbot import db as dbm
from tripbot.models import Event


def _mk(market="tw", cid="1", title="t", start=1000, end=2000) -> Event:
    return Event(market=market, campaign_id=cid, url="u", title=title,
                 start_ms=start, end_ms=end)


def test_event_key_stable_and_distinct() -> None:
    a = _mk(cid="1")
    b = _mk(cid="1", title="changed")
    assert a.event_key == b.event_key          # 同 (market,cid) 同 key
    c = _mk(cid="2")
    assert a.event_key != c.event_key


def test_upsert_and_missed_ended(tmp_path) -> None:
    conn: sqlite3.Connection
    with dbm.session(str(tmp_path / "db.sqlite")) as conn:
        ev = _mk()
        dbm.upsert_event(conn, ev)
        assert dbm.get_event(conn, ev.event_key) is not None

        # 第一次缺席：只計 missed，不判 ENDED
        ended = dbm.mark_missed_and_ended(conn, seen_keys=set())
        assert ended == []
        row = conn.execute(
            "SELECT missed_polls, status FROM events").fetchone()
        assert row["missed_polls"] == 1 and row["status"] == "active"

        # 第二次缺席：判 ENDED
        ended = dbm.mark_missed_and_ended(conn, seen_keys=set())
        assert len(ended) == 1 and ended[0].status == "ended"

        # 再次出現：復活為 active、missed 歸零
        dbm.upsert_event(conn, ev)
        row = conn.execute(
            "SELECT missed_polls, status FROM events").fetchone()
        assert row["status"] == "active" and row["missed_polls"] == 0


def test_runs_and_meta(tmp_path) -> None:
    with dbm.session(str(tmp_path / "db.sqlite")) as conn:
        rid = dbm.record_run_start(conn, "tw")
        dbm.record_run_end(conn, rid, found=5, new_count=2, modified=1,
                           ended=0, errors=0)
        r = conn.execute("SELECT * FROM scrape_runs").fetchone()
        assert r["found"] == 5 and r["ok"] == 1

        dbm.set_meta(conn, "k", "v")
        assert dbm.get_meta(conn, "k") == "v"
        assert dbm.get_meta(conn, "missing", "d") == "d"
