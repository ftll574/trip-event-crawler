"""解析活動頁的 __foxpage_data__ JSON。

依【01】§1.3/§4 欄位模型（一手實證）：
- 整頁設定序列化在 <script id="__foxpage_data__" type="application/json"> 內。
- structures[] 節點含 name / structure.label / props。
- timer 元件：props.startTime / props.endTimeNew（epoch 毫秒）、props.endTimeZone
  （如 "GMT+08:00"）—— 排程一律以 epoch 為準，時區字串僅供顯示。
- coupon-v2 元件：props.title.text、prizeType、playIds、txtOutOfStock。
- T&C 富文本、dateTabSwitchTime 檔期輪播間隔。

Foxpage 改版時本模組可能静默漏抓 → 測試 fixtures 契約測試 + scrape_runs 驟降告警兜底。
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from .models import Event

log = logging.getLogger(__name__)

FOXPAGE_SCRIPT_RE = re.compile(
    r"<script[^>]*id=\"__foxpage_data__\"[^>]*>(.*?)</script>",
    re.DOTALL,
)

_TIMER_HINT = re.compile(r"timer|countdown|seckill", re.I)
_COUPON_HINT = re.compile(r"coupon|promo|voucher", re.I)


def extract_foxpage_json(html: str) -> dict[str, Any]:
    """從活動頁 HTML 抽出並反序列化 __foxpage_data__。找不到回傳 {}。"""
    m = FOXPAGE_SCRIPT_RE.search(html)
    if not m:
        return {}
    try:
        data = json.loads(m.group(1))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        log.warning("__foxpage_data__ JSON 解析失敗")
        return {}


def _iter_structures(data: dict[str, Any]) -> list[dict[str, Any]]:
    s = data.get("structures")
    if isinstance(s, list):
        return [x for x in s if isinstance(x, dict)]
    if isinstance(s, dict):
        return [x for x in s.values() if isinstance(x, dict)]
    return []


def _node_text(node: dict[str, Any]) -> str:
    label = ""
    structure = node.get("structure")
    if isinstance(structure, dict):
        label = str(structure.get("label", ""))
    return f"{node.get('name', '')} {label}"


def _as_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        f = float(v)
        return int(f)
    except (TypeError, ValueError):
        return None


def parse_event(html: str, *, market: str, campaign_id: str, url: str,
                page_title: str = "",
                now_ms: int | None = None) -> Event | None:
    """把活動頁 HTML 解析成結構化 Event。無 foxpage 資料時仍以頁面標題建檔。

    now_ms：可注入時鐘（測試確定性）；預設取當下時間。
    """
    data = extract_foxpage_json(html)
    ev = Event(market=market, campaign_id=campaign_id, url=url,
               title=page_title.strip())
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)

    timers: list[dict[str, Any]] = []
    coupons: list[dict[str, Any]] = []
    tnc_texts: list[str] = []
    tab_switch: int | None = None

    for node in _iter_structures(data):
        text = _node_text(node)
        raw_props = node.get("props")
        props: dict[str, Any] = raw_props if isinstance(raw_props, dict) else {}

        if _TIMER_HINT.search(text):
            timers.append(props)
            tzv = props.get("endTimeZone") or props.get("timeZone")
            if tzv and not ev.tz_label:
                ev.tz_label = str(tzv)
            ts = _as_int(props.get("dateTabSwitchTime"))
            if ts:
                tab_switch = ts if tab_switch is None else min(tab_switch, ts)

        if _COUPON_HINT.search(text):
            coupons.append(props)
            title_prop = props.get("title")
            if not ev.title or ev.title == page_title.strip():
                cand = ""
                if isinstance(title_prop, dict) and title_prop.get("text"):
                    cand = str(title_prop["text"]).strip()
                elif isinstance(title_prop, str) and title_prop.strip():
                    cand = title_prop.strip()
                if cand:
                    ev.title = cand
            if props.get("prizeType") and not ev.discount_text:
                pt = str(props["prizeType"]).strip()
                # prizeType 常是數字枚舉（如 "4"）；只收看起來像文案的值
                if pt and not pt.isdigit():
                    ev.discount_text = pt
            play_ids = props.get("playIds")
            if isinstance(play_ids, list):
                for p in play_ids:
                    if p is not None and str(p) not in ev.play_ids:
                        ev.play_ids.append(str(p))
            oos = props.get("txtOutOfStock")
            if isinstance(oos, str) and oos.strip():
                ev.stock_text = oos.strip()
                # 名額文案出現即視為售罄訊號之一，由關鍵字細判
                if re.search(r"(售完|已搶完|已領完|sold.?out|完售)", oos, re.I):
                    ev.sold_out = True

        # T&C 富文本（常見 key：content / richText / html）
        for k in ("terms", "tnc", "agreement"):
            v = props.get(k)
            if isinstance(v, str) and len(v) > len("..."):
                tnc_texts.append(v)

    if timers:
        starts = [_as_int(t.get("startTime")) for t in timers]
        ends = [
            _as_int(t.get("endTimeNew")) or _as_int(t.get("endTime"))
            for t in timers
        ]
        valid_starts = [s for s in starts if s]
        valid_ends = [e for e in ends if e]
        ev.start_ms = min(valid_starts) if valid_starts else None
        ev.end_ms = max(valid_ends) if valid_ends else None

        # 常青票券頁的 timer.startTime 以「頁面渲染時間」為錨點（實測每輪漂移
        # ≈ 爬行間隔，解析時僅過去數秒），會讓 content_hash 每輪不同 →
        # MODIFIED 推播轟炸。凡不晚於當下的 start 一律正規化為 None：
        # 已開賣無提醒價值；未來的真實開賣時間不受影響。
        if ev.start_ms is not None and ev.start_ms <= now_ms:
            log.debug("start_ms %s 為過去時間／滾動錨點，正規化為 None",
                      ev.start_ms)
            ev.start_ms = None

    if tnc_texts:
        joined = "\n".join(tnc_texts)
        ev.scope_text = joined[:2000]

    if tab_switch:
        ev.sale_note = ev.sale_note or f"tab 輪播間隔 {tab_switch}ms"

    # 完全沒有可用資訊且無標題 → 視為解析失敗，不建檔（交由 run 層計 errors）
    if data and not ev.title and ev.start_ms is None and ev.end_ms is None:
        return None
    return ev
