from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_api(name: str):
    """Vercel api/ 檔案以路徑載入（非套件）；測試沿用同方式。"""
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "api" / f"{name}.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_build_ics_basic() -> None:
    ics_mod = _load_api("ics")
    events = [
        {
            "event_key": "a" * 64,
            "market": "tw",
            "title": "雙11 旅展；機票 11 元",
            "start_ms": 1762152000000,
            "end_ms": 1762756800000,
            "tz_label": "GMT+08:00",
            "discount_text": "限時 5 天",
            "url": "https://tw.trip.com/sale/w/x/y.html",
        },
        {
            "event_key": "b" * 64,
            "market": "jp",
            "title": "no start time",
            "start_ms": None,
            "end_ms": None,
        },
    ]
    text = ics_mod.build_ics(events, market="tw")
    assert text.startswith("BEGIN:VCALENDAR")
    assert "BEGIN:VEVENT" in text and "END:VEVENT" in text
    # jp 活動被 market 過濾
    assert text.count("BEGIN:VEVENT") == 1
    # RFC5545 跳脫：分號要轉義
    assert r"；" in text or "\\;" in text
    assert "DTSTART:20251103" in text  # 1762152000000 = 2025-11-03T08:00Z
