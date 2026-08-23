# Trip.com 促銷活動監控 × LINE 推播 — 可行實作計畫

> 任務：t4「彙整三份研究報告，撰寫可行實作計畫」｜撰寫：planner（architect）
>
> 依據的三份研究報告（本計畫所有選型均可回溯至其中一條已驗證結論）：
> - 《01 Trip.com 各國促銷活動資料來源研究報告》— `research/01-tripcom-promo-sources.md`（下稱【01】，promo-scout／t1）
> - 《02 爬蟲技術棧、排程與反爬策略研究》— `research/02-crawling-stack.md`（下稱【02】，crawl-engineer／t2）
> - 《03 LINE Messaging API 推播與提醒方案研究》— `research/03-line-integration.md`（下稱【03】，line-integrator／t3）
>
> 引用格式：（【NN】§節）。三份報告的核心結論均為 HTTP 實抓／官方文件直抓的一手證據，本計畫不引入未經驗證的假設。

---

## 0. 一句話定位

定時巡檢 Trip.com 各市場的促銷活動頁，解析出結構化欄位（活動名稱、折扣形式、開賣／結束時間與時區、適用範圍、名額狀態），偵測「新活動上線」與「內容異動」，透過 LINE 官方帳號推送 Flex Message 卡片，並在開賣時刻前主動提醒；另提供 .ics 下載與（後期）LIFF 搶購日曆頁讓用戶自行管理提醒。

---

## 1. 系統架構總覽（文字版架構圖）

```
┌────────────────────────────────────────────────────────────────────┐
│ L1 資料來源層                                                        │
│  • {market}.trip.com/sale/deals/         優惠中樞頁（SSR，17 市場存活）│
│  • {market}.trip.com/sale/w/{cid}/{slug}.html  活動頁（SSR）          │
│      └ 內含 <script id="__foxpage_data__"> JSON＝解析主目標          │
│  • 補充訊號：Google News RSS（✅可用）／官方 FB・IG 公開貼文／ShopBack │
│  • 官方管道（並行申請）：Trip.com Affiliate 後台 Promotion Center     │
└──────────────┬─────────────────────────────────────────────────────┘
               │ ① HTTP GET（低頻禮貌抓取：≥15 分間隔＋jitter、誠實 UA）
               │ ② robots 合規：sale/promotion 未被 Disallow；
               │    絕不碰 /restapi/soa2/* 等內部 API
┌──────────────▼─────────────────────────────────────────────────────┐
│ L2 爬蟲／排程層（GitHub Actions scheduled workflow）                  │
│  cron 「17,47 * * * *」（避開整點）→ fetcher(httpx)                  │
│   → parser(BS4 + json：抽 timer/coupon/T&C 節點)                    │
│   → 正規化 → event_key/content_hash → 三態判定                       │
│      NEW ／ MODIFIED（欄位級 diff）／ ENDED(missed_polls≥2–3)        │
│  tenacity 指數退避重試 ・ 熔斷（連續被擋→冷卻1小時）                   │
│  healthchecks.io 死人開關 ・ ntfy.sh 營運告警                        │
└──────────────┬─────────────────────────────────────────────────────┘
               │
┌──────────────▼─────────────────────────────────────────────────────┐
│ L3 資料庫層（SQLite + WAL，單機零維運）                               │
│  events（活動主檔，event_key UNIQUE）                                │
│  snapshots（每次抓取快照＋content_hash，保留近 K 版供 diff）          │
│  scrape_runs（每輪執行稽核）                                          │
│  subscriptions（userId × 活動 × 提醒時刻）※Phase 2                   │
│  markets（市場設定：locale/curr/IANA 時區/固定快閃節奏）※Phase 2      │
└──────┬──────────────────────────────────┬──────────────────────────┘
       │ ③ NEW/MODIFIED 事件               │ ④ 開賣時刻掃描（T-15min 等）
┌──────▼──────────────────────────┐  ┌────▼─────────────────────────┐
│ L4 LINE 推播層                    │  │ L5 日曆提醒層                  │
│  （官方帳號 OA + Messaging API）   │  │  • 到點前 multicast 提醒      │
│  • Webhook（常駐 HTTPS endpoint） │  │    （吃配額：1則/人/次）       │
│    ├ follow：存 userId＋Flex 歡迎 │  │  • .ics 下載/webcal 連結      │
│    └ postback：「開賣前提醒我」訂閱 │  │    （不吃配額）               │
│  • 新活動/異動 → Flex carousel    │  │  • P3：rich menu→LIFF 搶購    │
│    （≤12 bubbles、altText 必寫）   │  │    日曆頁（瀏覽不吃配額）      │
│  • multicast/broadcast（計費）     │  │  ✕ 不做 Google Calendar API  │
│    Reply API 用於互動（免費）      │  │    （OAuth 審查成本過高）      │
└──────────────────────────────────┘  └──────────────────────────────┘
```

