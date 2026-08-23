"""發佈層：把 SQLite 的 active 活動匯出到 data/events.json。

Vercel 端（webhook 歡迎清單 / 提醒 cron / .ics）讀 repo 內這個檔案，
由 crawl workflow 每輪 commit、自動觸發 Vercel redeploy。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .db import active_events


def publish(conn: sqlite3.Connection, out_path: str,
            generated_at: str | None = None) -> int:
    events = active_events(conn)
    payload = {
        "version": 1,
        "generated_at": generated_at,  # 呼叫端帶入 ISO 時間；測試可省
        "events": [e.to_public_dict() for e in events],
    }
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return len(events)


def load_published(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {"version": 0, "events": []}
    return json.loads(p.read_text(encoding="utf-8"))
