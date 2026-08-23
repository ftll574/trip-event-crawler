# Trip.com 各國促銷活動資料來源研究報告

> 任務：t1「研究 Trip.com 各國促銷活動資料來源」（team: trip-promo-research / researcher: promo-scout）
> 研究日期：2026-08-24。重點為**資料來源的取得方式**（data sources），非爬蟲實作。
> 所有標注「✅ 已驗證」的內容皆於本研究期間以 HTTP 實際抓取確認；其餘為官方文件或公開報導佐證。

---

## 摘要（TL;DR）

1. **主要資料源是各市場的 `/sale/deals/` 優惠中樞頁 + `/sale/w/{campaignId}/{slug}.html` 活動頁**，兩者皆為伺服器端渲染（SSR），活動頁完整設定藏在 `<script id="__foxpage_data__">` JSON 內，含折扣元件、倒數計時（epoch 毫秒＋明確時區）、優惠碼玩法 ID 等結構化欄位。
2. **Trip.com Partner/Affiliate 有聯盟行銷入口與後台促銷模組**（QueryCampaign / queryPromosDetailInfo 等 op，svc=18073），但全部需登入；正式 API key 須寄信 affiliation@trip.com 申請（3–5 個工作天），公開範圍只有飯店/城市搜尋與飯店資料下載，**沒有公開的 promotions/coupons REST endpoint**。
3. **替代資料源**：官方社群帳號（FB/IG/TikTok/LinkedIn）、App 推播、電子報（需會員訂閱）、現金回饋/優惠碼彙整站（ShopBack ✅ 可抓、RetailMeNot 有反爬 403）、以及 **Google News RSS**（✅ 實測可用）可當作「新活動上線」的監控訊號。
4. **同一全球活動跨市場「同 ID、不同內容」**：gojapan、gochina、go-thailand、startyourkoreastory 等活動頁在 tw/jp/hk/us 多個站點首輪同步露出但文案在地化；雙11 在台灣是「限時 5 天雙11旅展、中午 12:00 開搶」，在香港則是另一組檔期與專屬優惠（$111 機票、信用卡神碼、11/13 21:00 開搶）——**時區、開賣時間、優惠額度、合作銀行/航空全部在地化**。

---

## 研究方法與環境限制