### 1.1 各層職責與依據

| 層 | 職責 | 關鍵依據 |
|---|---|---|
| **L1 資料來源** | 發現活動（deals hub＋首頁輪播兩個固定入口）→ 取得 campaignId 清單 → 逐頁抓活動頁 | 【01】§1.1–1.2：中樞頁與活動頁全數 SSR 實測 200；sitemap.xml 不存在（404），必須靠巡檢中樞頁發現新活動 |
| **L2 爬蟲/排程** | 抓取、解析 `__foxpage_data__`、變更偵測、失敗處理 | 【01】§1.3：整頁設定序列化在單一 script tag，timer 元件含 epoch 毫秒＋明確時區字串——正是排程需要的欄位；【02】§4–§5、§7 |
| **L3 資料庫** | 活動主檔、快照、執行稽核、訂閱 | 【02】§6：SQLite 足夠（WAL），Schema 已提案 |
| **L4 LINE 推播** | 收 friend/postback、主動推卡片 | 【03】§0、§2、§6：webhook 只處理 follow/postback，其餘全部排程主動推送 |
| **L5 日曆提醒** | 開賣前提醒＋用戶自管日曆 | 【03】§4：組合 (a)push＋(c).ics＋P3(b)LIFF；(d)Google Calendar API 不做 |

### 1.2 兩個關鍵架構決策

1. **全鏈路「純 HTTP、無瀏覽器」起步**：【01】證明目標資料全在 SSR HTML 的 `__foxpage_data__` 內，【02】§1.2 的判定法則（view-source 有資料就不上瀏覽器）成立 → MVP 不引入 Playwright，省掉最重的依賴與流量；僅當頁面轉為 SPA 或遇到 JS challenge 時局部啟用（Phase 3 後備）。
2. **批次與事件分離**：爬蟲是 GitHub Actions 上的無狀態批次 job（不需伺服器）；但 LINE webhook 需要一個**常駐的公開 HTTPS endpoint**（禁自簽憑證，【03】§1.3）。MVP 可以先把 webhook 架在免費小型 PaaS（Fly.io/Railway/Render 之一）或暫緩互動功能（只做單向廣播），此取捨列為開放問題 Q2。

---

## 2. 技術選型與理由

