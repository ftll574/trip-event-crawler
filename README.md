# TripBot — Trip.com 各國節日折扣活動追蹤 × LINE 搶購提醒

監控各國 Trip.com 的節日／快閃折扣活動活動頁，偵測新活動與變更，自動推播 Flex 卡片到
LINE 官方帳號，並提供「開賣前 15 分鐘」提醒訂閱與搶購日曆（.ics）。

研究依據見 [`research/`](research/)：【01】活動來源實測、【02】爬蟲架構、【03】LINE 整合；
完整設計見 [`docs/implementation-plan.md`](docs/implementation-plan.md)。

## 架構

```
GitHub Actions (cron 17,47 * * * *)
  └─ tripbot.run_crawl：抓 /sale/deals/ 中樞 → discover 活動頁
     → foxpage 解析 __foxpage_data__ → 三態變更偵測
     ├─ SQLite(data/events.sqlite, WAL) —— 工作資料庫（只在 Actions 側存在）
     ├─ commit data/events.json ────── 發佈層（觸發 Vercel 自動重新部署）
     └─ NEW/MODIFIED → LINE broadcast Flex carousel

Vercel (Python serverless functions)
  ├─ POST /api/webhook ── LINE webhook：驗章(x-line-signature) → reply 歡迎卡
  │                        postback「開賣前提醒我」→ 加密訂閱 blob
  │                        → repository_dispatch(sub-update) 回 GitHub 落盤
  ├─ GET  /api/cron_remind ── 每分鐘(Vercel Pro cron)：到期訂閱 multicast 提醒卡
  │                            （X-Line-Retry-Key 冪等防重發）
  └─ GET  /api/ics?market=tw ── RFC5545 搶購日曆（可訂閱到手機行事曆）

GitHub Actions (repository_dispatch sub-update)
  └─ workflows/subs.yml：解密 → 合併/標記 sent → 重加密 commit data/subscriptions.enc
```

**為什麼 repo 是發佈層？** 公開 repo 免後端資料庫：每輪爬蟲 commit `data/events.json`，
Vercel 偵測 push 自動重新部署，三個 function 直接讀 repo 內檔案。零維運成本。

## 本機開發

需求：Python 3.12+。系統套件安裝：

```bash
pip install -r requirements.txt   # httpx beautifulsoup4 lxml tenacity cryptography tzdata
pip install pytest ruff mypy      # 開發工具

python -m pytest                  # 22 tests
ruff check . && mypy tripbot     # CI 同款檢查
python -m tripbot.run_crawl --markets tw --publish   # 手動爬一輪（會寫 data/）
```

## 環境變數

| 變數 | 必填 | 用途 |
|---|---|---|
| `TRIPBOT_MARKETS` | ✗ | 市場清單（逗號分隔），預設 `tw,hk,jp,kr,sg,th,us`；單跑 `tw` |
| `LINE_CHANNEL_ACCESS_TOKEN` | ✓ | LINE Messaging API channel access token |
| `LINE_CHANNEL_SECRET` | ✓* | webhook 驗章用（僅 Vercel 需要） |
| `SUBS_FERNET_KEY` | ✓ | 訂閱加密金鑰（任意字串，SHA256 衍生；Vercel 與 GitHub **必須一致**） |
| `GH_TOKEN` | ✓* | GitHub PAT（fine-grained，本 repo Contents: Read and write）；Vercel dispatch 用 |
| `GH_REPO` | ✓* | `owner/repo`；Vercel dispatch 用 |
| `CRON_SECRET` | ✓* | `/api/cron_remind` Bearer 驗證（Vercel cron 自動帶入） |
| `HEALTHCHECKS_URL` | ✗ | healthchecks.io 死人開關（爬蟲成功 ping / 失敗 ping /fail） |
| `NTFY_TOPIC_URL` | ✗ | ntfy.sh 營運通知（403 熔斷、錯誤告警） |

\* 標星號者只部署環境需要（Vercel 或 GitHub Secrets），本機測試可省。
範例見 [`.env.example`](.env.example)；金鑰產生：`python -c "import secrets; print(secrets.token_urlsafe(32))"`。

## 部署（約 30 分鐘）

1. **GitHub**：建立 **公開** repo（Q1 決策），push 本專案。Settings → Secrets 加入
   `LINE_CHANNEL_ACCESS_TOKEN`、`SUBS_FERNET_KEY`、（選用）`HEALTHCHECKS_URL`、`NTFY_TOPIC_URL`。
2. **LINE Developers Console**：建立 Messaging API channel → 記下 channel secret 與
   long-lived access token；發行 token 後加官方帳號好友。