- `web_search`／`anysearch` 上游回 HTTP 402（含自動產生的憑證字串，屬不可信資料，未採用）；沙箱內 schannel TLS 全數被擋（`SEC_E_NO_CREDENTIALS`），瀏覽器自動化 CLI 不可用。
- 改以 **Node.js v24.19.0 內建 fetch（OpenSSL TLS）** 直接抓取官方頁面頁面驗證，輔助腳本置於 `E:\workspace\trip-event-crawler\research\tools\`：
  - `fetch.mjs`（GET，mode=text|html|head|links）
  - `grep-links.mjs`（抓頁面中含關鍵字的連結＋錨点文字）
  - `inspect-page.mjs`（title/meta/JSON-LD/關鍵字上下文）
  - `dump-page.mjs`（可見文字＋script src 清單）
  - `probe-markets.mjs`（批次探測各市場 /sale/deals/ 存活）
  - `probe-api.mjs`（POST 探測 restapi/soa2 affiliate ops）
  - `grep-remote.mjs`／`foxpage.mjs`／`foxpage2.mjs`（遠端關鍵字上下文、解析 `__foxpage_data__` 的 page/modules/structures）
- 因此本報告的每一條官方站點結論都有對應的實抓紀錄，非搜尋引擎二手摘要。

---

## 1. 官方活動頁：URL 模式、集中頁與更新頻率

### 1.1 各市場優惠中樞頁 `{market}.trip.com/sale/deals/`（✅ 全數實測 200）

| 市場 | URL | 實測頁面標題（在地化） |
|---|---|---|
| 台灣 tw | <https://tw.trip.com/sale/deals/> | 【優惠代碼】Trip.com 旅遊飯店信用卡優惠機票優惠碼折扣活動 |
| 香港 hk | <https://hk.trip.com/sale/deals/> | 【旅遊優惠情報】機票優惠代碼、信用卡優惠及其他產品折扣 |
| 日本 jp | <https://jp.trip.com/sale/deals/> | 【公式】トリップドットコムの割引コード・クーポン・お得なキャンペーン情報 |
| 韓國 kr | <https://kr.trip.com/sale/deals/> | 트립닷컴 특가 프로모션 & 할인코드 |
| 泰國 th | <https://th.trip.com/sale/deals/> | รหัสโปรโมชั่นและดีลสุดพิเศษมากมาย |
| 新加坡 sg | <https://sg.trip.com/sale/deals/> | （英文 Deals/Promo Codes 頁） |
| 美國 us | <https://us.trip.com/sale/deals/> | Trip.com Deals, Promo & Discount Codes |
| 全球 www | <https://www.trip.com/sale/deals/> | 由 www.geo 導向所處網路對應市場（本次從此網路被導到 tw） |
| 其餘實測存活 | ph / de / my / fr / vn / es / id / it / uk / au | 同模式存在 |
| 印度 in | <https://in.trip.com/sale/deals/> | ❌ 404（該市場無此中樞頁） |
| 中國 cn | <https://cn.trip.com/sale/deals/> | 抓取失敗（隔離網路，無法驗證） |

- 這一頁就是各市場的**集中 campaign landing page ＋ 優惠券專區**（標題即「優惠代碼／割引コード・クーポン／프로모션 & 할인코드／Promo & Discount Codes」），列出當前所有進行中的活動卡片（標題＋描述＋活動頁連結）。
- **發現新活動的兩個固定入口**：(a) 各市場首頁的促銷輪播區；(b) `/sale/deals/` 中樞頁列表。兩者都是 SSR HTML，可直接解析。

### 1.2 活動頁 URL 模式（✅ 大量樣本實測）

```
https://{market}.trip.com/sale/w/{campaignId}/{slug}.html?locale=xx-XX&curr=XXX[&promo_referer={aid}_{cid}_{pos}&transparentBar=1&wkp=1]
```

- `{campaignId}`：**純數字**（舊式）或 **16 碼隨機字串**（新式），slug 為英文活動代稱。
- 追蹤參數 `promo_referer={aid}_{cid}_{pos}` 為聯盟/版位追蹤；`transparentBar=1`、`wkp=1` 為嵌入框架樣態參數。
- `locale` 與 `curr` 可強制切換語言幣別 —— 表示**同一活動頁可跨語系複用**。

實測存在的 campaignId 樣本（依類型分組，均可在對應市場存取）：

- **常青旗艦**：`4823` seasonal-promotion（多分頁：flight-deals/hotel-deals；內部參數 `internal campaignId:4491, slotId:45, cardQuantityLimit:"6"`）
- **目的地大促**：`37676 gojapan`、`19280 gochina`、`e7fjmapjissndf3r go-thailand`、`2xiuiykzyfph6wtw startyourkoreastory`（tw/jp/us 共用）、`4337 southkorea-destination`、`19595 exploreasia`、`19133 2026exploreamerica`、`4217 japan-travel`
- **會員日 Member Day**：`wrjdvj6d5p9db25f`（TW）、`l3iaaiaybmqjcjja jp-memberday-june`、`ap2vawe3dclh3bgr hkmemberday`（JP/KR/TH/SG 亦有各自版本）
- **週期快閃**：`15871 happyfriday`（US 景點週五快閃）、`z8hpr8495sqitavz dealsoftheweek`（US）、TW 每周一機票/沖繩代碼（附於 `17859 okinawapromotion`）
- **航空公司聯名**：`gnxffrndq4a1oyvm airline-ke-kij`、`ef7tyxlbmjljkiw5 airline-lj`、`akzikiys2cknxlvr airline-tw`（長榮/星宇類）、`25293 philippine-airlines`、`14940 super-flight-day`（JP 每月25日）、`31376 superbusan-promotion`、`4225 super-worldweek-th`
- **銀行/卡組織聯名**：`15290 boc`（HK 中銀）、`15927 hangsengbank`、`3196 mastercard-flight-hotel-tnt`、SG 六家銀行（DBS/OCBC/HSBC/Citi/StanChart/DCS，見 1.4）
- **其他**：`17859 okinawapromotion`、`42134 family-campaign`、`4283 friend-referral`、`6p8fynbi0tctq9y9 hk26summer`、`9717 flight-hot-deals`(HK)、`12343 longhaultrip`、`42463 hkpremium`、`24446 hkmo`、`43408 mainlandtraintravel`、`kquff9fxm8rtuj7j vibetravelling`、`21947 super-new-opening-hotels`、`oxpsorbijlbbhzzi 26hengqin`

### 1.3 活動頁內部結構：Foxpage CMS（✅ 解析實證）

活動頁由 Foxpage CMS 以 React SSR 產出，**整頁設定序列化在一個 script tag 內**：

```html
<script id="__foxpage_data__" type="application/json">{ ... }</script>
```

- 頂層 keys：`root, page, modules, structures, resource, option, aresHost, i18n`。
- `page` 例：`{appId:"appl_zrvXd1AE3LIf8a9", slug:"sale", pageId:"cont_u7SPuu641U13Ysw", locale, fileId}`。
- `structures` 為節點陣列（okinawapromotion 實測 315 個節點），每節點 `{id:"stru_*", name:"@ctrip/cloud-component-*", label, props}`；模組 JS 來自 `ak-s-cw.tripcdn.com/modules/fpc/cloud-component-*`。
- 另有 `window.__CARGO_DATA__`、`div#foxpage-app`、`data-foxpage-node-id/type` 屬性可供定位。