| # | 層面 | 選擇 | 理由（可回溯的研究結論） |
|---|---|---|---|
| 1 | **語言** | **Python 3.12** | 【02】§1.1：爬蟲＋資料清洗＋排程生態最完整（httpx/BS4/Scrapy/APScheduler/tenacity）；且【03】§7 line-bot-sdk-python 現役維護（v3 支援 async）。備註：【02】§1.1 同時以一手取證證明「Node v24 內建 fetch 可直接打 Trip.com 主站」，若團隊主 JS 可平移到 Node（line-bot-sdk-nodejs 亦現役），功能等價 |
| 2 | **爬蟲方式** | **httpx + BeautifulSoup4(lxml)，純 HTTP**；Playwright 僅作後備 | 【01】§1.1–1.3：活動頁/中樞頁皆 SSR、解析目標是 `__foxpage_data__` script tag（活動頁**沒有** JSON-LD）；【02】§1.2–1.3：判定法則＋主站 SSR 實證（1.9MB HTML 含完整可見文字） |
| 3 | **解析目標** | `__foxpage_data__` 的 `structures[]` 節點 props：①timer 元件（`startTime`/`endTimeNew` epoch 毫秒＋`endTimeZone` 如 `"GMT+08:00"`）②coupon-v2 元件（`@ctrip/cloud-component-sales4-coupon-b`：`playIds`、`title.text`、`txtOutOfStock` 名額文案）③T&C 富文本 ④`dateTabSwitchTime` 檔期輪播 | 【01】§1.3＋§4 欄位模型（實證樣本：okinawapromotion 315 節點、member-day timer） |
| 4 | **排程** | **GitHub Actions scheduled workflow**，cron `17,47 * * * *`（避開整點） | 【02】§4：public repo 標準 runner 免費＝免主機首選；官方文件明示 schedule 在高負載（整點）會延遲，故避開 :00；只能在 default branch 生效；public repo **60 天無活動自動停用**→ 需 keepalive commit |
| 5 | **輪詢節奏** | 平時 15–30 分/次；已知開賣時段（如週一 12:00 前）收緊至 ~5 分；全程 ±1–2 分鐘 jitter；長期不低於 3–5 分 | 【02】§4：禮貌抓取＋避開行為偵測 |
| 6 | **儲存** | **SQLite + WAL**（events / snapshots / scrape_runs 三表起步） | 【02】§6：單寫入者、低寫入量、零維運；Postgres 僅在多寫入者/Web 化需求出現後升級 |
| 7 | **變更偵測/去重** | 正規化→hash→三態判定：`event_key = sha256(標題+地區+起訖)`（跨 locale 以 URL 內 campaignId 為優先）；`content_hash` 偵測修改並存欄位級 diff；本次缺席→`missed_polls += 1`，**連續 2–3 次**才標 ENDED；每事件保留近 K 版快照 | 【02】§5（防單次渲染失敗誤報 ENDED） |
| 8 | **重試/熔斷** | tenacity 指數退避＋jitter（3 次，30s→10min 上限）、一律設 timeout；403/challenge 頁視為「被擋」直接告警不做重試風暴；連續 N 次被擋→冷卻 1 小時＋告警一次 | 【02】§7 |
| 9 | **死人開關/告警** | 每次成功 run ping healthchecks.io（逾時未收到即告警）；ntfy.sh 推送 NEW/MODIFIED/ENDED 營運通知 | 【02】§7（爬蟲靜默掛掉也能被發現） |
| 10 | **LINE 整合** | 官方帳號（OA）＋ Messaging API。Webhook 只接 `follow`（存 userId＋回 Flex 活動清單歡迎訊息）與 `postback`（「提醒我」訂閱）；其餘全部排程主動推送：新活動用 broadcast、精準提醒用 multicast（Max 500 IDs/req、`X-Line-Retry-Key` UUID 冪等重試）；互動回覆一律 Reply API（免費不吃配額）；深夜推送帶 `notificationDisabled:true`；每輪查 `GET /v2/bot/message/quota` 記錄用量 | 【03】§0、§2.1–2.3、§6：LINE Notify 已於 2025-03-31 終止，「通知型訊息」禁止行銷內容→唯一正解是一般 Messaging API |
| 11 | **LINE SDK** | line-bot-sdk-python v3 | 【03】§7：現役維護（最近 push 2026-08-21，Apache-2.0，async 支援） |
| 12 | **Token 管理** | v2.1 user-specified expiration token（自訂最長 30 天，JWT 自助簽發＋IP allowlist），排程在到期前自動換發 | 【03】§1.2：四類型計數獨立、有效期內重複使用勿頻繁換發 |
| 13 | **推播卡片** | Flex Message carousel（上限 **12 bubbles**）；`altText` 必寫一行吸睛文案；折扣 % 用 xxl 大字＋高對比色塊；倒數為純文字由後端排程更新（或引導 LIFF 看 JS 倒數）；footer `uri` action 直開活動頁；先用 Flex Message Simulator 調版再接 SDK；hero 圖 ≤1MB、`aspectRatio:"2:1"+cover` | 【03】§3 |
| 14 | **日曆方案** | **(a) 到點前 push（主力）＋ (c) 活動卡附 .ics/webcal 連結（補充）＋ Phase 3 加 (b) rich menu 第一格→LIFF 搶購日曆頁（常駐瀏常駐瀏覽入口，瀏覽不吃配額）；(d) Google Calendar API 代管不做** | 【03】§4：(d) 需 Google OAuth consent 敏感範圍審查＋隱私疑慮＋維運最高，不值得；(a) 觸及率最高；(c)/(b) 不吃 LINE 配額 |
| 15 | **合規邊界** | 只抓 robots 允許的公開頁（tw robots：`promotion`/`sale` 未被 Disallow，聯盟參數活動頁明確 Allow；`/restapi/soa2/*` 等內部 API 禁碰）；ToS 無明文禁爬條款，個人低頻不轉售＝安全側；**推播只送摘要＋原頁連結，不整批轉載內容** | 【01】§1.5＋§2.3、【02】§3.1–3.2 |
| 16 | **官方管道並行** | 寄信 affiliation@trip.com 申請 Trip.com Affiliate（3–5 工作天），啟用後以後台 Promotion Center（campaignName/promoId/start/end/status）作為官方授權補充源；同步評估 developers.trip.com B2B | 【01】§2＋§6.3、【02】§1.4 |

