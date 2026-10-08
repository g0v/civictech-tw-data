# civictech-tw-data

台灣公民科技資料庫（[civictech.tw](https://civictech.tw)）的開放資料出口。每日從 Airtable 匯出成靜態 JSON，提供公開、免 token、免 rate limit 的唯讀取用。

Open data export for the Taiwan Civic Tech Database ([civictech.tw](https://civictech.tw)). Synced daily from Airtable into static JSON — publicly readable, no token, no rate limit.

**授權 License**：資料 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.zh-hant)（姓名標示「g0v civictech.tw」）／程式碼 [MIT](LICENSE)

---

## 端點 Endpoints

```
https://data.civictech.tw/index.json          ← 先讀這個，它列出全部
https://data.civictech.tw/v0/{資料集}/{表}.json
```

### 公民科技專案 `/v0/tech/`

| 端點 | 內容 | 筆數 |
|---|---|---|
| [`/v0/tech/projects.json`](https://data.civictech.tw/v0/tech/projects.json) | 公民科技專案 | 219 |
| [`/v0/tech/categories.json`](https://data.civictech.tw/v0/tech/categories.json) | 影響力類別（SDGs） | 20 |
| [`/v0/tech/tags.json`](https://data.civictech.tw/v0/tech/tags.json) | 標籤 | 58 |
| [`/v0/tech/talks.json`](https://data.civictech.tw/v0/tech/talks.json) | 專案發表紀錄 | 666 |

### 公民科學與群眾參與計畫 `/v0/science/`

| 端點 | 內容 | 筆數 |
|---|---|---|
| [`/v0/science/programs.json`](https://data.civictech.tw/v0/science/programs.json) | 公民科學與群眾參與計畫 | 352 |
| [`/v0/science/papers.json`](https://data.civictech.tw/v0/science/papers.json) | 文獻、研究成果、文章 | 271 |
| [`/v0/science/orgs.json`](https://data.civictech.tw/v0/science/orgs.json) | 機構與單位 | 3105 |
| [`/v0/science/categories.json`](https://data.civictech.tw/v0/science/categories.json) | 類別 | 575 |
| [`/v0/science/districts.json`](https://data.civictech.tw/v0/science/districts.json) | 行政區 | 465 |
| [`/v0/science/platforms.json`](https://data.civictech.tw/v0/science/platforms.json) | 數據資料彙整方案或平台 | 200 |
| [`/v0/science/equipment.json`](https://data.civictech.tw/v0/science/equipment.json) | 設備器材 | 180 |
| [`/v0/science/seasons.json`](https://data.civictech.tw/v0/science/seasons.json) | 計畫執行的時段或時節 | 107 |
| [`/v0/science/counties.json`](https://data.civictech.tw/v0/science/counties.json) | 縣市 | 48 |
| [`/v0/science/rewards.json`](https://data.civictech.tw/v0/science/rewards.json) | 禮品與獎勵 | 28 |
| [`/v0/science/material-types.json`](https://data.civictech.tw/v0/science/material-types.json) | 文獻或知識素材類型 | 17 |
| [`/v0/science/regions.json`](https://data.civictech.tw/v0/science/regions.json) | 國際地區 | 16 |
| [`/v0/science/methods.json`](https://data.civictech.tw/v0/science/methods.json) | 演算或分析方案 | 9 |
| [`/v0/science/ccu-topics.json`](https://data.civictech.tw/v0/science/ccu-topics.json) | 中正社區大學學群主題 | 6 |

### AI Monday 講題紀錄 `/v0/aimonday/`

| 端點 | 內容 | 筆數 |
|---|---|---|
| [`/v0/aimonday/events.json`](https://data.civictech.tw/v0/aimonday/events.json) | 場次（AI Monday、g0v 國會松、COSCUP 的 AI 相關議程） | 26 |
| [`/v0/aimonday/talks.json`](https://data.civictech.tw/v0/aimonday/talks.json) | 講題（含講者、影片、授權） | 72 |

來源是揪松團維護的 Google Sheet，不是 Airtable，所以**格式和上面兩個資料集不同**：沒有 `fields` 包一層，欄位已經整理成固定的形狀（見下方「aimonday 的欄位」）。

筆數以 [`index.json`](data/index.json) 為準，本表可能落後。

## 馬上試 Quick start

```bash
# 全部的公民科技專案
curl -s https://data.civictech.tw/v0/tech/projects.json | jq '.records[].fields["project name"]'

# 只要「開放資料與開源社群基礎建設」這一類的
curl -s https://data.civictech.tw/v0/tech/projects.json \
  | jq -r '.records[] | select(.fields["影響力類別"][]?.name | test("開放資料")) | .fields["project name"]'
```

```js
const res = await fetch('https://data.civictech.tw/v0/tech/projects.json');
const { records } = await res.json();
console.log(records.length);
```

CORS 全開（`Access-Control-Allow-Origin: *`），瀏覽器可直接 fetch。

## 回應格式 Response shape

```jsonc
{
  "version": "v0",
  "dataset": { "slug": "tech", "name": "…", "label": "公民科技專案資料庫" },
  "table":   { "slug": "projects", "name": "project list", "label": "公民科技專案", "id": "tbl…" },
  "recordCount": 219,
  "fields":  [ { "id": "fld…", "name": "project name", "type": "singleLineText" } ],
  "records": [
    {
      "id": "recXXX",
      "createdTime": "2021-…",
      "fields": {
        "project name": "Cofacts 真的假的",
        "影響力類別": [ { "id": "recYYY", "name": "19-新聞訊息與媒體識讀" } ]
      }
    }
  ]
}
```

- **關聯欄位已展開**為 `{ id, name }`，不必再查一次表。
- **欄位是稀疏的**：Airtable 空欄位不會出現在 `fields` 裡，讀取時一律當可能不存在。
- **檔內不含匯出時間戳**（無變動時重跑不產生 diff）。**最後更新時間以 git commit 歷史為準。**

### aimonday 的欄位

```jsonc
// events.json 的一筆
{
  "id": "2026-10-05-ai-monday",          // 日期＋系列，穩定
  "date": "2026-10-05", "weekday": "一",
  "series": "AI Monday", "series_slug": "ai-monday",
  "theme": "地端模型主題場",
  "status": "已完成",                     // 已完成／已排定／邀約中／停辦
  "start_time": "20:00", "end_time": "21:30", // 台灣時間；已完成／已排定應該要有（漏填會發警告），其他狀態可能是 null
  "format": "線上", "venue": null,
  "notes_url": null, "sponsor": "聯發科技開放資料社",
  "promotions": [ { "text": "…", "urls": ["https://…"] } ],
  "talk_ids": ["2026-10-05-ai-monday-1", "2026-10-05-ai-monday-2"]
}

// talks.json 的一筆
{
  "id": "2026-07-25-congressthon-3",     // 場次 id＋上台順序。⚠️ Sheet 裡調換順序，id 會跟著變
  "event_id": "2026-07-25-congressthon", "order": 3,
  "kind": "talk",                         // talk／qa
  "title": "…", "description": null,
  "speakers": [ { "name": "簡毅慧", "affiliation": "《報導者》數據記者、AI 專案經理", "url": null } ],
  "open_slot": false,                     // true＝還在邀約的空位
  "duration_min": 20, "slides_url": null,
  "video": { "url": "https://www.youtube.com/watch?v=6zh7_ROJQ4c&t=2357s", "youtube_id": "6zh7_ROJQ4c", "start_sec": 2357 },
  "keywords": [],
  "license": "CC-BY-ND",                  // 影片授權
  "license_status": "confirmed"           // confirmed／pending／unknown；沒有影片時為 null
}
```

- 欄位**不是稀疏的**：沒有值就是 `null` 或 `[]`，不會省略。
- Sheet 的「線上會議網址」「備註」兩欄不匯出。
- Sheet 填寫格式不合規的地方列在 [`/v0/aimonday/report.json`](https://data.civictech.tw/v0/aimonday/report.json)（疑似個資已遮蔽），[AI-Monday](https://github.com/g0v/AI-Monday) 的每日建置會讀它、開 issue 通知維護者。未遮蔽的完整版在 `reports/aimonday.json`（不對外發布）。

## 為什麼路徑長這樣

| | |
|---|---|
| `v0` | Airtable 欄位改名是常態，schema 現在**給不起穩定承諾**。`v0` 是約定俗成的「這還會變」訊號，比假裝 `v1` 誠實。破壞性變更會開 `v1`，`v0` 保留一段時間。 |
| `tech` / `science` | 這是兩份資料集**真正的差別**，不是 Airtable 的 base 名稱。不把內部結構洩漏成公開介面。 |
| ASCII slug | 中文表名留在 `index.json` 當標籤——**機器讀路徑，人讀 index**。原本的中文檔名 16/18 個需要 URL 編碼，貼進文件會斷、也唸不出來。 |

## 不在匯出範圍 Not exported

- **內部工作表**：`[工作文件]`、`【工作區】`，以及 Airtable 預開的 `[空白N]` 範本表（依型樣排除，其 `Assignee` 是 collaborator 欄位，會帶出人名與 email）。
- **完全沒有內容的表**（依內容判斷，不依名字）。
- **空白列**：Airtable 預開的空列不匯出。原本 `project list` 898 筆裡有 686 筆是空的，會讓人誤以為有 898 個專案。「空」是指扣掉 Airtable 自動計算的欄位（count、formula、rollup 等）之後，剩下的欄位都沒值、只有空白字元，或只有 `[空白列]` 這種佔位字。`science/orgs` 原本 3105 筆裡有 3036 筆是 `[空白列]`。
- **個人聯絡欄位**：見 `scripts/sync.mjs` 的 `EXCLUDE_FIELDS`。
- 另有**內容層的個資掃描**：匯出時會掃所有自由文字欄位裡的 email 與電話，掃到未經檢視的就**讓匯出失敗**。理由是 `EXCLUDE_FIELDS` 是依欄位名的黑名單，而真正的個資往往躲在「描述」這種自由文字裡，欄位名比對結構上抓不到。已人工檢視、確認是專案自己對外公告的聯絡管道者，列在 `PII_REVIEWED` 放行。

**發現個資外流請開 issue 或直接聯繫**，我們會盡快移除。

## 更新方式 Update

`scripts/sync.mjs` 每天執行一次（台灣時間 04:00）。它結尾會接著跑 `scripts/sync-aimonday.mjs`（Google Sheet，免 token），最後用 `scripts/build-index.mjs` 依 `data/v0/` 實際有的檔案重建 `index.json`。

各資料集**只清自己的目錄**。aimonday 同步失敗時，`/v0/aimonday/` 停在上一版，不影響 Airtable 那兩個資料集的更新；失敗原因寫在 `reports/aimonday.json`。

目前由維護者的 VPS 以 cron 執行（`0 4 * * *`）：拉最新 `main` → 跑上述三支腳本 → 有變動才 commit 並推回 → 部署到 Cloudflare Pages（`data.civictech.tw`）→ 對帳（確認最新部署成功、正式站讀得到資料）。連續 48 小時沒有成功同步會發告警給維護者。每次執行的結果寫在 `data/status.html`。

> ⚠️ `.github/workflows/sync.yml` 是舊的排程，**目前不會觸發**（原 GitHub 帳號 2026-09-01 停權）。請勿同時啟用兩邊，否則會互相覆蓋 commit。

## 本地開發 Local development

需 Node.js 22+。Airtable Personal Access Token 只需唯讀 scope（`data.records:read` + `schema.bases:read`），放在 `.env`（見 `.env.example`，已 gitignore）：

```bash
export $(grep -v '^#' .env | xargs) && node scripts/sync.mjs
```

匯出會在下列情況**直接失敗**，不會安靜跳過：

- Airtable 新增了有內容的表，但 `scripts/sync.mjs` 的 `DATASETS` 沒有對應 slug
- `DATASETS` 裡有 Airtable 已經沒有的表
- 掃到未經檢視的個人聯絡資料

前兩者是刻意的：白名單會**兩個方向靜默失效**（表加了沒補進來就靜靜不匯出，表刪了沒拿掉就留一個空端點），而靜默失效正是這個專案踩過的坑。

## 相關 Related

- [civictech.tw](https://civictech.tw) — 前端網站 frontend
- 資料維護於 Airtable，由 [g0v jothon](https://jothon.g0v.tw) 主導。Data is maintained in Airtable, led by g0v jothon.
