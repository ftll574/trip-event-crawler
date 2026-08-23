# LINE Messaging API 推播與提醒方案研究

> 任務：t3 ｜ 研究日期：2026-08-24 ｜ 團隊：trip-promo-research / line-integrator
> 資料來源：LINE 官方文件（developers.line.biz，markdown 原始碼直接抓取）、tw.linebiz.com 台灣官方部落格、GitHub API。
> 本機原始檔快取：`research/_src/out/`（LINE docs markdown + API reference 全文），抓取腳本在同目錄 `_src/`。

---

## 0. TL;DR — 對「機票/旅遊搶購活動通知」專案的落地建議

1. **架構**：LINE 官方帳號 (OA) + Messaging API。Webhook 只處理 `follow`（存 userId、回活動清單歡迎訊息）與 `postback`（rich menu 按鈕互動）；其餘通知全部由後端排程主動 push/broadcast。
2. **費用**：台灣輕用量免費 200 則/月（訊息數＝收件人數）。好友數 ≤100 時每月可全體廣播 2 次；低頻精選通知夠用，好友成長後升級中用量 NT$800/3,000 則或高用量 NT$1,200/6,000 則+加購 NT$0.2 起。
3. **提醒組合**：到點前 push 提醒（主力）＋ rich menu 常駐「搶購日曆」LIFF 頁（瀏覽不吃配額）＋ 每張活動卡附 .ics 下載（用戶原生日曆提醒）。Google Calendar API 代管不建議做。
4. **卡片**：Flex Message carousel（上限 12 張 bubble），折扣 % 用大字級色塊、倒數用文字由後端排程更新、footer 按鈕 `uri` action 直開活動頁；先用 Flex Message Simulator 調版。
5. **LINE Notify 已死**（2025-03-31 終止）：唯一正解是 Messaging API。台灣後繼的「LINE 通知型訊息」**禁止行銷內容**且限認證帳號，不適合活動促銷。

---

## 1. Channel 建立流程與 Developers Console 要點

### 1.1 建立流程（2024-09-04 新制）

**自 2024-09-04 起不能再直接在 LINE Developers Console 建立 Messaging API channel**。現行流程：

1. 註冊 **LINE Business ID**（business.account.line.me）。
2. 建立 **LINE 官方帳號**（OA entry form，免費，選擇產業類別）。
3. 到 **LINE Official Account Manager**（manager.line.biz）→ 設定 → 啟用 **Messaging API**（系統自動建立對應 channel，此步驟不可逆）。
4. 啟用時選擇 **Provider**（提供者）——**一經選定不可更改**，且操作者需具備該 Provider 的 Admin role。
5. 回 **LINE Developers Console**（developers.line.biz/console）做技術設定：webhook URL、channel access token、Channel secret。

### 1.2 Channel access token 四種類型

| 類型 | 有效期 | 數量上限/ch | 特點 |
|---|---|---|---|
| **v2.1 user-specified expiration（推薦）** | 自訂，最長 30 天 | 30 | 用 JWT 自助簽發；可搭配 IP allowlist |
| Stateless | 15 分鐘 | 無上限 | 每次請求前即時簽發；不可 revoke |
| Short-lived | 30 天 | 30 | 超額簽發時最舊的 token 自動被撤銷 |
| Long-lived | 永不過期 | 1（重發使舊 token 失效，可延長 24h） | Console 的 Messaging API 分頁直接簽發 |

要點：
- 四類型**計數各自獨立**；過期 token 不佔名額；同一張 token 在有效期內重複使用（不要每次請求都換發，會被暫時限速）。
- 建議：正式環境用 v2.1 + 排程在到期前自動換發；IP allowlist 在 Console 的 Security settings 設定。
- 懷疑外洩時立即 revoke（各類型都有對應 revoke endpoint）。

### 1.3 Webhook URL 設定

- 每個 channel 只有**一個 webhook URL**，必須 HTTPS 且憑證為公開可信 CA（**禁自簽憑證**）。
- Console → Messaging API 分頁 → Webhook URL → Edit → Update → **Verify**（送測試事件）→ 打開 **Use webhook** 開關（沒打開就不會收到任何事件）。
- 測試方式：Console 上有 QR code，手機掃碼加好友即可對話測試。
- Greeting（歡迎訊息）與 auto-reply（自動回應）**預設 Enabled**：若 bot 自己處理歡迎流程，建議兩者都 Disabled，改用程式攔截 `follow` event 回覆（更靈活、可帶 Flex 卡片）。