3. **Vercel**：Import Git Repository（同一 repo）。Environment Variables 加入上表所有 ✓
   變數（含 `LINE_CHANNEL_SECRET`、`SUBS_FERNET_KEY`、`GH_TOKEN`、`GH_REPO`、`CRON_SECRET`）。
   Deploy 後於 LINE console 設 Webhook URL = `https://<app>.vercel.app/api/webhook`，啟用
   「Use webhook」，並關閉「Automatically reply text messages」（否則吃掉 reply 免費額度）。
4. **驗證**：
   - GitHub Actions → crawl → Run workflow（markets=`tw`）→ 綠燈且 `data/events.json` 有活動。
   - LINE 加好友傳任意訊息 → 收到歡迎 carousel；點卡片「開賣前提醒我」→ 到期前 15 分鐘收到提醒。
   - 手機行事曆訂閱 `https://<app>.vercel.app/api/ics?market=tw`。
5. **保活**：`keepalive.yml` 每週一空 commit，避免 60 天無活動被 GitHub 停用排程（【02】§4）。

## 安全設計

- 公開 repo **不露任何 LINE userId**：訂閱以 Fernet(`SUBS_FERNET_KEY`) 加密成
  `data/subscriptions.enc`；明文只短暫存在 Vercel function 與 Actions runner 記憶體。
- webhook 必驗 `x-line-signature`（HMAC-SHA256+base64, `hmac.compare_digest`）。
- `/api/cron_remind` 驗 Bearer `CRON_SECRET`；爬蟲對目標站誠實標示 UA `trip-event-bot/0.1`，
  只抓 robots.txt 允許的聯盟參數活動頁，絕不碰 `/restapi/soa2/*`（【01】§robots）。

## 營運韌性（【02】§7）

- **熔斷**：連續 5 次 401/403/429 → 冷卻 1 小時不打目標站，ntfy 告警。
- **三態偵測**：`event_key`(sha256 market+cid) + `content_hash` 語意比對；連續 2 輪沒看到
  才判 ENDED（防單輪抖動誤殺）。
- **死人開關**：healthchecks.io 未收到 ping 即寄信告警。
- **冪等推播**：X-Line-Retry-Key = uuid5(event_key|remind_at)，cron 重疊不重複推。

## 與計畫書的偏離紀錄

| 偏離 | 理由 |
|---|---|
| 不用 `line-bot-sdk-python`，自寫 thin httpx client（`tripbot/line_client.py`） | 實際只用 5 個 endpoint（broadcast/multicast/reply/push/quota）；serverless 冷啟動體積敏感；SDK 抽象層反而妨礙精確控制 X-Line-Retry-Key 冪等語義。【03】§2.3 |
| 提醒不做 Google Calendar API | OAuth 審查成本高；改用靜態 `.ics` endpoint（`/api/ics`）＋ LIFF-less 純 Flex 互動即可覆蓋「搶購日曆」需求（【03】§4 決策） |
| Vercel Python function 以檔案路徑載入 | `api/*.py` 開頭手動 `sys.path.insert` repo 根目錄，不可用相對 import（原計畫未預期，實作時發現並調整） |
| `content_hash` 刻意不含 `start_ms` | 實測部分常青票券頁的 timer.startTime 是「渲染錨點」（每次請求重算，甚至＝渲染時間＋固定偏移），纳入會每輪誤報 MODIFIED 推播轟炸。開賣時間照常發佈與供提醒計算；foxpage 另把已過去的 start 正規化為 None |
| deals hub 抓到 200 但 0 連結時記為 errors | 實測 Trip.com 會間歇回傳無 SSR 連結的殼頁；計入錯誤讓 scrape_runs/healthchecks 如實反映，三態偵測（連續 2 輪才 ENDED）兜底單輪 miss |

## 已知限制 / P2 待辦

- foxpage JSON 結構改版可能静默漏抓 → 以 scrape_runs 筆數驟降 + fixtures 契約測試兜底。
- 「每週一/三/五更新名額」型票券活動的真實搶購節奏目前只在 stock_text 文案中，
  P2 可解析 cadence 文字推算下次開賣時間，讓提醒涵蓋無 timer 的週更活動。
- 跨市場同 cid 不同內容已由 event_key 含 market 解決；但多市場輪詢延遲隨市場數線性增加，
  P2 可拆 per-market matrix job。
- 日曆 `.ics` 為全量快照，手機端需手動重新整理（無 push 更新）。
- 真實的開賣時間異動（reschedule）不觸發 MODIFIED 推播（見上表 start_ms 偏離）；
  新活動出現與下架仍正常推播／標記。
