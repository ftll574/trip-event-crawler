"""L1 活動發現：從 deals 中樞頁 HTML 抽出活動頁連結。

URL 模式（依【01】§1.2）：/{market}.trip.com/sale/w/{campaignId}/{slug}.html
campaignId：純數字（舊式）或 16 碼隨機字元（新式）都要支援。
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

# campaignId 至少 4 碼英數；slug 允許中英文/連字號，非貪婪直到 .html
_CAMPAIGN_RE = re.compile(
    r"/sale/w/(?P<cid>[0-9A-Za-z]{4,})/(?P<slug>[^\"'?\#<>]+?)\.html"
)


def discover_campaign_links(html: str, base_url: str) -> list[tuple[str, str]]:
    """回傳 [(campaignId, absolute_url)]，去重且保持出現順序。"""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for m in _CAMPAIGN_RE.finditer(html):
        cid = m.group("cid")
        abs_url = urljoin(base_url, m.group(0))
        if cid not in seen:
            seen.add(cid)
            out.append((cid, abs_url))
    return out