---

## 2. Push 免費額度、發送方式差異與超額費用

### 2.1 計費原則（官方 pricing 文件）

- **訊息數 = 收件人數，不是 message 物件數**：同一則廣播給 1,000 位好友＝1,000 則；一個 push 帶 5 個 message object 給 1 人＝1 則。
- 已封鎖 bot 或 userId 不存在的收件人**不計入**。
- **計入配額**：push / multicast / broadcast / narrowcast。**Reply API 完全免費**（不受額度限制）。
- 超量時 API 直接回錯誤且**不送出**（除非方案支援加購且有設定加購上限）。
- 查用量：`GET /v2/bot/message/quota`（方案類型+剩餘）、`GET /v2/bot/message/consumption`（當月總用量）。

### 2.2 台灣官方帳號方案（2023-09-01 生效，未稅）

來源：tw.linebiz.com 官方文章《2023年LINE官方帳號方案價格調整》。

| 方案 | 月費 | 免費訊息則數 | 加購 |
|---|---|---|---|
| 輕用量 | **NT$0** | **200 則** | — |
| 中用量 | NT$800 | 3,000 則 | **不可加購** |
| 高用量 | NT$1,200 | 6,000 則 | 每則 **NT$0.2 起**，階梯式累進計價 |

- 台灣計費訊息類型：**群發訊息（broadcast）、Messaging API Push API、漸進式訊息（narrowcast）**。
- 免費訊息：加入好友歡迎訊息、一對一手動聊天、自動回應、AI 自動回應、Reply API。
- 升級當月立即生效並補滿額度（收差額）；降級次月生效。
- 官網有費用計算機（輸入好友數＋每月群發次數即算出月費）。

### 2.3 五種發送方式比較

| 方式 | Endpoint | 對象 | 限制 | Rate limit | 配額 |
|---|---|---|---|---|---|
| Reply | `POST /v2/bot/message/reply` | webhook 事件的 replyToken | ≤5 msgs；token 有效期限短 | 2,000 req/s | **免費** |
| Push | `POST /v2/bot/message/push` | 單一 userId/groupId/roomId | ≤5 msgs | 2,000 req/s | 計費 |
| Multicast | `POST /v2/bot/message/multicast` | 指定多個 userId | **Max 500 user IDs/request**；≤5 msgs；支援 `X-Line-Retry-Key`（UUID 冪等重試） | 200 req/s | 計費（=人數） |
| Broadcast | `POST /v2/bot/message/broadcast` | **全部好友** | ≤5 msgs | 60 req/hr | 計費（=人數） |
| Narrowcast | `POST /v2/bot/message/narrowcast` | 分眾（非同步） | 最小收件人門檻；配送期間其他發送可能被擋 | 60 req/hr | 計費 |

其他共用參數：`notificationDisabled`（true＝不響通知音，適合深夜）、`customAggregationUnits`（自訂統計單位）。Narrowcast 可用 `recipient`（audience/redelivery）+ `filter.demographic`（性別/年齡/appType/地區/好友期間）+ `AND/OR/NOT` 巢狀運算子，進度查 `GET /v2/bot/message/progress/narrowcast?requestId=`；audience 必須 READY，部分受眾只能從 OA Manager/Ad Manager 建。

另有 `quoteToken`（引用過去訊息回覆，限 text/sticker，reply+push）與 loading 動畫 API（`chat.loading.start`）。

### 2.4 「低頻活動通知」夠不夠用？

- 計費以**收件人數**累計 → 輕用量 200 則/月的容量＝「好友數 × 廣播次數」≤ 200。
- 例：100 位好友 → 每月 2 次全體廣播；50 位好友 → 4 次。**對初期低頻精選通知（每週 1 次精選、好友 <200）免費方案足夠**。
- 成長策略：①只對「標記想收活動通知」的 userId 做 multicast/push（比全體廣播省）；②重要大檔活動才廣播；③好友破 200 後升中用量（NT$800）。
- 注意：multicast 一次 500 人、broadcast 60 次/hr 的限制對本場景都不構成瓶頸；瓶頸是**月配額**。

---

## 3. Flex Message carousel 活動卡片

### 3.1 結構