---

## 3. 分階段路線圖

> 人日＝1 人 1 個工作天。日曆時間含外部等待（審核、審批）。每階段結尾有明確驗收標準。

### Phase 0 — 環境準備與 LINE Bot 申請（實作 1–2 人日＋外部等待 3–7 天）

| 工作項 | 內容 | 依據 |
|---|---|---|
| P0-1 版控與專案骨架 | 建 GitHub repo（公開/私有待 Q1 決策）、Python 3.12 + uv/poetry、目錄骨架（`crawler/`、`linebot/`、`db/`、`.github/workflows/`）、ruff+mypy+pytest 基線 | 【02】§8 |
| P0-2 LINE 官方帳號與 Messaging API | 註冊 LINE Business ID → 建立 OA（免費）→ OA Manager 啟用 Messaging API（**2024-09-04 新制：不能直接在 Developers Console 建 channel**；Provider 一經選定不可更改）→ Developers Console 設定 webhook URL/Verify/Use webhook 開關；greeting 與 auto-reply 改 Disabled（改由程式攔 follow event） | 【03】§1.1、§1.3、§6.1 |
| P0-3 憑證管理 | 簽發 v2.1 token（30 天）＋Channel secret 存入 GitHub Actions secrets 與 webhook host 環境變數；Console 設 Security settings/IP allowlist | 【03】§1.2 |
| P0-4 聯盟帳號申請（並行） | 寄信 affiliation@trip.com（回覆 3–5 工作天），通過後取得 Promotion Center 存取 | 【01】§2.3 |
| P0-5 營運監控帳號 | healthchecks.io check 建立、ntfy.sh topic 建立（可自架） | 【02】§7 |
| P0-6 CI 冒煙測試 | 一支 workflow 手動觸發：fetch tw.trip.com/sale/deals/ 回 200＋印頁面標題，驗證 runner 出網與解析環境 OK | 【02】§1.3 一手證據 |

**驗收**：手機加好友成功、Console webhook Verify 綠燈、CI 冒煙 job 成功、secrets 就位。

### Phase 1 — MVP：台灣單市場（爬取＋偵測＋Flex 推播）（6–9 人日，日曆約 1.5–2 週）