**關鍵元件與欄位（直接可解析的結構化促銷資料）：**

1. 優惠券元件 `@ctrip/cloud-component-sales4-coupon-b`（label `coupon-v2`）props 例：
   ```json
   {"prizeType":4,"campaignId":"17859","playIds":["165629"],
    "txtOutOfStock":"目前已搶完，每週一更新名額",
    "title":{"enable":true,"text":"每周一12:00｜沖繩、釜山優惠代碼"},
    "floorBg":{"color":"#2346ff"}}
   ```
   → `playIds` 是領券玩法 ID；`txtOutOfStock` 直接揭露**補貨節奏（每週一）**。
2. 倒數計時元件（member-day 頁實測）：
   ```json
   {"startTime":1787521841533,"endTimeNew":1787760000367,"tipsTimeNew":1787760000282,
    "endTimeZone":"GMT+08:00","copy":"活動開始","endTips":"活動熱烈進行中",
    "tipsTimeZone":"GMT+08:00","type":"large"}
   ```
   → **開始/結束時間為 epoch 毫秒＋明確時區字串**，正是排程爬取需要的欄位。
3. 條款文字含精確期限：「*優惠代碼有效日期：2026 年 5 月 20 日 23:59 (GMT+8)。兌換旅遊產品將會立即消耗 Trip Coins。」
4. 分頁切換參數：`dateTabSwitchTime:1800000`（30 分鐘換 tab，多用於多檔期輪播）。
5. SEO/meta 由 `@ctrip/cloud-component-trip-promo-head-pack` 伺服器端渲染（TDK＋Share Info）；**活動頁沒有 JSON-LD 結構化資料**，解析目標就是 `__foxpage_data__`。
6. **優惠碼明碼不在靜態 HTML**：碼值由前端呼叫 API 於領取時發放；靜態層可得的是玩法 ID、名額狀態文案、時間與範圍。

### 1.4 更新頻率與檔期節奏（✅ 各市場頁面文案實證）