- 訊息物件：`{"type": "flex", "altText": "...", "contents": {bubble 或 carousel}}`。
- **bubble** 由四個 block 組成，各至多一次：`header` / `hero` / `body` / `footer`。
- **carousel**：`{"type": "carousel", "contents": [bubble, ...]}`，**Max 12 bubbles**，各 bubble 寬度必須相同，body 高度對齊最高的那張。
- 常用元件：box（vertical/horizontal/baseline，可用 flex 比例、spacing、margin）、text（`wrap:true` 換行、weight/color/size/maxLines）、image、button（style: primary/secondary/link，color 自訂）、separator、filler。

### 3.2 最佳做法

1. **圖片 ≤1MB**（避免顯示延遲），hero 用 `aspectRatio:"2:1"`~`"20:13"` + `aspectMode:"cover"` 裁切滿版。
2. **altText 必寫**：通知橫幅摺疊時只顯示 altText，寫「🔥5折！台北↔東京機票特賣」這類一行吸睛文案。
3. **折扣 % 視覺化**：header/body 用大字級（xxl）+ 高對比色（如 `#EB0F0F`）色塊呈現「5 折」「-63%」，比小字塞在文案裡醒目。
4. **倒數**：Flex 沒有動態元件，倒數是**純文字**（如「⏰倒數 3 天」）。做法：後端排程每天重新生成並 push 更新版的卡片；或只在 LIFF 頁面做真正的 JS 倒數。
5. **按鈕開活動頁**：footer button 用 `{"type":"uri","label":"查看詳情","uri":"https://..."}`（https 網址在手機上直接開瀏覽器/LIFF；也可用 LINE URL scheme）。
6. **carousel 張數 ≤12**；列表太長時拆多則訊息（一次 push 可帶 ≤5 個 message objects）或引導到 LIFF 完整清單頁。
7. 先用 **Flex Message Simulator**（developers.line.biz/flex-simulator）調版面再接 SDK，免燒配額。
8. 渲染隨裝置與 LINE 版本而異：video/maxWidth/maxHeight/lineSpacing 需 LINE 11.22+；deca/hecto/scaling 字級需 13.6+。

### 3.3 JSON 範例：活動 carousel（2 張卡示例）

```json
{
  "type": "flex",
  "altText": "🔥本週搶購活動精選：東京5折、首爾-63%",
  "contents": {
    "type": "carousel",
    "contents": [
      {
        "type": "bubble",
        "hero": {
          "type": "image",
          "url": "https://example.com/img/tokyo-sale.jpg",
          "size": "full",
          "aspectRatio": "2:1",
          "aspectMode": "cover"
        },
        "body": {
          "type": "box",
          "layout": "vertical",
          "spacing": "sm",
          "contents": [
            {
              "type": "box",
              "layout": "baseline",
              "justifyContent": "space-between",
              "contents": [
                { "type": "text", "text": "長榮 台北↔東京", "weight": "bold", "size": "lg", "flex": 0 },
                { "type": "text", "text": "-63%", "weight": "bold", "size": "xxl", "color": "#EB0F0F", "flex": 0 }
              ]
            },
            { "type": "text", "text": "來回未稅 $8,900 起（原價 $24,000）", "size": "sm", "color": "#555555" },
            { "type": "separator", "margin": "md" },
            {
              "type": "box",
              "layout": "horizontal",
              "margin": "md",
              "contents": [
                { "type": "text", "text": "⏰ 倒數 3 天", "size": "sm", "color": "#D95E00", "flex": 0 },
                { "type": "text", "text": "開賣 09-01 10:00", "size": "sm", "color": "#999999", "align": "end" }
              ]
            }
          ]
        },
        "footer": {
          "type": "box",
          "layout": "vertical",
          "spacing": "sm",
          "contents": [
            {
              "type": "button",
              "style": "primary",
              "color": "#17B900",
              "action": { "type": "uri", "label": "開活動頁", "uri": "https://example.com/deal/tokyo-0899" }
            },
            {
              "type": "button",
              "style": "link",
              "action": { "type": "postback", "label": "開賣前提醒我", "data": "action=remind&deal=tokyo-0899" }
            }
          ]
        }
      },
      {
        "type": "bubble",
        "hero": {
          "type": "image",
          "url": "https://example.com/img/seoul-sale.jpg",
          "size": "full",
          "aspectRatio": "2:1",
          "aspectMode": "cover"
        },
        "body": {
          "type": "box",
          "layout": "vertical",
          "spacing": "sm",
          "contents": [
            {
              "type": "box",
              "layout": "baseline",
              "justifyContent": "space-between",
              "contents": [
                { "type": "text", "text": "釜山航空 台北↔首爾", "weight": "bold", "size": "lg", "flex": 0 },
                { "type": "text", "text": "5 折", "weight": "bold", "size": "xxl", "color": "#EB0F0F", "flex": 0 }
              ]
            },
            { "type": "text", "text": "單程未稅 $2,200 起", "size": "sm", "color": "#555555" },
            { "type": "separator", "margin": "md" },
            {
              "type": "box",
              "layout": "horizontal",
              "margin": "md",
              "contents": [
                { "type": "text", "text": "⏰ 倒數 12 小時", "size": "sm", "color": "#D95E00", "flex": 0 },
                { "type": "text", "text": "結束 08-25 23:59", "size": "sm", "color": "#999999", "align": "end" }
              ]
            }
          ]
        },
        "footer": {
          "type": "box",
          "layout": "vertical",
          "spacing": "sm",
          "contents": [
            {
              "type": "button",
              "style": "primary",
              "color": "#17B900",
              "action": { "type": "uri", "label": "開活動頁", "uri": "https://example.com/deal/seoul-2200" }
            },
            {
              "type": "button",
              "style": "link",
              "action": { "type": "postback", "label": "開賣前提醒我", "data": "action=remind&deal=seoul-2200" }
            }
          ]
        }
      }
    ]
  }
}
```

