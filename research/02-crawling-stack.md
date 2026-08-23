# 02 — 爬蟲技術棧、排程與反爬策略研究（Trip.com 活動頁監控）

> 任務 t2 產出 · 調查者：crawl-engineer · 2026-01
> 本報告基於對 Trip.com 實際 HTTP 取證（非僅文獻調研）。原始證據存於 `E:\workspace\trip-event-crawler\.tmp-research\`：`trip-robots.txt`（4396B）、`terms-en.txt`（~307KB）、`gh-schedule.md`（67KB）、`partners.html`（52KB）、`dev-portal.html`（8KB）。
> ⚠️ 工具環境限制：本環境 web_search/anysearch 後端不可用（HTTP 402），沙箱封鎖 Windows TLS（pwsh Invoke-WebRequest「基礎連接已關閉」、curl.exe `SEC_E_NO_CREDENTIALS`）；實測全部以 **Node v24.19.0 內建 fetch** 完成。此結論同時證明「純 Node fetch 可直接打 Trip.com 主站」，是技術棧選型的一手證據。

---

## 1. 技術棧建議（Python vs Node.js；HTTP vs Headless）

### 1.1 語言選擇
| 面向 | Python | Node.js |
|---|---|---|
| 爬蟲生態 | 最成熟：httpx、BeautifulSoup4/lxml、Scrapy、tenacity | fetch 內建、cheerio、puppeteer |
| Headless | Playwright-Python 官方支援 | Playwright-Node / Puppeteer 原生 |
| 排程整合 | APScheduler 成熟 | node-cron 較陽春 |
| 團隊慣例 | 資料處理/分析順手 | 若團隊主 JS 則零切換 |

**結論：兩者皆可行；推薦 Python**（爬蟲+資料清洗+排程生態最完整）。但注意：本次取證即用 Node fetch 成功抓到 Trip.com 主站 HTML——代表最輕量的方案連第三方函式庫都不需要。

### 1.2 HTTP 抓取 vs 瀏覽器渲染（何時需要瀏覽器）
判定法則：**先看 view-source 有沒有目標資料**。
- 有 → `httpx`（支援 HTTP/2）或 `requests` + `BeautifulSoup4(lxml)` 即可。
- 沒有（純 SPA、需互動、JS challenge）→ 才上 Playwright（推薦，跨瀏覽器+auto-wait；Puppeteer 僅 Chromium 且偏 Node 生態）。

### 1.3 Trip.com SSR 實測（關鍵一手證據）
- `https://www.trip.com/things-to-do/` → HTTP 200，HTML **1,949,236 bytes**，原始碼含可見文字約 18,342 字元（Trending destinations、Taipei Top picks…）→ **主要活動/目的地頁是伺服器端渲染**，httpx+BS4 就能解析。
- 首頁 `www.trip.com/` → 159,198B，含完整頁尾文字。
- 少數 hub 是純 SPA：`/partners/index` 回 200 但 HTML 只有 meta title（聯盟頁需瀏覽器渲染或走官方註冊流程）。

### 1.4 官方管道優先（比爬蟲更穩）
- **Trip.com Affiliate Program**：`https://www.trip.com/partners/index`（實測 200，SPA 文案 "Trip.com Affiliate Program – Join us and start earning up to 7% commission"）。帶聯盟參數（aid/allianceid/sid）的活動頁在 robots.txt 明確 Allow（見 §3）→ 註冊聯盟帳號後拿到的追蹤連結本身就是官方認可的存取路徑。
- **developers.trip.com**：實測 200 的 B2B 開發者入口（Hotels / Flights / Trains / Tours&Tickets / Car Rentals / Business Travels；子頁 `/hotel`、`/train` 等為 SPA 路由 404，需站內導覽）。若能談到 API 權限，資料取得全面合法化。
- `open.trip.com` → 200 但空 JS 殼；`affiliate.trip.com`／`affiliates.trip.com` 對非瀏覽器客戶端連線重置（見 §2）。

## 2. 反爬現況（Trip.com 實測）