| 市場 | 固定節奏（自頁面文案擷取） |
|---|---|
| TW | 每週一 12:00 沖繩/釜山優惠代碼（售完「每週一更新名額」）；會員日每月 27 號（$1,500 代碼）；LINE Bank 週三 85 折（折 $1,400）；Visa 卡折抵 $2,000；親子活動 6/15–8/31 送 Trip Coins 2,500；JR PASS 5 折 |
| JP | 每月 25 日スーパーフライトデー（機票 6,900 円~）；毎月 27 日メンバーズデイ（最大 5% Trip Coins）；スーパー・ワールドウィーク（ホテル 50%）；東北 60% OFF；T'way/Jin Air LCC 專案 |
| KR | 진에어 단독 라이브；슈퍼 멤버스데이 7% 적립；일본 초특가 매주 수요일 5만원권；중국 매주 화·목 5만원권；트립타임 항공+호텔 평균 11%；제주항공 월요깜짝할인；브랜드위크 월·수·금 9,900원 핫딜 |
| TH | Member Day ฿800；Flash Sale ทุกวันอังคารเที่ยงตรง（每週二正午，胡志明/吉隆坡 ฿3,800~）；Flash Sale ทุกวันจันทร์ 50%（每週一）；UOB 折 ฿1,200；Ritz-Carlton voucher ฿14,000 Top Spender；年份用佛曆（2569 = 西元 2026） |
| SG | 銀行日曆制：DBS/POSB Monday Yays（週一 $200 OFF）；OCBC Wander Wednesday（$120）；HSBC Thrilling Thursday（TravelOne $120）；Citi Fly-days（機票 50%）；StanChart/DCS（$100）；NATAS 旅展 8/21–23（攤位碼 S$20,000）；STARLUX 15%；學生票 |
| US | Trip Tuesday（每週二 $99 機票快閃）；國際線滿 $200 減 $20；ATTRACTIONS & TOURS FLASH SALE EVERY FRIDAY 11 AM PT（meta description 卻寫 10 AM——同一頁內部不一致，爬蟲需以元件時間戳為準）；新飯店 20% off；Invite & Earn |

**更新頻率結論**：常青頁（seasonal-promotion/deals hub）持續滾動替換卡片；週期快閃為「週更」（每週固定星期幾＋固定時刻，各市場不同）；會員日月更（多市場綁每月 27 日或各自日期）；大型節慶檔期（雙11/黑色星期五/旅展）為事件制，通常提前 1–2 週上線活動頁、限時 4–7 天。

### 1.5 robots.txt 與 sitemap（✅ 實測）

`https://tw.trip.com/robots.txt`：

- `promotion`、`sale` 路徑**未被 Disallow**（活動頁可合法抓取）。
- Disallow：`/webapp/`、`/restapi/soa2/*`、`/htls/restapi/*`、`/market/datafeed/`、`/m/`、searchresults。
- `Allow: /partners/ad/*?aid=`（聯盟廣告素材放行）。
- `sitemap.xml` 不存在（tw/www 均 404）→ **無法靠 sitemap 發現新活動，需巡檢 deals hub 與首頁**。

---

## 2. Trip.com Partner/Affiliate API（partner 計畫）

### 2.1 入口與條件（✅ 入口頁實測）

- 聯盟計畫入口：<https://www.trip.com/partners/index>（footer「聯盟計畫」；SPA，內容由 app bundle 讀出）。
- 條件摘要（官網宣稱）：佣金最高 **7%**、cookie 歸因 **7 天**、月訂單量階梯費率、請款審核 **6–8 週**＋ 5 天內轉帳；目標客群明列「coupon sites, publishers」，垂直產業含 Airline/Loyalty、Bank/Credit Card 等。

### 2.2 後台路由與促銷相關模組（自前端 bundle 路由表實證）