> 「開賣前提醒我」按鈕走 postback → 後端記下 userId+活動 → 排程器在開賣前 15 分鐘用 push 送提醒（吃 1 則/人）。這就是第 4 節方案 (a) 的入口。

---

## 4. 提醒/日曆功能怎麼做最省事？

LINE **沒有原生行事曆**。四個候選方案：

| 方案 | 使用者體驗 | 開發成本 | 吃配額？ | 主要缺點 |
|---|---|---|---|---|
| **(a) 到點前 push 提醒** | ★★★★★ 零操作，通知直達 | 低：cron + multicast | 是（1 則/人/次） | 提醒時點由我方決定；量大時燒配額 |
| **(b) rich menu / LIFF 自製搶購日曆頁** | ★★★☆☆ 需主動點開 | 中：LIFF app + 後端 API | **否**（瀏覽不算訊息） | 不點不會看；要做 UI/資料介接 |
| **(c) 產生 .ics 讓用戶加入 Google Calendar** | ★★★☆☆ 加一次永久提醒 | 低：產生 .ics 檔/URL | 否 | 下載-開啟流程流失率高；iOS/Android 行為不一；活動異動要重抓 |
| **(d) Google Calendar API 代管** | ★★★★☆ 直接寫進用戶日曆 | **高**：Google OAuth consent 審查 + API 串接 | 否 | 需 Google 帳號授權；calendar.events 屬敏感範圍需 Google 驗證審核；隱私疑慮；維運成本最高 |

**優缺細節**：
- (a) 觸及率最高（LINE 通知開啟率遠高於 email/calendar），且提醒訊息可直接附「開活動頁」按鈕；代價是每人每次 1 則配額。適合「開賣前 15 分鐘」「結束前 1 小時」這種關鍵時點。
- (b) rich menu 是常駐入口（見 §7 rich menu 規格：圖片 2500×1686px、≤20 個熱區、每 OA 至多 1,000 個 rich menu + 1,000 個 alias、支援 tab 切換與點擊統計）。把第一格做成「📅搶購日曆」開 LIFF 日曆頁：內容隨時更新、可放完整清單+真 JS 倒數+收藏，完全不占訊息配額——是「瀏覽」需求的最佳解。
- (c) `.ics` 是零依賴的補充：活動卡 footer 多放一顆「加到行事曆」（Webcal/下載連結），使用者手機日曆就會準時跳提醒，**不經過 LINE、不吃配額**。適合願意自己管理提醒的重度用戶。
- (d) 除非產品定位就是行事曆工具，否則 OAuth 審查（Google security assessment 流程）+ 授權流失不值得。

**建議組合（省事優先）**：(a) 為主力（postback「提醒我」→ cron multicast）＋ (b) rich menu 第一格 LIFF 日曆頁當常駐瀏覽入口 ＋ 活動卡附 (c) .ics 連結。(d) 不做。