### 2.1 防護層級判斷（HTTP header 取證）
- `www.trip.com` 回應**無任何 Cloudflare 標記**（無 `cf-ray`、無 `server: cloudflare`）；`server-timing: cdn-cache; desc=MISS, edge; dur=5, origin; dur=81` → 自建邊緣 CDN，**目前未掛 Cloudflare/Turnstile**。
- Cookies：`GUID`（附 `GUID.sig` HMAC 驗證）、`UBT_VID`（行為追蹤）、`ibusite`/`ibulocale`/`ibu_country`（geo 設定）→ 指紋/行為偵測基礎存在。
- `x-frame-options: SAMEORIGIN`。
- **選擇性封鎖**：`affiliate.trip.com`／`affiliates.trip.com` 對非瀏覽器 TLS 直接重置連線；同一時間 `www.trip.com` 用同一 client 正常回應 → 子網域層級的 bot 過濾，而非全站統一防護。
- **綜合判斷：主站目前防護＝自家指紋+行為偵測＋部分子網域 TLS 層封鎖；非 Cloudflare Turnstile**。低頻、誠實 UA 的抓取風險低，但防護可隨時升級，設計上要留「被擋就停」的退場機制（§7）。

### 2.2 合理應對（按優先序）
1. **官方/聯盟管道優先**（§1.4）——最穩定、零法律風險。
2. **低頻禮貌抓取**公開活動頁：尊重 robots.txt、間隔 ≥15 分鐘、加 ±1–2 分鐘 jitter、避開整點、UA 誠實標示專案用途。
3. **快取+條件請求**：能用 `ETag`/`Last-Modified` 就用；本地快取減少重複請求。
4. ❌ 不建議：驗證碼代打服務、undetched-chromedriver/camoufox 指紋偽裝軍備競賽（脆弱且違約）、代理 IP 輪換（貴、脆、個人研究用途正當性差）。

## 3. 合規面（robots.txt 與 Terms of Use 實測）

### 3.1 robots.txt（`https://www.trip.com/robots.txt`，全文已存檔）
- `User-agent: *`；**無 Crawl-delay、無 Sitemap 指令**。
- 重點 Disallow（與本專案相關）：內部 API `/restapi/soa2/*`、`/htls/restapi/*`、`/market/datafeed/`、`/datatool/`；搜尋/列表頁 `*searchresults*`、`/searchresult/`、`/hotels/list`、`/hotel/w/list`、ShowFareFirst 機票比價頁；`/webapp/`、`/m/`、`/account/`、`/passport/`；travel-guide 下僅 Allow `destination//attraction//shops//foods//guidebook/` 子路徑。
- **#finally 全域禁帶 `aid=`/`sid=` 參數**（`/*?*aid=*` 等）——但**明確 Allow 帶聯盟參數的活動頁**：
  - `/trains/activity/*?*aid=*`（及 AID/Allianceid/allianceid/sid/SID 變體）
  - `/web-contents/*/growth/*?*aid=*`
  - `/partners/ad/*?*aid=*`
  - robots 最長比對規則下，這些較長的 Allow 勝過全域 Disallow → **聯盟活動頁正是官方預期被抓取的路徑**，與本專案目標完全吻合。
- 另有 AdsBot-Google 區塊、Googlebot-Image `Disallow /*.jpg$`、Twitterbot `Allow:/`。

### 3.2 Terms of Use（`https://www.trip.com/contents/service-guideline/terms.html?locale=en-SG`，©2026 Trip.com Travel Singapore Pte. Ltd.；zh-TW 參數仍回英文內容）
全文 grep `crawl|spider|scrap|harvest|mining|automated|robot` → **無明文禁止爬蟲條款**。關鍵條款（terms-en.txt 行號）：
- L89：所有 IP（含 database rights）保留。
- L91：「You may print off copies, and may download extracts, of any page(s) from our Website for your personal use」→ 個人用途允許下載摘錄。
- L126：「Not to reproduce, duplicate, copy or re-sell any part of our Website in contravention with these terms」。
- L186：禁病毒/未授權存取/DoS。
- L188–198 LINKING 規則：僅可連首頁、不得 frame；L196：「Our Website must not be framed on any other site…」。

