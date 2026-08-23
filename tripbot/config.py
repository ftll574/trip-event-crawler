"""環境變數驅動的設定（無第三方依賴）。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name, "")
    if not raw.strip():
        return list(default)
    return [x.strip() for x in raw.split(",") if x.strip()]


@dataclass(frozen=True)
class Market:
    """單一市場設定。依【01】§1.1/§5.2：locale/currency 影響 URL 參數，tz 用於顯示渲染。"""

    code: str          # tw / jp / hk ...
    base: str          # https://tw.trip.com
    tz: str            # IANA timezone（顯示用；解析一律以 epoch 為準）
    locale: str = ""
    currency: str = ""


DEFAULT_MARKETS: dict[str, Market] = {
    m.code: m
    for m in [
        Market("tw", "https://tw.trip.com", "Asia/Taipei", "zh-TW", "TWD"),
        Market("hk", "https://hk.trip.com", "Asia/Hong_Kong", "zh-HK", "HKD"),
        Market("jp", "https://jp.trip.com", "Asia/Tokyo", "ja-JP", "JPY"),
        Market("kr", "https://kr.trip.com", "Asia/Seoul", "ko-KR", "KRW"),
        Market("sg", "https://sg.trip.com", "Asia/Singapore", "en-SG", "SGD"),
        Market("th", "https://th.trip.com", "Asia/Bangkok", "th-TH", "THB"),
        Market("us", "https://us.trip.com", "America/Los_Angeles", "en-US", "USD"),
    ]
}

# 禮貌抓取參數（依計畫 §2-5：平時 15–30 分＋jitter；同 host 最少間隔）
POLL_MIN_INTERVAL_S = 900       # 同一 host 兩次請求最小間隔（15 分，用於單機長駐模式）
HTTP_TIMEOUT_S = 20.0
MAX_RETRIES = 3
BLOCKED_CIRCUIT_THRESHOLD = 5   # 連續被擋 N 次 → 熔斷（依【02】§7）
BLOCKED_COOLDOWN_S = 3600       # 熔斷冷卻 1 小時

USER_AGENT = (
    "Mozilla/5.0 (compatible; trip-event-bot/0.1; +personal deal monitor; "
    "contact: see repo README)"
)


@dataclass(frozen=True)
class Settings:
    markets: list[str] = field(default_factory=lambda: ["tw"])
    db_path: str = "data/events.sqlite"
    publish_path: str = "data/events.json"

    # LINE Messaging API
    line_channel_access_token: str = ""
    line_channel_secret: str = ""

    # 提醒訂閱加密（webhook 加密 / workflow 解密共用同一把 key）
    subs_fernet_key: str = ""

    # GitHub repository_dispatch（Vercel webhook → 觸發 workflow 寫訂閱）
    gh_token: str = ""
    gh_repo: str = ""           # 例：owner/trip-event-crawler

    # 營運告警
    healthchecks_url: str = ""  # 成功結束時 ping
    ntfy_topic_url: str = ""    # 例：https://ntfy.sh/my-trip-deals-ops

    # Vercel cron 保護
    cron_secret: str = ""

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            markets=_env_list("TRIPBOT_MARKETS", ["tw"]),
            db_path=os.environ.get("TRIPBOT_DB_PATH", "data/events.sqlite"),
            publish_path=os.environ.get("TRIPBOT_PUBLISH_PATH", "data/events.json"),
            line_channel_access_token=os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", ""),
            line_channel_secret=os.environ.get("LINE_CHANNEL_SECRET", ""),
            subs_fernet_key=os.environ.get("SUBS_FERNET_KEY", ""),
            gh_token=os.environ.get("GH_TOKEN", ""),
            gh_repo=os.environ.get("GH_REPO", ""),
            healthchecks_url=os.environ.get("HEALTHCHECKS_URL", ""),
            ntfy_topic_url=os.environ.get("NTFY_TOPIC_URL", ""),
            cron_secret=os.environ.get("CRON_SECRET", ""),
        )

    def resolve_market(self, code: str) -> Market | None:
        return DEFAULT_MARKETS.get(code.lower())


def campaign_page_url(market: Market, campaign_id: str, slug: str) -> str:
    """活動頁 URL 模式（依【01】§1.2：/sale/w/{campaignId}/{slug}.html）。"""
    return f"{market.base}/sale/w/{campaign_id}/{slug}.html"


DEALS_HUB_PATH = "/sale/deals/"