| 工作項 | 內容 | 依據 |
|---|---|---|
| P1-1 中樞頁爬蟲 | 抓 `https://tw.trip.com/sale/deals/`＋首頁輪播，regex 抽出 `/sale/w/{campaignId}/{slug}.html` 連結（campaignId：純數字舊式／16 碼隨機新式都要支援）→ 得當前活動清單 | 【01】§1.1–1.2 |
| P1-2 活動頁解析器 | 對每個 campaignId 抓活動頁 → `json.loads(__foxpage_data__)` → 走訪 `structures[]`，抽取 §4 欄位模型：title/slug、折扣形式（prizeType）、`startTime/endTimeNew`（epoch 毫秒）＋`endTimeZone`、開賣時刻文案、適用範圍、`playIds`、`txtOutOfStock`、T&C | 【01】§1.3、§4 |
| P1-3 資料庫 | 建立 SQLite（WAL）：`events`/`snapshots`/`scrape_runs`（沿用【02】§6 schema）；寫入器單一、ISO8601 儲存 | 【02】§6 |
| P1-4 變更偵測 | `event_key=sha256(title+region+起訖)`、`content_hash` 全欄位雜湊、三態判定＋`missed_polls`（2–3 次才 ENDED）；快照存近 K 版 | 【02】§5 |
| P1-5 排程 workflow | `.github/workflows/crawl.yml`：cron `17,47 * * * *`、jitter sleep ±1–2 分、同 host 請求間隔 ≥15 分、tenacity 重試、403/challenge→告警不重試、run 結束 ping healthchecks.io、每輪寫 `scrape_runs`；repo 定期 commit 防 60 天停用 | 【02】§4、§7 |
| P1-6 Flex 卡片模板 | 用 Flex Message Simulator 調出活動卡 bubble：hero 圖、標題＋xxl 折扣色塊、「⏰倒數 N 天」「開賣 MM-DD HH:mm（時區）」、footer「開活動頁(uri)＋開賣前提醒我(postback，先留桩)」；carousel 上限 12 張、超過拆多則（一次 push ≤5 message objects）；altText 必寫 | 【03】§3 |
| P1-7 推播服務 | NEW/MODIFIED 事件 → 組 Flex → broadcast 給全部好友（初期好友少）；`notificationDisabled` 夜間靜音；每輪呼叫 quota/consumption API 記錄用量到 log；推播內容＝摘要＋連結，不轉載全文 | 【03】§2、【02】§3.2 |
| P1-8 Webhook 最小版 | follow event：驗 `x-line-signature`(HMAC-SHA256)→快速回 200→背景存 userId→Reply API 送 Flex 歡迎清單；其餘事件忽略。（host 方案依 Q2；若暫不架 host，P1 可先只做單向廣播，postback 訂閱延到 P2） | 【03】§6.1 |
| P1-9 營運告警 | ntfy.sh 串接 NEW/MODIFIED/ENDED/blocked 通知（先推給開發者自己） | 【02】§7 |

**驗收**：連續 7 天排程成功率 ≥95%；新增活動能在 30 分鐘內推到 LINE；誤報 ENDED＝0；healthchecks.io 無逾時告警。

### Phase 2 — 多國市場＋搶購日曆（10–14 人日，日曆約 2–3 週）

