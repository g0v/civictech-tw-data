# civictech.tw 資料庫連結健檢（2026-09-19）

掃過資料庫裡 199 個專案的 307 個網址（`Website URL`／`github`／`document`／`Facebook Page Link`）。
純 HTTP 檢查，沒有用 AI，所以不會有幻覺。

| 分類 | 數量 | 意思 |
|---|---|---|
| 打得開 | 238 | — |
| 轉址 | 9 | 最後打得開，但落在不同網域，要確認是搬家還是被接手 |
| 死掉 | 20 | 4xx／5xx |
| 連不上 | 15 | 網域查不到、逾時、憑證過舊 |
| 擋機器 | 3 | 站台擋自動檢查，**不代表壞掉**，要人工開一次 |
| 無法判定 | 22 | Facebook。它對機器回登入牆，狀態碼 200 不代表粉專還在 |

## 讀這份報告前要知道的兩件事

1. **403 不是死掉。** Cofacts 官網回 403，但它的 repo 三天前還在 push。把「擋我」當成「死了」，會叫人去修沒有壞的東西。
2. **Facebook 一律無法判定。** 22 個 FB 連結全部落在這一格——不是好消息也不是壞消息，是這個方法看不到。

## 一、14 個專案「一個能打開的連結都沒有」

這些是站上最該處理的——使用者點進專案頁，每一條路都是死的。

- **Twinkle Hub _台灣資料的 MCP Hub**
  - `Website URL` https://hub.twinkleai.tw/ — SSLError: [SSL: TLSV1_ALERT_PROTOCOL_VERSION] tlsv1 alert protocol version (_ssl.c:1129)
- **Vaxx.tw**
  - `Website URL` https://vaxx.tw/ — HTTP 404
- **《我們想這樣生小孩！陪伴孕產旅程的行動手冊》**
  - `Website URL` https://www.facebook.com/share/p/1EZYQNjdRU/ — Facebook 對機器回登入牆，狀態碼不能當作還活著
- **你被服貿了嗎?**
  - `Website URL` http://tisa.g0v.tw/ — timeout: timed out
- **八仙塵爆資訊整合 hackfoldr**
  - `document` http://beta.hackfoldr.org/627pray/ — HTTP 404
- **台電睦鄰金流大解析**
  - `Website URL` https://opentaipower.g0v.tw/ — HTTP 522
- **無家者小幫手**
  - `Website URL` https://homeless-helper.doyouaflavor.tw/ — gaierror: [Errno 8] nodename nor servname provided, or not known
- **福利請聽**
  - `Website URL` http://listening.g0v.tw/ — HTTP 404
  - `Facebook Page Link` https://www.facebook.com/Listening-%E7%A6%8F%E5%88%A9%E8%AB%8B%E8%81%BD-173478432803859/ — Facebook 對機器回登入牆，狀態碼不能當作還活著
- **立委咖電喂**
  - `Website URL` http://call.ly.g0v.tw/ — gaierror: [Errno 8] nodename nor servname provided, or not known
  - `document` http://beta.hackfoldr.org/callliwei — HTTP 404
- **美國國會台灣觀測站**
  - `Website URL` https://www.uswatch.tw/ — gaierror: [Errno 8] nodename nor servname provided, or not known
  - `Facebook Page Link` https://www.facebook.com/ustaiwanwatch/ — Facebook 對機器回登入牆，狀態碼不能當作還活著
- **臺灣黑熊通報與資訊平台**
  - `document` https://hackmd.io/@tai271828/rJq_CxbgY — HTTP 403：站台擋自動檢查，不代表壞掉，要人工開一次
- **賽豬公上太空**
  - `Website URL` http://nspo.g0v.tw/ — timeout: timed out
- **農業災損幾多錢**
  - `Website URL` http://uav-fly.nchu.edu.tw/g0vAna/ — HTTP 404
- **高雄氣爆**
  - `document` https://beta.hackfoldr.org/Kaohsiung-explode-20140801/ — HTTP 404

## 二、20 個專案部分連結壞掉