**合規結論**：個人研究、低頻、不轉售地抓公開活動頁＝常見且風險低（ToS 未禁止、robots 對活動頁友善）；商業化轉售或高頻打內部 API＝明確越線。通知類產品（LINE 推播）只送摘要+原頁連結、不整批轉載內容，落在安全側。

## 4. 排程方案比較

| 方案 | 成本 | 可靠度 | 適用 |
|---|---|---|---|
| cron/systemd timer | 需常開主機 | 高（配 healthcheck ping） | 已有 NAS/VPS 時 |
| **APScheduler**（Python 行程內） | 免費 | 中（跟著宿主行程） | 爬蟲本身是常駐 app 時；cron/interval 觸發、misfire/coalesce、SQLAlchemy jobstore。文件：https://apscheduler.readthedocs.io/en/3.x/ （已驗證 200） |
| **GitHub Actions scheduled workflow** | public repo 標準 runner **免費**；private repo 有每方案免費分鐘數 | 中高 | **免主機首選**（本專案推薦） |
| 雲端函數（Lambda/Cloud Run Functions + EventBridge Scheduler） | 低頻近免費 | 最高 | 要多雲帳號設定成本 |

### GitHub Actions schedule 已驗證細節（github/docs 原始 markdown）
- 只能在 **default branch** 生效；不支援 `@daily` 等簡寫；官方推薦用 crontab.guru 檢查運算式。
- **高負載延遲**（原文）：「The `schedule` event can be delayed during periods of high loads… High load times include the start of every hour… To decrease the chance of delay, schedule your workflow to run at a different time of the hour.」→ **避開 :00，選冷門分鐘如 `17,47 * * * *` 或 `*/17`**。
- public repo **60 天無活動自動停用排程**（需定期 commit 或 keepalive）。
- Billing 文件原文：「GitHub Actions usage is free for self-hosted runners and for public repositories that use standard GitHub-hosted runners. For private repositories, each GitHub account receives a quota of free minutes...」

### 輪詢頻率建議（針對「活動多在特定時間開跑」）
- 平時 **15–30 分鐘/次**；已知開賣時段前後（如當地 10:00/12:00）收緊到 **~5 分鐘**；全程加 jitter ±1–2 分鐘。
- 不要長期低於 3–5 分分鐘：禮貌考量＋觸發行為偵測風險。失敗時指數退避（§7）。

## 5. 變更偵測與去重

管線：**正規化 → hash → 三態判定**
- 每次抓取抽取事件欄位（title、region、起訖日期、折扣、圖片、url），正規化空白/日期格式。
- `event_key = sha256(標題+地區+起訖)` 作為身分鍵（跨 locale 以 URL 內 id 為優先；否則標題相似度+日期重疊做模糊合併）。
- `content_hash = sha256(全部欄位)` 偵測修改。
- 判定：
  - key 不存在於 DB → **NEW 新活動**
  - key 存在但 content_hash 變 → **MODIFIED**（存欄位級 diff）
  - DB 有、本次缺 → `missed_polls += 1`，**連續 2–3 次**缺席才標 **ENDED**（防止單次渲染失敗誤報）
- Snapshot：每事件保留最近 K 版原始 JSON/HTML 供 diff；存 diff 摘要即可。

## 6. 儲存方案：SQLite 足夠

單寫入者、低寫入量、零維運；開 WAL 支援並讀。Postgres 僅在多寫入者/全文檢索/Web 化需求出現後才升級。Schema 提案：