| 工作項 | 內容 | 依據 |
|---|---|---|
| P2-1 市場配置表 | `markets` 表：tw/hk/jp/kr/th/sg/us 起步（17 市場清單已有實測存活資料）；欄位＝locale、curr、IANA 時區、固定快閃節奏（如 TW 週一 12:00、TH 週二正午、US 週五 11AM PT、JP 每月 25 日、會員日多綁每月 27 日） | 【01】§1.1、§1.4、§5.2 |
| P2-2 多市場爬蟲 | 迴圈各市場 deals hub → 活動頁；同一全球活動「同 ID 不同內容」以 `(campaignId, market)` 為複合身分，避免跨市場互相覆蓋 | 【01】§1.2、§5.2 |
| P2-3 開賣時段感知排程 | 平時 15–30 分；進入該市場已知開賣時段前 60 分收緊至 ~5 分＋jitter；不同市場錯峰排程 | 【02】§4、【01】§1.4 |
| P2-4 時區正規化 | 儲存：epoch 毫秒（絕對瞬間）＋原始時區字串＋ISO8601(with offset)；顯示：以市場 IANA 時區渲染（US 用 America/Los_Angeles 處理 DST；**不得**假設 GMT+8；TH 佛曆年份只影響文案顯示不影響解析） | 【01】§1.3、§5.2-5 |
| P2-5 訂閱與提醒排程器 | postback「開賣前提醒我」→ `subscriptions(userId, event_key, remind_at)`；排程器每分鐘掃描到期訂閱 → multicast（≤500 IDs/req、X-Line-Retry-Key 冪等）送提醒卡（附 uri 按鈕）；提醒時點預設 T-15min（可調，Q4）；夜間 `notificationDisabled` | 【03】§3.3、§2.3 |
| P2-6 .ics 服務 | 產生活動 .ics（webcal:// 或 https 下載連結）掛在卡片 footer「加到行事曆」；活動異動時重新生成（UID 固定讓日曆端可更新） | 【03】§4(c) |
| P2-7 多市場推播策略 | 只對「標記想收該市場通知」的 userId 做 multicast（比全體廣播省配額）；大檔活動（雙11/旅展）才 broadcast；每則推播前查剩餘配額，不足→降級只推訂閱者＋告警 | 【03】§2.4 |
| P2-8 配額看板 | 每日記錄 `consumption` 到 SQLite，月內用量 >80% 時 ntfy 告警 | 【03】§2.1 |

**驗收**：≥3 市場穩定爬取；開賣前提醒在 T-15min ±2 分送達；.ics 匯入手機日曆可正常響鈴；月配額不超過 200 則（輕用量）。

### Phase 3 — 優化（滾動進行，每項 2–5 人日；建議順序如下）

| 優先 | 工作項 | 內容 | 依據 |
|---|---|---|---|
| 1 | **去重強化** | 跨市場同活動分組顯示（同 campaignId 折疊成一張卡＋市場 tag）；標題模糊合併（相似度＋日期重疊）防同名異 ID 重複推播 | 【02】§5、【01】§5.2 |
| 2 | **失敗告警強化** | 熔斷事件（連續被擋→冷卻 1 小時）升級為立即 ntfy＋healthchecks 双通道；每週摘要 broadcast（本週新活動總覽，1 則搞定取代多次推播） | 【02】§7、【03】§2.4 |
| 3 | **LIFF 搶購日曆頁** | rich menu（2500×1686px、第一格「📅搶購日曆」）→ LIFF 頁：完整活動清單、真 JS 倒數、收藏/訂閱管理；瀏覽完全不吃訊息配額 | 【03】§4(b)、§7 |
| 4 | **聯盟源接入** | Affiliate 審核通過後，把後台 Promotion Center（campaignName/promoId/start/end/status）併入解析管線當第二資料源交叉驗證；活動連結改帶聯盟參數（robots 明確 Allow） | 【01】§2.2–2.3、【02】§1.4、§3.1 |
| 5 | **節慶檔期預警** | Google News RSS 多關鍵字訂閱（「Trip.com 雙11」「旅展」「セール」…）＋官方 FB/IG 公開貼文監控→提前 1–2 週捕捉大型檔期活動頁上線 | 【01】§3.4、§1.4 |
| 6 | **Playwright 後備** | 若偵測到某頁轉 SPA/JS challenge：headless chromium 局部接管（阻斷圖片字體省流量），只在必要頁面啟用 | 【02】§1.2、§8 |
| 7 | **解析器契約測試** | 把實抓的 `__foxpage_data__` 樣本固化成 test fixtures；Foxpage module 改版（元件 name 變更）時 CI 立即紅燈而非静默漏抓 | 【01】§1.3 |
| 8 | **配額升級治理** | 好友破 ~150 時評估升中用量 NT$800/3,000 則（不可加購）；或導向 multicast-only 策略壓低用量 | 【03】§2.2、§2.4 |