- 後台路由：`/partners/{dashboard,booking,commission,tools,report,payout,account,help,campaign,keywords}`
- 工具：`deeplink`、`staticbanner`、`dynamicbanner`、`richEditor`、`bankEntrance`、`api`
- **促銷相關**：`/partners/tools/promotion/popularDeals`、`/partners/tools/promotion/list`；`/partners/tools/pmCenter`（Promotion Center：main/history）
- 後台 API 模式：`POST https://www.trip.com/restapi/soa2/{service}/json/{operation}`；affiliate 服務編號 **18073**。實證存在的 ops：
  `QueryCampaign`、`QueryCampaignSupportedLocale`、`signUpCampaign`、`queryPopupWindowInfo`、`queryPromosDetailInfo`、`queryCommissionOrder`、`queryCommissionAmountV2`、`reportAllianceOrder`、`queryPaymentHistory`、`queryApCoinsDetail`、`sitePerformance`、`querySidList`、`hotCityList`；另有 `getProductDetail`(svc 16436)、`getPromotionInfo`(svc 16201)。
  未帶登入憑證探測一律 **HTTP 403**（login-gated）。

### 2.3 API 申請門檻（官網 locale bundle 文字實證）

- 取得正式 API key：**寄信至 affiliation@trip.com**，官方回覆「3–5 個 working days」（bundle key `key_api_notice_1`）。
- 公開聯盟 API 範圍＝**飯店/城市搜尋＋飯店資料下載**（`key_tools_api_doc_sub_title`）；完整 API 文件需帳號開通後解鎖。
- **結論：沒有對外的 promotions/coupons REST endpoint**。聯盟夥伴取得促銷的官方途徑是後台 Promotion Center：
  - Promo Campaign / Incentive 模組欄位：`campaignName`、`promoId`、`campaignStartTime`、`campaignEndTime`、`status`（Ongoing | Expired）、`description`、`terms`，並提供 Share→promo link、Book direct。
  - Promotion Center 另有「Top Deals」「Hot Sellers」分頁（商品＋評分＋預估收益）。

---

## 3. 替代資料源

### 3.1 社群官方帳號（✅ 自 tw.trip.com 首頁 JSON-LD `sameAs` 實證）

- Facebook：<https://www.facebook.com/Trip>
- Instagram：<https://www.instagram.com/trip>
- TikTok：<https://www.tiktok.com/@trip.com>
- LinkedIn：<https://www.linkedin.com/company/trip-com/>
- 首頁未列 YouTube 與 X/Twitter 連結；各市場另有在地小編粉專（如 Trip.com 台灣），活動貼文常附活動頁短鏈。→ 可作為「新活動上線」的早期訊號源（公開貼文）。

### 3.2 電子報與 App 推播（定性描述）

- **電子報**：無公開封存頁（tw 首頁無 subscribe/電子報連結實證）；行銷信隨會員註冊/帳戶內行銷通知設定發送。屬會員內容，需帳號授權才能取得，不適合無帳號蒐集。
- **App 推播**：Trip.com App 對閃購/會員日/價格提醒做推播（裝置端通知，無公開 feed）；推播文案即活動名＋開賣時間，但要系統性取得需自有帳號＋裝置，成本高。建議只把兩者列為補充訊號。

### 3.3 比價／優惠彙整站（第三方聚合）

| 站點 | URL | 實測結果 |
|---|---|---|
| ShopBack 台灣 | <https://www.shopback.com.tw/tripcom> | ✅ 200；「<18% 現金回饋, 優惠碼 & 折扣碼」，含回饋率變化歷史與活動檔期，可解析 |
| RetailMeNot | <https://www.retailmenot.com/view/trip.com> | ⚠️ 403（Cloudflare「Just a moment…」反爬），需另想辦法或放棄 |
| Money101 / roo.cash 等 | （文章型介紹信用卡×Trip.com 檔期） | 本次未取得穩定 URL，列入待補清單 |

### 3.4 新聞/RSS 監控（✅ 實測可用，推薦）

Google News RSS 對活動上線反應快且無反爬：

```
https://news.google.com/rss/search?q=%22Trip.com%22+%E9%9B%9911&hl=zh-TW&gl=TW&ceid=TW:zh-Hant
```

實測命中（雙11 相關，見 §5 引用）；亦可換關鍵字（「Trip.com 旅展」「Trip.com セール」等）做多市場監控。

---

## 4. 單一活動的可用欄位模型（自 `__foxpage_data__` 實證歸納）

