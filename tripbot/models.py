"""資料模型與雜湊（event_key / content_hash）。

依計畫 §2-7：
- 身分＝(market, campaign_id)；campaign_id 缺時退回 sha256(標題|市場|起訖)。
- content_hash 覆蓋語意欄位，偵測 MODIFIED。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class Event:
    market: str
    campaign_id: str
    url: str
    title: str = ""
    start_ms: int | None = None
    end_ms: int | None = None
    tz_label: str = ""
    sale_note: str = ""
    discount_text: str = ""
    stock_text: str = ""
    sold_out: bool = False
    scope_text: str = ""
    play_ids: list[str] = field(default_factory=list)
    status: str = "active"
    missed_polls: int = 0
    first_seen: str = ""
    last_seen: str = ""

    @property
    def event_key(self) -> str:
        if self.campaign_id:
            basis = f"{self.market}:{self.campaign_id}"
        else:
            basis = (
                f"{self.title}|{self.market}|{self.start_ms}|{self.end_ms}"
            )
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()

    def content_hash(self) -> str:
        # 刻意不含 start_ms：實測部分票券頁的 timer.startTime 為「渲染錨點」，
        # 每輪重算（甚至渲染時間＋偏移的未來值），纳入會導致每輪誤報 MODIFIED。
        # 開賣時間仍照常 upsert／發佈／供提醒計算；end_ms 是穩定 epoch 保留。
        payload = {
            "title": self.title,
            "end_ms": self.end_ms,
            "tz_label": self.tz_label,
            "discount_text": self.discount_text,
            "stock_text": self.stock_text,
            "sold_out": self.sold_out,
            "scope_text": self.scope_text,
            "play_ids": sorted(self.play_ids),
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_public_dict(self) -> dict:
        """發佈到 data/events.json 的公開欄位（不含內部稽核欄位）。"""
        return {
            "event_key": self.event_key,
            "market": self.market,
            "campaign_id": self.campaign_id,
            "url": self.url,
            "title": self.title,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "tz_label": self.tz_label,
            "sale_note": self.sale_note,
            "discount_text": self.discount_text,
            "stock_text": self.stock_text,
            "sold_out": self.sold_out,
            "status": self.status,
        }


def semantic_diff(old: Event, new: Event) -> dict[str, tuple]:
    """回傳欄位級 diff {field: (old, new)}，用於 MODIFIED 推播摘要。"""
    fields = [
        "title", "start_ms", "end_ms", "tz_label", "sale_note",
        "discount_text", "stock_text", "sold_out", "scope_text",
    ]
    diff: dict[str, tuple] = {}
    for f in fields:
        a, b = getattr(old, f), getattr(new, f)
        if a != b:
            diff[f] = (a, b)
    if sorted(old.play_ids) != sorted(new.play_ids):
        diff["play_ids"] = (len(old.play_ids), len(new.play_ids))
    return diff