---

## 4. 風險與對策

| # | 風險 | 等級 | 對策 | 依據 |
|---|---|---|---|---|
| R1 | **反爬/封鎖升級**：主站目前無 Cloudflare（自家指紋 GUID/UBT_VID＋行為偵測；affiliate 子網域對非瀏覽器 TLS 直接重置），但防護可隨時加碼 | 高 | ①低頻禮貌抓取：間隔 ≥15 分＋±1–2 分 jitter、誠實 UA 標示專案用途；②ETag/Last-Modified 條件請求＋本地快取；③熔斷：連續 N 次被擋→冷卻 1 小時＋告警，絕不重試風暴；④❌不用驗證碼代打/指紋偽裝/代理池（脆弱且違約）；⑤Affiliate 官方管道作為被封時的備援 | 【02】§2.1–2.2、§7 |
| R2 | **LINE 配額爆量**：輕用量免費僅 200 則/月，且「訊息數＝收件人數」（100 好友＝每月只能全體廣播 2 次） | 中高 | ①預設 multicast 訂閱制取代全體 broadcast；②每則推播前查 `quota/consumption`，>80% 告警、不足降級只推訂閱者；③一次 push 帶 ≤5 message objects 只算 1 則/人→週摘要打包；④夜間 `notificationDisabled`；⑤Reply API（免費）承接所有互動；⑥升級路徑：中用量 NT$800/3,000 則（不可加購）→高用量 NT$1,200/6,000＋NT$0.2 加購 | 【03】§2.1–2.4 |
| R3 | **時區/曆制處理錯誤**：同全球活動各市場開賣時間不同（TW 11/11 中午 vs HK 11/13 21:00）；TH 佛曆（2569）；US 用 PT 且有 DST；頁面甚至有自身不一致案例（US happyfriday meta 寫 10AM、正文 11AM） | 高 | ①一律以元件 timestamp（epoch 毫秒）為準，文案只當展示；②儲存絕對瞬間＋原始 `endTimeZone` 字串，渲染用 IANA 時區（DST 自動處理）；③永不假設 GMT+8；④同一頁衝突時間以 timer 元件優先並記錄 diff 供人工複查 | 【01】§1.3、§1.4-US、§5.1–5.2 |
| R4 | **頁面結構改版**：Foxpage 元件改名/搬移會静默漏抓 | 中 | ①解析器契約測試（fixtures 固化實抓 JSON，P3-7）；②`scrape_runs.items_found` 驟降告警（較前 7 日均值 −50% 即通知）；③快照保留近 K 版可事後重放 | 【01】§1.3、【02】§5 |
| R5 | **GitHub Actions 限制**：schedule 高負載延遲、只能 default branch、public repo 60 天無活動自動停用 | 低中 | ①cron 避開整點（`17,47`）；②keepalive：每週自動 commit（changelog）保活；③關鍵提醒（開賣 T-15min）不依賴 GH Actions 排程精度→由常駐 webhook host 的 cron 執行（Q2 一併決策）；④逃生門：同一程式可在 VPS/NAS 用系統 cron 直接跑 | 【02】§4 |
| R6 | **優惠碼明碼拿不到**（前端領券 API 動態發放，且 restapi 被 robots Disallow） | 註定性 | 產品設計止步於「玩法＋名額狀態＋活動頁連結」，推播文案引導用戶點原頁領券；**絕不**嘗試打內部領券 API | 【01】§1.3-6、§6-5 |
| R7 | **法遵**：商業化轉售、高頻打內部 API＝明確越線；framing 官網違反 ToS LINKING 條款 | 中 | 只抓 robots 允許的公開頁；推播＝摘要＋原頁連結（不整批轉載、不 frame）；卡片按鈕用一般 `uri` 開啟原頁而非嵌入 | 【02】§3.2 |
| R8 | **Webhook 單點故障**：endpoint 掛掉→follow/postback 收不到，長期失敗會被 LINE 暫停推送 | 中 | ①收到事件先回 200 再背景處理；②webhook host 上 healthcheck（同 healthchecks.io 模式）；③redelivery＋`webhookEventId` 去重；④MVP 可先不架 webhook（單向廣播），把依賴往後推（Q2） | 【03】§1.3、§6.1 |

