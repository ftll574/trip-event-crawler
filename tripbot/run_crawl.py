"""批次爬蟲進入點（GitHub Actions crawl.yml / 本機手動執行）。

流程：deals 中樞頁 → 活動連結 → 活動頁解析 → 三態偵測 →
SQLite + data/events.json → LINE 推播（NEW/MODIFIED）→ 告警 ping。

用法：
  python -m tripbot.run_crawl --markets tw,hk [--publish data/events.json]
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

import httpx

from . import db as dbm
from .alerts import ntfy, ping_healthchecks
from .config import (
    BLOCKED_CIRCUIT_THRESHOLD,
    BLOCKED_COOLDOWN_S,
    DEALS_HUB_PATH,
    Settings,
)
from .discover import discover_campaign_links
from .fetch import BlockedError, CircuitBreaker, fetch
from .flex import build_carousel, chunk_events
from .foxpage import parse_event
from .line_client import LineClient
from .models import Event, now_iso, semantic_diff
from .publish import publish

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("run_crawl")

# 每輪推播的活動數上限（配額治理：好友多時靠 multicast 訂閱制，見 P2）
MAX_PUSH_PER_RUN = 12


def _page_title(html: str) -> str:
    lower = html.lower()
    if "<title>" in lower:
        s = lower.index("<title>") + 7
        e = lower.find("</title>", s)
        if e > s:
            return html[s:e].strip()
    return ""


def crawl_market(market_code: str, settings: Settings,
                 client: httpx.Client | None = None) -> tuple[list[Event], list[Event], int]:
    """回傳 (parsed_events, new_or_modified, error_count)。"""
    market = settings.resolve_market(market_code)
    if market is None:
        log.warning("未知市場 %s，略過", market_code)
        return [], [], 1

    hub_url = market.base + DEALS_HUB_PATH
    resp = fetch(hub_url, client=client)
    links = discover_campaign_links(resp.text, str(resp.url))
    log.info("[%s] deals hub 發現 %d 個活動連結", market_code, len(links))
    if not links:
        # 實測 Trip.com 會間歇回傳無 SSR 連結的殼頁（HTTP 200）。
        # 記為錯誤讓 scrape_runs/healthchecks 反映異常，而非静默成功；
        # 三態偵測會把單輪 miss 留在 missed_polls，連續兩輪才判 ENDED。
        log.warning("[%s] deals hub 異常：200 但 0 連結（len=%d）",
                    market_code, len(resp.text))
        return [], [], 1

    parsed: list[Event] = []
    errors = 0
    for cid, url in links:
        try:
            r2 = fetch(url, client=client)
            ev = parse_event(
                r2.text, market=market_code, campaign_id=cid, url=url,
                page_title=_page_title(r2.text),
            )
            if ev is None:
                errors += 1
                continue
            parsed.append(ev)
        except BlockedError:
            errors += 1
            raise  # 被擋：直接中止本市場，交由上層熔斷計數
        except Exception as exc:  # noqa: BLE001 - 單頁失敗不拖垮整輪
            log.warning("[%s] %s 解析失敗: %s", market_code, url, exc)
            errors += 1
    return parsed, [], errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--markets", default=None,
                    help="逗號分隔市場代碼；預設讀 TRIPBOT_MARKETS 或 tw")
    ap.add_argument("--publish", default=None)
    args = ap.parse_args()

    settings = Settings.from_env()
    markets = (args.markets or ",".join(settings.markets)).split(",")
    publish_path = args.publish or settings.publish_path

    all_new_modified: list[Event] = []
    total_errors = 0
    run_started = time.time()

    with dbm.session(settings.db_path) as conn:
        run_id = dbm.record_run_start(conn, ",".join(markets))
        breaker = CircuitBreaker(BLOCKED_CIRCUIT_THRESHOLD, BLOCKED_COOLDOWN_S)

        blocked_count = int(dbm.get_meta(conn, "consecutive_blocked", "0"))
        last_blocked_ts: float | None = None
        raw_ts = dbm.get_meta(conn, "last_blocked_ts", "")
        if raw_ts:
            last_blocked_ts = float(raw_ts)

        if breaker.should_skip(blocked_count, last_blocked_ts):
            msg = f"熔斷中（連續被擋 {blocked_count} 次），本輪跳過網路抓取"
            log.warning(msg)
            ntfy(settings.ntfy_topic_url, "爬蟲熔斷", msg, priority="high")
            return 0

        found_total = 0
        new_total = 0
        ended_total = 0
        for code in markets:
            try:
                parsed, _, errs = crawl_market(code, settings)
                total_errors += errs
            except BlockedError as exc:
                blocked_count = breaker.record_blocked(blocked_count)
                dbm.set_meta(conn, "consecutive_blocked", str(blocked_count))
                dbm.set_meta(conn, "last_blocked_ts", str(time.time()))
                msg = f"市場 {code} 被擋：{exc}；連續 {blocked_count} 次"
                log.error(msg)
                ntfy(settings.ntfy_topic_url, "爬蟲被擋", msg, priority="high")
                continue

            seen_keys: set[str] = set()
            for ev in parsed:
                key = ev.event_key
                seen_keys.add(key)
                old = dbm.get_event(conn, key)
                if old is None:
                    status = "new"
                    new_total += 1
                elif old.content_hash() != ev.content_hash():
                    status = "modified"
                else:
                    status = "same"
                if status in ("new", "modified"):
                    all_new_modified.append(ev)
                    diff = semantic_diff(old, ev) if old else {}
                    log.info("[%s] %s %s %s", code, status.upper(),
                             key[:12], ev.title[:40])
                    log.debug("diff=%s", diff)
                dbm.upsert_event(conn, ev, tnc_sha="")
                dbm.save_snapshot(
                    conn, key, ev.content_hash(),
                    {"title": ev.title, "start_ms": ev.start_ms,
                     "end_ms": ev.end_ms, "discount_text": ev.discount_text},
                )
            # 只比對本市場：單市場輪詢不會誤殺其他市場的活動
            ended_total += len(
                dbm.mark_missed_and_ended(conn, seen_keys, market=code))
            found_total += len(parsed)

            # 成功 → 重置熔斷計數
            if blocked_count:
                c, ts = breaker.record_success()
                dbm.set_meta(conn, "consecutive_blocked", str(c))
                if ts is None:
                    dbm.set_meta(conn, "last_blocked_ts", "")

        dbm.record_run_end(
            conn, run_id, found=found_total, new_count=new_total,
            modified=len(all_new_modified) - new_total, ended=ended_total,
            errors=total_errors,
        )

        # 發佈 JSON（Vercel 端資料源）
        count = publish(conn, publish_path, generated_at=now_iso())
        log.info("已發佈 %d 個 active 活動 → %s", count, publish_path)

        # LINE 推播 NEW/MODIFIED（有 token 才推）
        if settings.line_channel_access_token and all_new_modified:
            lc = LineClient(settings.line_channel_access_token)
            try:
                pub = [e.to_public_dict() for e in
                       all_new_modified[:MAX_PUSH_PER_RUN]]
                for chunk in chunk_events(pub):
                    card = build_carousel(chunk)
                    if card:
                        lc.broadcast([card])
                q = lc.quota_consumption()
                log.info("LINE 配額使用：%s", q)
            finally:
                lc.close()

    elapsed = time.time() - run_started
    log.info("完成：%.1fs，活動 %d，變更 %d，錯誤 %d",
             elapsed, found_total, len(all_new_modified), total_errors)
    ping_healthchecks(settings.healthchecks_url, ok=(total_errors == 0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
