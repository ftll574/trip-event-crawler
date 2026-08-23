"""三態變更偵測（NEW / MODIFIED / ENDED）的純函式部分。

db.mark_missed_and_ended 已處理 ENDED；此模組提供掃描層的分類輔助，
讓 run_crawl 與測試共用同一套語意。
"""

from __future__ import annotations

from .models import Event, semantic_diff


def classify(old: Event | None, new: Event) -> tuple[str, dict]:
    """回傳 (status, diff)；status ∈ {new, modified, same}。"""
    if old is None:
        return "new", {}
    if old.content_hash() != new.content_hash():
        return "modified", semantic_diff(old, new)
    return "same", {}


def classify_market_scan(current: dict[str, Event],
                         previous: dict[str, Event]) -> dict[str, list[Event]]:
    """以整個市場視角分類（供測試與未來批次重構使用）。

    ENDED 不在此判定（需連續缺席 2–3 次，由 db 層 missed_polls 處理，
    防【02】§5 提到的單次渲染失敗誤報）。
    """
    out: dict[str, list[Event]] = {"new": [], "modified": [], "same": [],
                                   "missing": []}
    for key, ev in current.items():
        old = previous.get(key)
        status, _ = classify(old, ev)
        out[status].append(ev)
    for key, ev in previous.items():
        if key not in current:
            out["missing"].append(ev)
    return out