```sql
PRAGMA journal_mode=WAL;
CREATE TABLE events (
  id INTEGER PRIMARY KEY,
  event_key TEXT UNIQUE,            -- sha256(title+region+dates)
  url TEXT, locale TEXT, region TEXT,
  title TEXT, description TEXT,
  starts_at TEXT, ends_at TEXT,     -- ISO8601
  discount TEXT, image_url TEXT,
  first_seen_at TEXT, last_seen_at TEXT,
  status TEXT CHECK(status IN ('active','ended','unknown')),
  missed_polls INTEGER DEFAULT 0
);
CREATE INDEX idx_events_status ON events(status);
CREATE INDEX idx_events_last_seen ON events(last_seen_at);

CREATE TABLE snapshots (
  id INTEGER PRIMARY KEY,
  event_id INTEGER REFERENCES events(id),
  captured_at TEXT, content_hash TEXT, raw_path TEXT
);

CREATE TABLE scrape_runs (
  id INTEGER PRIMARY KEY, started_at TEXT, finished_at TEXT,
  source TEXT, status TEXT,          -- ok/blocked/error
  items_found INTEGER, error TEXT
);
```

## 7. 失敗處理與告警

- **重試**：tenacity 指數退避+jitter（例：3 次，30s→10min 上限）；一律設 timeout；403/challenge 頁視為「被擋」→ 直接告警，**不做重試風暴**。
- **死人開關（dead-man's switch）**：每次成功跑完 ping 一個 [healthchecks.io](https://healthchecks.io/) URL（官網文案："We notify you when your nightly backups, weekly reports, cron jobs, and scheduled tasks don't run on time."）；逾時未收到 ping 自動寄 email/TG——爬蟲「靜默掛掉」也能被發現。
- **活動異動推播**：[ntfy.sh](https://docs.ntfy.sh/)（可自架）手機推播 NEW/MODIFIED/ENDED。
- **熔斷**：連續 N 次被擋/失敗 → 冷卻 1 小時停止輪詢＋告警一次，避免升級成封禁。
- 每次 run 寫一列 `scrape_runs`，供事後稽核。

## 8. 推薦組合（MVP）

> **Python 3.12 + httpx + BeautifulSoup4(lxml) + SQLite(WAL) + GitHub Actions scheduled workflow（public repo，cron 避開整點，如 `17,47 * * * *`）+ tenacity 重試 + healthchecks.io 死人開關 + ntfy.sh 推播**

- 頁面若遇純 SPA 再局部換 Playwright（headless chromium、阻斷圖片字體省流量）；主站多數頁 SSR，先別引入瀏覽器。
- 同步申請 Trip.com Affiliate（最高 7% 佣金）/ developers.trip.com B2B API，能走官方就走官方。
- 合規紅線：只抓 robots 允許的公開頁（活動/growth 頁尤佳）、≥15 分鐘間隔、摘要+連結推送而不整批轉載、絕不碰 `/restapi/soa2/*` 等內部 API。

## 參考連結

- Trip.com robots.txt — https://www.trip.com/robots.txt （已抓取存證）
- Trip.com Terms of Use — https://www.trip.com/contents/service-guideline/terms.html?locale=en-SG （已抓取存證）
- Trip.com Affiliate Program — https://www.trip.com/partners/index （up to 7% commission）
- Trip.com Developers（B2B API）— https://developers.trip.com/
- GitHub Actions schedule 事件 — https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule （延遲警告、60 天停用、default branch）
- GitHub Actions 計費 — https://docs.github.com/en/billing/concepts/product-billing/github-actions （public repo 免費）
- APScheduler — https://apscheduler.readthedocs.io/en/3.x/
- healthchecks.io — https://healthchecks.io/
- ntfy — https://docs.ntfy.sh/
- httpx — https://www.python-httpx.org/ · BeautifulSoup4 — https://www.crummy.com/software/BeautifulSoup/bs4/doc/
- Playwright(Python) — https://playwright.dev/python/docs/intro · Puppeteer — https://pptr.dev/
- tenacity — https://tenacity.readthedocs.io/ · SQLite WAL — https://sqlite.org/wal.html
- Cloudflare Turnstile — https://developers.cloudflare.com/turnstile/ （注意 `/cloudflare-turnstile/` 舊路徑 404；本站實測未使用）
- crontab.guru — https://crontab.guru/