| 欄位 | 來源位置 | 實例 |
|---|---|---|
| 活動名稱/slug | URL slug＋head-pack meta＋模組 title | `okinawapromotion`、「每周一12:00｜沖繩、釜山優惠代碼」 |
| 折扣形式 | coupon/timer/文案元件 | 代碼折抵、立即折扣、Trip Coins 回饋（prizeType:4）、禮遇voucher、買1送1 |
| 開始/結束時間＋時區 | timer 元件 epoch 毫秒＋`endTimeZone`/`tipsTimeZone` 字串 | `endTimeNew:1787760000367`, `"GMT+08:00"` |
| 開賣/搶購時刻 | 文案＋timer＋quota 文案 | 「每周一12:00」、「EVERY FRIDAY 11 AM PT」、「11月13日9PM開搶」 |
| 適用範圍 | 分頁/卡片元件與條款 | 機票(航線/航空)/飯店(目的地)/景點/火車；最低消費、會員限定、卡別限定 |
| 優惠碼 | 領券元件 playIds（碼值前端 API 發放） | `playIds:["165629"]`, `campaignId:"17859"` |
| 名額/庫存狀態 | `txtOutOfStock` | 「目前已搶完，每週一更新名額」 |
| 活動 ID 體系 | URL campaignId＋內部 campaignId/slotId | 外部 `4823` ↔ 內部 `4491`+`slotId:45`；會員日內部 `campaignId:"51171"` |
| 條款 T&C | 富文本元件 | 「*優惠代碼有效日期：2026年5月20日 23:59 (GMT+8)…」 |
| 檔期輪播 | `dateTabSwitchTime` | 1800000 ms（30 分鐘切換檔期 tab） |

---

## 5. 同一全球活動在各國站點的差異（雙11 案例＋通用觀察）

### 5.1 雙11（2025）跨市場實例（Google News RSS 實測命中之公開報導）