---

## 5. LINE Notify 停止服務與替代方案

- LINE Notify 於 **2025-03-31 終止服務**（2016-09 上線）；官方理由為資源集中至後繼產品，官方指定的一般替代品是 **LINE 官方帳號 + Messaging API**（每月一定量免費推播）。
- 台灣市場的後繼產品：**「LINE 通知型訊息（Notification Message）」**（tw.linebiz.com/service/account-solutions/line-notification-message/）：
  - 僅限**實用型通知**（帳單、到貨、預約提醒等），**禁止行銷/促銷內容**，內容需經 LINE 審核。
  - 可用**手機號碼**觸及好友＋非好友（封鎖者除外）——這是一般 Messaging API做不到的。
  - NT$0.2/則（對照簡訊 0.8~2 元）；僅限**認證（藍盾）/企業（綠盾）**官方帳號。
  - 需自建後台串接，或透過合作夥伴（漸強 Cresclab、Omnichat、直通國際、台北數位廣告、翔評互動、91APP、酷必、inline 等）。
- **對本專案的結論**：活動促銷通知**不能**用「通知型訊息」（禁行銷），必須走一般 Messaging API push/broadcast。若只是爬蟲跑完想通知自己（原 Notify 用法）：申請一個免費輕用量 OA + Messaging API，用自己的 userId multicast 一則文字即可，完全免費。

---

## 6. Webhook 回應 vs 主動推播架構；加好友誘導

### 6.1 架構差異

```
[被動/Webhook]  使用者動作 ──> LINE 平台 ──POST──> 你的 HTTPS endpoint
                 （follow/postback/message…）        ├─ 驗 x-line-signature
                                                    ├─ 快速回 200（重活在背景非同步做）
                                                    └─ 需要回話時用 Reply API（免費）

[主動/Push]     你的排程器(cron) ──判斷時刻──> Push/Multicast/Broadcast API ──> 使用者
                 （需要先存好 userId；吃月配額）
```

- Webhook 事件類型：message、edit(群)、unsend、follow、unfollow、join、leave、memberJoined/memberLeft、postback、videoPlayComplete、beacon、accountLink。
- **必須驗證 `x-line-signature`**＝base64(HMAC-SHA256(channelSecret, rawRequestBody))；驗不過一律拒絕（防偽造請求）。
- 收到事件**先回 200 再非同步處理**；伺服器長期失敗會被 LINE **暫停 webhook 推送**。
- Redelivery 預設關閉（Console 可開）：僅對非 2xx 回應重試；用 `webhookEventId` 去重、`timestamp` 排序保序。
- 多媒體內容下載：`GET https://api-data.line.me/v2/bot/message/{messageId}/content[/preview]`；取使用者 profile：`GET /v2/bot/profile/{userId}`。
- 注意：`liff.sendMessages()` 送出的訊息**不觸發 webhook**。
- **本專案的分工**：webhook 只負責 `follow`（存 userId、送活動清單 Flex 歡迎訊息）＋`postback`（「提醒我」訂閱、rich menu 按鈕）；其餘全部排程主動推送。

### 6.2 加好友誘導管道（官方 sharing-bot 文件）

| 管道 | 用法 |
|---|---|
| QR code | Developers Console 或 OA Manager「加入好友工具」產生（可複製 HTML snippet 嵌網站） |
| LINE ID | @開頭 ID 讓用戶搜尋 |
| Add Friend 按鈕 | LINE Social Plugins 或 Manager 產生的 HTML 按鈕（可顯示好友數） |
| URL scheme 加好友 | `https://line.me/R/ti/p/{percent-encoded LINE ID}`（@→%40，例 `@mybot`→`%40mybot`）；PC 端顯示商業檔案頁或 QR code |
| 推薦分享 | `https://line.me/R/nv/recommendOA/{id}`（開「傳送到聊天」分享畫面） |
| 帶字開聊天 | `https://line.me/R/oaMessage/{id}/?{text}`（預填訊息） |
| 分享文字 | `https://line.me/R/share?text={text}` |
| LINE Login 綁定 | login channel 設 `bot_prompt=normal`（同意畫面內含加好友選項）/`aggressive`(登入後另開加好友頁) |
| Bot 內誘導 | follow event 送「活動清單」Flex 歡迎訊息 + 引導查看 rich menu；rich menu 第一格常駐「📅搶購日曆」 |