---

## 5. 待用戶決策的開放問題

| # | 問題 | 選項與影響 |
|---|---|---|
| Q1 | **GitHub repo 公開還是私有？** | 公開＝Actions 標準 runner 免費（【02】§4），但爬蟲程式碼與市場策略可被任何人看到；私有＝有免費分鐘數額度（本專案用量極可能夠），代碼私有。**建議私有** |
| Q2 | **Webhook 接收端（常駐 HTTPS）放哪？** | A. 免費小型 PaaS（Fly.io/Railway/Render）；B. Cloudflare Workers；C. 既有 VPS/NAS＋反代；D. MVP 先不架 webhook，只做單向廣播（postback 訂閱延後）。影響 Phase 0/1 工作項 P1-8 與 R5/R8 |
| Q3 | **Phase 2 市場優先序？** | 研究已驗證 hk/jp/kr/th/sg/us 中樞頁皆存活（【01】§1.1）。預設順序 hk→jp→sg→th→kr→us，可調 |
| Q4 | **提醒時點策略？** | 預設「開賣前 15 分鐘」一檔；可選再加「前 1 小時」「結束前 1 小時」。每多一檔＝每人每次多 1 則配額 |
| Q5 | **好友規模預期與付費意願？** | <100 人免費方案夠用（每月約 2 次全體廣播）；若預期破 200 人，是否接受中用量 NT$800/月（不可加購）？（【03】§2.2） |
| Q6 | **是否申請 Trip.com Affiliate 帳號？以誰的名義？** | 申請信 affiliation@trip.com、3–5 工作天；好處＝官方 Promotion Center 資料源＋活動連結可帶聯盟參數（robots Allow）；佣金歸因歸屬需用戶指定帳號（【01】§2.3） |
| Q7 | **推播語言策略？** | A. 全部繁中（簡單，但 jp/kr 市場卡片讀起來是外語活動名）；B. 隨市場語言。影響 Flex 模板數量與 i18n 工作 |
| Q8 | **官方帳號品牌資訊？** | OA 名稱/頭像/說明、是否申請認證（藍盾/綠盾）——認證才能用「通知型訊息」（本專案用不到）但影響信任感；Provider 名稱一經選定不可更改（【03】§1.1） |
| Q9 | **Snapshot 保留版本數 K 與資料保留期限？** | 建議 K=5、ended 活動保留 90 天後清理（SQLite 體積可控） |
| Q10 | **是否需要管理用後台（Web UI）？** | Phase 3+ 可選：查看 events/訂閱/配額/失敗紀錄。若要做，儲存層可能提前升級 Postgres（【02】§6 觸發條件） |

---

## 附錄：研究報告索引

| 報告 | 路徑 | 作者/任務 |
|---|---|---|
| 01 資料來源 | `E:\workspace\trip-event-crawler\research\01-tripcom-promo-sources.md` | promo-scout / t1 |
| 02 爬蟲技術棧 | `E:\workspace\trip-event-crawler\research\02-crawling-stack.md` | crawl-engineer / t2 |
| 03 LINE 整合 | `E:\workspace\trip-event-crawler\research\03-line-integration.md` | line-integrator / t3 |
| 輔助腳本 | `E:\workspace\trip-event-crawler\research\tools\`（fetch/probe/foxpage 解析等，可直接改造為 crawler 雛形） | t1 產出 |

*計畫完。總工作量估計：Phase 0 約 1–2 人日（＋等待 3–7 天）、Phase 1 約 6–9 人日、Phase 2 約 10–14 人日、Phase 3 滾動每項 2–5 人日；MVP（P0+P1）最快約 3 週內可上線運轉。*