- 台灣：「全年最強優惠『雙11旅展』限時5天隆重登場」— 經商新聞（2025-11-11）：<https://news.google.com/rss/articles/CBMiTkFVX3lxTFBCSFJWdkUyWnVsOVdoQ18wMy1nVXZMMkphYUlZeVVmRHRDdWZhZ3R1UEh6M3gteVd3eEJ5NGhCanhudVRDN2VrQkc3Q0ZoQQ?oc=5>；TVBS「限時五天！trip.com雙11旅展今中午開搶 日本機票、飯店11元起」：<https://news.google.com/rss/articles/CBMiTkFVX3lxTE9sdjNWNDJWR3g5bjFUWThHWFZjSFBjaDBUbXBLblR6aFhKVnZ6Wm1vUHh1TURLMTlRQXV6T1paTnFlRUxmLVFZZng4Q3poUQ?oc=5>；NOWnews「雙11搶機票！Trip.com飛日本11元、飛韓泰999元」：<https://news.google.com/rss/articles/CBMiTEFVX3lxTE55V2dTaWlEZjl2dnRaeUtpWWo1WThOZXdXbG5hWkdUMERZN3EwZ1Y5dXFDNkZWWnZXTUd3Ny0zdmFjQ3E1bWJYSjhuMTDSAVJBVV95cUxNMHJubmxQQ0s3VmxvWHd1UjQzQlJTS3k1ZkZ6OFRtNjJNTnQwemd4Uk9QNjFDX2ZDa3VETTFUVEdZOFhiNmN1RUowZlQ3YkpDUmZn?oc=5>；ETtoday「今中午開搶！日本單程機票、飯店11元起」：<https://news.google.com/rss/articles/CBMiWkFVX3lxTE9vc0tGNXV6ZXU3OURZdGMzc2VjcjZuNm9JNnE1ME1QRjAzaGZLQldWX1dDc3BTNkxnQ005OURVdE9DblBCdDVKRTg1MjlnalFvZUVJNWdWajVyd9IBT0FVX3lxTE9OS05FU1IxeUdPWFpreXRJempyZWpCVTA0QjA0Q1dqelVsRkdJcDRoN29GRXRMcGNGcmdZaHBJRC1OV2JJTmJPanlHRm1pXzg?oc=5>
- 香港：utravel HK「Trip.com雙11機票優惠｜台灣機票買1送1！人均$688起直飛台北！11月13日9PM開搶」（港人視角推台航線、開賣時刻不同）：<https://news.google.com/rss/articles/CBMi2wJBVV95cUxPLXhEWmRHRFU4U3dvVmc2a3Q5ZTUxaVRVX1VLekpqS0xqOVBKTmd0eGN5SVE5REI4RTNHdVJTa25tUVVfVFBwYzFZc0J4TFRvcTJhVzctbkJCQVVwZkExVmxYQTFsNFczUjFJalVGWjJUOUpsNzcyY3dfMUc1ZlVNODRxbjNFMnE4b1N0T0hOOEdKNmUyZUhMeFoyYi1HOTlYU3RESDIwZEdGY1VlaFpDcVFBMnZ0UG9IRm8zWDhlLV9lVnc4VUhoYVZPa2ZaRUNnTEZuNTg4NUF6Zzdyc0s1S1FQc0ZobS1nSElGUHJKYk9ydTZoTG1YRnVuQUFPQXNCdEtzX0JnVWduaGk1ZVMyTVZHWGtJYTJtYS1yRVgwYklWMmhGdUxoaXYtWENpSGppajRwVHFuV0RDTEJXeEVGdDZUakVYVXN5OXNibkRoT0hxOUtZb0dHSTFSNA?oc=5>；Yahoo HK「東京平機票優惠｜香港航空連稅$111、優惠低至1折｜Trip.com雙11優惠2025」：<https://news.google.com/rss/articles/CBMi9wFBVV95cUxNT0JFUWxCOVVmRUQtUE9ZdTNNVWlzOGhyaHotMjNLUVFSU2dSNUFjQU8wT3ZzYkFvNzVHWFNzMDMwZXZWNHNNT1FaLWdQTXR3SXl4cmJHRnotNWZ2Y1dKcnNxR2lSaTZLNmlDclpxbmc3LUg1OUN6S3ZyNzU3bVVPNFdtVEJWcWd0Um4yUHk4cHN1MlU4OGhtd1JBZEZId0ZHVVRSMUFlSGthRUtUa0c1QTc0S1plZjVBLXpCd2hFM0daZ1lkUzBjY3NYTUplekxsU1JPRnRvMENkTXE1eDVPUGNRN011Ymg1QUsyVHAxd0NDNURYWm1J?oc=5>
- 觀察重點：**同一「11.11」檔期在 tw＝11/11 中午開跑、限時 5 天的旅展型大促；hk＝另一組 SKU（港航 $111、1 折）＋ 11/13 21:00 快閃**。開賣時刻、幣別、航線、合作方全然不同。

### 5.2 通用差異規律（§1.1–1.4 實證彙整)

1. **同 campaignId 跨市場復用、內容在地化**：`gojapan/gochina/go-thailand/startyourkoreastory/philippine-airlines` 同步出現在 tw/jp/hk/us 首頁輪播，但語言、幣別、SKU 各異（URL 的 `locale`/`curr` 參數即可切換）。
2. **會員日全球都有、權益各異**：TW $1,500 代碼／JP 最大 5% Coins／KR 7% 適立／TH ฿800。
3. **每週快閃日照市場錯開**：TW 週一 12:00、US 週五 11AM PT（景點）＋週二 $99、TH 週二正午＋週一 50%、KR 週三（日本）/週二·四（中國）/週一（濟州航空）、SG 按銀行分週一～週五。
4. **刷卡合作徹底在地化**：TW Visa/LINE Bank、HK 中銀/恒生/Mastercard、SG DBS/OCBC/HSBC/Citi/StanChart/DCS、TH UOB。
5. **曆制/時區差異**：TH 用佛曆（2569）、US 用 PT 時區——解析時務必讀元件內的 `endTimeZone` 字串而非假設 GMT+8。