- **Cofacts 真的假的**：`document` HTTP 404
- **IDystopia 2035 數位身份大冒險**：`Website URL` gaierror: [Errno 8] nodename nor servname provided, or not known
- **g0v 零時空汙觀測網**：`Website URL` HTTP 404；`document` HTTP 404
- **shared-tw**：`Website URL` SSLCertVerificationError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self signed certificate (_ssl.c:1129)
- **享食台灣**：`Website URL` gaierror: [Errno 8] nodename nor servname provided, or not known
- **公有地大行動 / 天龍特公地**：`Website URL` HTTP 404
- **司法陽光網－判決書API計畫**：`Website URL` timeout: timed out
- **寵物需要我**：`Website URL` gaierror: [Errno 8] nodename nor servname provided, or not known
- **專為高中生設計的管家型聊天機器人**：`Website URL` ConnectionRefusedError: [Errno 61] Connection refused
- **島島阿學**：`Website URL` gaierror: [Errno 8] nodename nor servname provided, or not known
- **新聞小幫手**：`Website URL` HTTP 500
- **父母救星 大營家 優質營隊月曆**：`Website URL` gaierror: [Errno 8] nodename nor servname provided, or not known
- **立委投票指南**：`Website URL` timeout: timed out；`document` HTTP 404
- **群眾標註地圖工具**：`Website URL` HTTP 502
- **臺灣好植地 Patch by Planting**：`document` HTTP 404
- **萌典**：`document` HTTP 404
- **資料申請小幫手**：`Website URL` HTTP 525
- **選前大補帖**：`Website URL` HTTP 404
- **阿美語萌典**：`document` HTTP 404
- **面海松**：`document` HTTP 404

## 三、9 個轉去了別的網域

實際看過，**沒有發現網域被搶註**，多數是正常搬家。列出來是因為資料庫該更新成新網址：

- **阿龜微氣候**：https://agriweather.beehivedt.com/ → https://www.agriweather.com.tw/
- **秒懂災害潛勢**：http://bit.ly/2PmxklI → https://sheet2site.com/api/v3/index.php?key=1U2d2EiK1GLH7SaMo2VXvRYwnrO2CJZMMbpYaxslF-WI
- **awesome-g0v-projects**：https://chunyenhuang.github.io/awesome-g0v-projects/ → https://awesome.g0v.tw/
- **遠距心理諮詢資訊彙整**：http://bit.ly/g0vpsymap → https://sheet2site.com/api/v3/index.php?key=1R-81yYOJpvZ1oitlF4QbYdjQM9kqk9FREEoqjAko09Q
- **吉祥物資料蒐集**：http://bit.ly/2GkInGT → https://sheet2site.com/api/v3/index.php?key=1WW5QYjIowWf5g3h8s1PPnwB2olaa_rfA6HVdJjg4JEw
- **地方淨零觀測站**：https://carbon-map-ten.vercel.app/ → https://localnetzero.gcaa.org.tw/
- **藥品仿單白話文運動**：https://lin.ee/ucbMS6N → https://line.me/R/ti/p/@816cfprg?ts=04121512&oat_content=url
- **iCanHelp 應變地圖_災情通報_志工報名**：https://app.icanhelp.tw → https://www.forward.org.tw/tw/a/resources/app
- **法律偵探 - 免費 AI 法律諮詢**：https://dr-lawbot.com/ → https://dr-legal.com.tw/

## 四、hackfoldr 是一個系統性問題，不是七個獨立的壞連結

`beta.hackfoldr.org` 服務本身還活著（首頁 200），但底下每一個專案資料夾都回 404——
cofacts、g0vairmap、tree、voter_guide_tw、callliwei、627pray、Kaohsiung-explode，
連 `beta.hackfoldr.org/g0v` 也是。**先問 hackfoldr 的維護者發生了什麼事，再決定這些連結怎麼辦**，一個一個修會修錯方向。

## 這份東西可以怎麼用

1. **站上先別說謊**：專案頁對這些連結標「最後檢查日期 × 打不開」，比直接拿掉好——拿掉等於假裝沒這回事。
2. **回寫資料庫**：Airtable 沒有狀態欄，這份掃描可以當它的第一版（8/4 會議問過「有沒有運作中／無運作的分類」）。
3. **定期重跑**：腳本沒有相依套件，掃一次約三分鐘。連結不會通知你它死了。