---

## 7. 開發工具現況

| 工具 | 現況 |
|---|---|
| **LINE Official Account Manager**（manager.line.biz） | OA 營運後台：greeting/auto-reply、rich menu GUI（模板式設定熱區）、加入好友工具、一對一聊天、統計。啟用 Messaging API 也在此操作 |
| **LINE Developers Console**（developers.line.biz/console） | channel 管理、webhook URL/Verify、token 簽發/revoke、Channel secret、IP allowlist、QR code 測試 |
| **Flex Message Simulator**（developers.line.biz/flex-simulator） | 免發送即時預覽 Flex、匯出 JSON；官方文件有 step-by-step 教學 |
| **SDK 官方支援** | Java / PHP / Python / Node.js / Go / Ruby（Perl 已 archive 停更）；github.com/line/line-openapi 提供 OpenAPI spec 可自行 codegen 其他語言 |
| **line-bot-sdk-python** | 現役維護中（archived=false；最近 push 2026-08-21；★2131；Apache-2.0）；v3 支援 async |
| **line-bot-sdk-nodejs** | 現役維護中（archived=false；最近 push 2026-08-21；★1079） |

**Rich menu 補充規格**（供 LIFF/rich menu 實作）：圖片寬 800–2500px、高 ≥250px、寬高比 ≥1.45（常用 2500×1686）、檔案 ≤1MB、**熱區 max 20**、每 OA 至多 1,000 個 rich menu ＋1,000 個 rich menu alias；API 版支援 postback/datetime picker action、tab 切換（switch between tabs）、曝光/點擊統計；預設 rich menu 可由 Manager GUI 或 API 設定，per-user rich menu 顯示優先於預設；變更在使用者重開聊天室時生效（最慢約 1 分鐘）；非好友打開聊天室也看得到預設 rich menu。Rate limit：建立/刪除 100/hr、批次連結 3/hr。

---

## 8. 參考連結

**官方文件（developers.line.biz/en/docs/messaging-api/）**
- Getting started／Channel 建立：https://developers.line.biz/en/docs/messaging-api/getting-started/
- Building a bot／token & webhook：https://developers.line.biz/en/docs/messaging-api/building-a-bot/
- 定價：https://developers.line.biz/en/docs/messaging-api/pricing/
- 發送訊息（reply/push/multicast/broadcast/narrowcast）：https://developers.line.biz/en/docs/messaging-api/sending-messages/
- API Reference（endpoint/rate limit 全表）：https://developers.line.biz/en/reference/messaging-api/
- 訊息類型：https://developers.line.biz/en/docs/messaging-api/message-types/
- Flex Message：https://developers.line.biz/en/docs/messaging-api/using-flex-messages/
- Flex 元素規格：https://developers.line.biz/en/docs/messaging-api/flex-message-elements/
- Flex Simulator 教學：https://developers.line.biz/en/docs/messaging-api/flex-message-simulator/
- Rich menu 總覽／使用：https://developers.line.biz/en/docs/messaging-api/rich-menus-overview/ 、 https://developers.line.biz/en/docs/messaging-api/using-rich-menus/
- 收取訊息（webhook）：https://developers.line.biz/en/docs/messaging-api/receiving-messages/
- 簽章驗證：https://developers.line.biz/en/docs/messaging-api/verify-webhook-signature/
- Channel access token：https://developers.line.biz/en/docs/basics/channel-access-token/
- 加好友推廣：https://developers.line.biz/en/docs/messaging-api/gaining-friends/
- LINE URL scheme：https://developers.line.biz/en/docs/messaging-api/using-line-url-scheme/
- LINE Login 加好友選項：https://developers.line.biz/en/docs/line-login/link-a-bot/

**台灣官方（tw.linebiz.com）**
- 2023 方案調整公告：https://tw.linebiz.com/column/LINEOA-2023-Price-Plan/
- LINE 通知型訊息：https://tw.linebiz.com/service/account-solutions/line-notification-message/
- LINE Notify 終止說明：https://notify-bot.line.me/

**GitHub**
- Python SDK：https://github.com/line/line-bot-sdk-python
- Node.js SDK：https://github.com/line/line-bot-sdk-nodejs
- OpenAPI spec：https://github.com/line/line-openapi