---

## 6. 取得策略建議（供後續 crawler 設計排序）

1. **第一優先**：每日抓 `{market}.trip.com/sale/deals/`（17 市場）＋首頁輪播 → 取得當前 campaignId 清單。
2. **第二優先**：對每個 campaignId 抓 `/sale/w/{id}/{slug}.html`，解析 `__foxpage_data__`：timer（epoch＋時區）、coupon-v2（playIds/prizeType/outOfStock 文案）、tab 切換時間、T&C —— 即得 §4 欄位模型。
3. **第三優先**：申請 Partner/Affiliate 帳號（affiliation@trip.com），啟用後台 Promotion Center 作為官方授權的促銷清單來源（campaignName/promoId/start/end/status）。
4. **監控補充**：Google News RSS 多關鍵字訂閱＋官方 FB/IG 公開貼文 → 提前捕捉節慶檔期上線。
5. **注意**：優惠碼明碼與領券 API（`restapi/soa2`）被 robots Disallow 且需登入/前端互動，設計上應止步於「玩法與名額名額狀態」層級。

---

## 附錄 A：本研究輔助腳本（`E:\workspace\trip-event-crawler\research\tools\`）

`fetch.mjs`（mode=text|html|head|links）、`grep-links.mjs`、`inspect-page.mjs`（meta/JSON-LD）、`dump-page.mjs`、`probe-markets.mjs`（17 市場 deals hub 探測）、`probe-api.mjs`（soa2 affiliate ops POST 探測，403 實證）、`grep-remote.mjs`、`foxpage.mjs`/`foxpage2.mjs`（`__foxpage_data__` 解析）。

## 附錄 B：參考連結總表

**官方頁面（本研究實抓）**
- 優惠中樞：https://tw.trip.com/sale/deals/ ・ https://hk.trip.com/sale/deals/ ・ https://jp.trip.com/sale/deals/ ・ https://kr.trip.com/sale/deals/ ・ https://th.trip.com/sale/deals/ ・ https://sg.trip.com/sale/deals/ ・ https://us.trip.com/sale/deals/ ・ https://www.trip.com/sale/deals/
- 代表活動頁：https://tw.trip.com/sale/w/wrjdvj6d5p9db25f/member-day.html ・ https://tw.trip.com/sale/w/37676/gojapan.html ・ https://jp.trip.com/sale/w/l3iaaiaybmqjcjja/jp-memberday-june.html ・ https://us.trip.com/sale/w/15871/happyfriday.html ・ https://us.trip.com/sale/w/z8hpr8495sqitavz/dealsoftheweek.html ・ https://tw.trip.com/sale/w/17859/okinawapromotion.html ・ https://tw.trip.com/sale/w/e7fjmapjissndf3r/go-thailand.html ・ https://tw.trip.com/sale/w/2xiuiykzyfph6wtw/aug-super-destination-startyourkoreastory.html
- robots：https://tw.trip.com/robots.txt
- 聯盟入口：https://www.trip.com/partners/index （申請信箱：affiliation@trip.com）
- 官方社群：https://www.facebook.com/Trip ・ https://www.instagram.com/trip ・ https://www.tiktok.com/@trip.com ・ https://www.linkedin.com/company/trip-com/

**第三方**
- ShopBack TW：https://www.shopback.com.tw/tripcom ・ RetailMeNot：https://www.retailmenot.com/view/trip.com
- Google News RSS（雙11 監控範例）：https://news.google.com/rss/search?q=%22Trip.com%22+%E9%9B%9911&hl=zh-TW&gl=TW&ceid=TW:zh-Hant

**雙11 跨市場報導（經 Google News RSS 取得之原始連結，見 §5.1）**：經商新聞、TVBS、NOWnews、ETtoday、Yahoo TW/HK、utravel.com.hk（連結如上）。

---
*報告完。後續任務（02+）可依 §6 排序直接設計抓取目標。*
