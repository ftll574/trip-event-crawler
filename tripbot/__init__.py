"""Trip.com 促銷活動監控 × LINE 推播（MVP）。

模組地圖（對應 docs/implementation-plan.md 的五層架構）：
- fetch.py     : L2 禮貌抓取（誠實 UA、timeout、tenacity 重試、熔斷）
- discover.py  : L1 從 deals 中樞頁發現活動連結
- foxpage.py   : L2 解析活動頁 __foxpage_data__ JSON
- detect.py    : L2 三態變更偵測（NEW / MODIFIED / ENDED）
- db.py        : L3 SQLite(WAL) 儲存
- publish.py   : L3 匯出 data/events.json 供 Vercel 端使用
- flex.py      : L4 Flex Message 卡片組裝
- line_client.py: L4 Messaging API 客戶端（broadcast/multicast/reply/quota）
- linesec.py   : L4 webhook 簽章驗證
- subs.py      : 提醒訂閱的加密合併工具（repo 內加密儲存的寫入端）
- alerts.py    : 營運告警（healthchecks.io 死人開關 + ntfy.sh）
- run_crawl.py : 批次爬蟲進入點（GitHub Actions 用）
"""

__version__ = "0.1.0"
