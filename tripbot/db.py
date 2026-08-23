"""SQLite(WAL) 儲存層。Schema 依【02】§6 提案微調。"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .models import Event, now_iso

DDL = """
CREATE TABLE IF NOT EXISTS events (
  event_key    TEXT PRIMARY KEY,
  market       TEXT NOT NULL,
  campaign_id  TEXT NOT NULL DEFAULT '',
  title        TEXT NOT NULL DEFAULT '',
  url          TEXT NOT NULL DEFAULT '',
  start_ms     INTEGER,
  end_ms       INTEGER,
  tz_label     TEXT NOT NULL DEFAULT '',
  sale_note    TEXT NOT NULL DEFAULT '',
  discount_text TEXT NOT NULL DEFAULT '',
  stock_text   TEXT NOT NULL DEFAULT '',
  sold_out     INTEGER NOT NULL DEFAULT 0,
  scope_text   TEXT NOT NULL DEFAULT '',
  play_ids_json TEXT NOT NULL DEFAULT '[]',
  tnc_sha      TEXT NOT NULL DEFAULT '',
  extra_json   TEXT NOT NULL DEFAULT '{}',
  content_hash TEXT NOT NULL DEFAULT '',
  status       TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','ended')),
  missed_polls INTEGER NOT NULL DEFAULT 0,
  first_seen   TEXT NOT NULL DEFAULT '',
  last_seen    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_events_market ON events(market, status);

CREATE TABLE IF NOT EXISTS snapshots (
  event_key    TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  captured_at  TEXT NOT NULL,
  raw_json     TEXT NOT NULL,
  PRIMARY KEY (event_key, captured_at)
);

CREATE TABLE IF NOT EXISTS scrape_runs (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at  TEXT NOT NULL,
  finished_at TEXT,
  markets     TEXT NOT NULL DEFAULT '',
  found       INTEGER NOT NULL DEFAULT 0,
  new_count   INTEGER NOT NULL DEFAULT 0,
  modified    INTEGER NOT NULL DEFAULT 0,
  ended       INTEGER NOT NULL DEFAULT 0,
  errors      INTEGER NOT NULL DEFAULT 0,
  ok          INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL DEFAULT ''
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(DDL)
    return conn


@contextmanager
def session(db_path: str) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ---------- events ----------

def _row_to_event(r: sqlite3.Row) -> Event:
    return Event(
        market=r["market"],
        campaign_id=r["campaign_id"],
        url=r["url"],
        title=r["title"],
        start_ms=r["start_ms"],
        end_ms=r["end_ms"],
        tz_label=r["tz_label"],
        sale_note=r["sale_note"],
        discount_text=r["discount_text"],
        stock_text=r["stock_text"],
        sold_out=bool(r["sold_out"]),
        scope_text=r["scope_text"],
        play_ids=json.loads(r["play_ids_json"]),
        status=r["status"],
        missed_polls=r["missed_polls"],
        first_seen=r["first_seen"],
        last_seen=r["last_seen"],
    )


_EVENT_COLS = (
    "event_key, market, campaign_id, title, url, start_ms, end_ms, tz_label, "
    "sale_note, discount_text, stock_text, sold_out, scope_text, play_ids_json, "
    "tnc_sha, extra_json, content_hash, status, missed_polls, first_seen, last_seen"
)


def upsert_event(conn: sqlite3.Connection, ev: Event, tnc_sha: str = "",
                 extra: dict | None = None) -> None:
    conn.execute(
        f"""INSERT INTO events ({_EVENT_COLS})
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(event_key) DO UPDATE SET
              title=excluded.title, url=excluded.url, start_ms=excluded.start_ms,
              end_ms=excluded.end_ms, tz_label=excluded.tz_label,
              sale_note=excluded.sale_note, discount_text=excluded.discount_text,
              stock_text=excluded.stock_text, sold_out=excluded.sold_out,
              scope_text=excluded.scope_text, play_ids_json=excluded.play_ids_json,
              tnc_sha=excluded.tnc_sha, extra_json=excluded.extra_json,
              content_hash=excluded.content_hash, status='active',
              missed_polls=0, last_seen=excluded.last_seen
        """,
        (
            ev.event_key, ev.market, ev.campaign_id, ev.title, ev.url,
            ev.start_ms, ev.end_ms, ev.tz_label, ev.sale_note,
            ev.discount_text, ev.stock_text, int(ev.sold_out), ev.scope_text,
            json.dumps(ev.play_ids, ensure_ascii=False), tnc_sha,
            json.dumps(extra or {}, ensure_ascii=False), ev.content_hash(),
            "active", 0, ev.first_seen or now_iso(), now_iso(),
        ),
    )


def get_event(conn: sqlite3.Connection, event_key: str) -> Event | None:
    r = conn.execute(
        f"SELECT {_EVENT_COLS} FROM events WHERE event_key=?", (event_key,)
    ).fetchone()
    return _row_to_event(r) if r else None


def mark_missed_and_ended(conn: sqlite3.Connection, seen_keys: set[str],
                          threshold: int = 2,
                          market: str | None = None) -> list[Event]:
    """本次未出現的事件：missed_polls += 1；連續達標才判 ENDED（防渲染失敗誤報）。

    market 指定時只比對該市場——單市場輪詢不會把其他市場誤判 missed。
    """
    sql = f"SELECT {_EVENT_COLS} FROM events WHERE status='active'"
    args: tuple = ()
    if market:
        sql += " AND market=?"
        args = (market,)
    rows = conn.execute(sql, args).fetchall()
    ended: list[Event] = []
    for r in rows:
        if r["event_key"] in seen_keys:
            continue
        missed = int(r["missed_polls"]) + 1
        status = "ended" if missed >= threshold else "active"
        conn.execute(
            "UPDATE events SET missed_polls=?, status=? WHERE event_key=?",
            (missed, status, r["event_key"]),
        )
        if status == "ended":
            ev = _row_to_event(r)
            ev.status = status
            ev.missed_polls = missed
            ended.append(ev)
    return ended


def active_events(conn: sqlite3.Connection, market: str | None = None) -> list[Event]:
    sql = f"SELECT {_EVENT_COLS} FROM events WHERE status='active'"
    args: tuple = ()
    if market:
        sql += " AND market=?"
        args = (market,)
    return [_row_to_event(r) for r in conn.execute(sql, args)]


# ---------- snapshots / runs / meta ----------

def save_snapshot(conn: sqlite3.Connection, event_key: str, content_hash: str,
                  raw: dict, keep: int = 5) -> None:
    ts = now_iso()
    conn.execute(
        "INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?)",
        (event_key, content_hash, ts, json.dumps(raw, ensure_ascii=False)),
    )
    old = conn.execute(
        "SELECT captured_at FROM snapshots WHERE event_key=? ORDER BY captured_at DESC",
        (event_key,),
    ).fetchall()
    for row in old[keep:]:
        conn.execute(
            "DELETE FROM snapshots WHERE event_key=? AND captured_at=?",
            (event_key, row["captured_at"]),
        )


def record_run_start(conn: sqlite3.Connection, markets: str) -> int:
    cur = conn.execute(
        "INSERT INTO scrape_runs (started_at, markets) VALUES (?,?)",
        (now_iso(), markets),
    )
    return int(cur.lastrowid or 0)


def record_run_end(conn: sqlite3.Connection, run_id: int, **counts: int) -> None:
    sets = ",".join(f"{k}=?" for k in counts)
    conn.execute(
        f"UPDATE scrape_runs SET finished_at=?, ok=1, {sets} WHERE id=?",
        (now_iso(), *counts.values(), run_id),
    )


def get_meta(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    r = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return r["value"] if r else default


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key,value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
