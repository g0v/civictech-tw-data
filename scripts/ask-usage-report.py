#!/usr/bin/env python3
"""
黑客松鼠（civictech.tw 右下角的問答機器人）用量快照 —— 從 Cloudflare GraphQL Analytics 抓 AI Search 查詢次數。

為什麼要看：AI Search 2026-12-01 起計費。每個帳號每月含 1,000 次語意查詢，
**超過不會被擋，而是照量收錢**（$0.75／1,000 次），也沒有花費上限可以設。
所以「松鼠累了」那句 429 訊息大概永遠不會出現，唯一看得到用量的地方就是這裡。

座標（2026-11-23 實測）：
  - 資料集 aiSearchSemanticQueriesAdaptiveGroups／aiSearchFulltextQueriesAdaptiveGroups，
    官方文件沒寫，是從 GraphQL schema 撈到的。
  - 松鼠用 hybrid 檢索，**一題只算一次語意查詢**，全文查詢那邊是 0（送一題實測）。
  - dimensions.tier 會標 free 或其他值。非 free 的就是被收錢的那部分。
  - 數的是**整個帳號**，不分實例：額度與帳單都是帳號層級，現在也只有松鼠在用。

保留期只有約 32 天（查更早會回 "cannot request data older than 4w4d"），
所以查詢起點最早只到 31 天前；更早的日子沿用上一份快照——這也是要存檔的原因。

月份照 Cloudflare 的 UTC 日期切，跟帳單同一個口徑。
每次跑都重抓這個月與上個月（月初那幾天上個月才會補齊），每個月一個檔，重跑會覆寫。
跟上一份對帳時，每天取兩邊的較大值：過去的日子次數只會變多，變少就是這次沒抓完整。

用法：
  CLOUDFLARE_ANALYTICS_TOKEN=... CLOUDFLARE_ACCOUNT_ID=... python3 scripts/ask-usage-report.py [--out-dir reports]
"""
import argparse, calendar, json, os, sys, urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

GQL = "https://api.cloudflare.com/client/v4/graphql"
INCLUDED_SEMANTIC = 1000          # 每月含的語意查詢
PRICE_PER_1K_SEMANTIC = 0.75      # 美元；見 developers.cloudflare.com/ai-search/platform/limits-pricing/

Q = """query($acc:String!,$s:Date!,$e:Date!){viewer{accounts(filter:{accountTag:$acc}){
 sem: aiSearchSemanticQueriesAdaptiveGroups(limit:5000,filter:{date_geq:$s,date_leq:$e}){count dimensions{date tier}}
 ft: aiSearchFulltextQueriesAdaptiveGroups(limit:5000,filter:{date_geq:$s,date_leq:$e}){count dimensions{date tier}}
}}}"""

def gq(token, acc, start, end):
    req = urllib.request.Request(
        GQL, data=json.dumps({"query": Q, "variables": {"acc": acc, "s": start, "e": end}}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    d = json.load(urllib.request.urlopen(req, timeout=60))
    if d.get("errors"):
        raise RuntimeError("; ".join(e.get("message", "") for e in d["errors"]))
    accts = d["data"]["viewer"]["accounts"]
    if not accts:
        # 帳號 ID 錯或 token 看不到這個帳號時，GraphQL 回空陣列而不是錯誤——那不是「沒人問」
        raise RuntimeError("查不到這個帳號，檢查 CLOUDFLARE_ACCOUNT_ID 與 token 權限")
    return accts[0]

def prev_month(m):
    y, mo = int(m[:4]), int(m[5:7])
    return f"{y - 1}-12" if mo == 1 else f"{y}-{mo - 1:02d}"

def month_end(m):
    y, mo = int(m[:4]), int(m[5:7])
    return f"{m}-{calendar.monthrange(y, mo)[1]:02d}"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="reports")
    args = ap.parse_args()
    token = os.environ.get("CLOUDFLARE_ANALYTICS_TOKEN")
    acc = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    if not token or not acc:
        sys.exit("缺少 CLOUDFLARE_ANALYTICS_TOKEN 或 CLOUDFLARE_ACCOUNT_ID")

    now = datetime.now(timezone.utc)
    this_m = now.strftime("%Y-%m")
    os.makedirs(args.out_dir, exist_ok=True)

    earliest = (now - timedelta(days=31)).date().isoformat()
    for m in (prev_month(this_m), this_m):
        start, end = max(f"{m}-01", earliest), month_end(m)
        if start > end:
            continue                      # 整個月都過了保留期，留著舊檔不動
        a = gq(token, acc, start, end)
        days = defaultdict(lambda: {"semantic": 0, "fulltext": 0, "semantic_billed": 0})
        for key, rows in (("semantic", a["sem"]), ("fulltext", a["ft"])):
            for r in rows:
                d = days[r["dimensions"]["date"]]
                d[key] += r["count"]
                if key == "semantic" and r["dimensions"].get("tier") not in (None, "", "free"):
                    d["semantic_billed"] += r["count"]

        path = os.path.join(args.out_dir, f"ask-usage-{m}.json")
        prev = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                prev = json.load(f).get("by_date", {})
        if not days and not prev:
            continue                      # 這個月還沒人問過，也沒有舊檔：不產空檔
        for date, v in prev.items():
            cur = days[date]
            for k in cur:
                cur[k] = max(cur[k], v.get(k, 0))

        by_date = {k: days[k] for k in sorted(days)}
        sem = sum(v["semantic"] for v in by_date.values())
        billed = sum(v["semantic_billed"] for v in by_date.values())
        out = {
            "generated_at": now.isoformat(timespec="seconds"),
            "month": m,
            "scope": "整個 Cloudflare 帳號（目前只有黑客松鼠用 AI Search）",
            "included_semantic": INCLUDED_SEMANTIC,
            "semantic_total": sem,
            "fulltext_total": sum(v["fulltext"] for v in by_date.values()),
            # tier 標成非 free 的才算被收錢；12/1 之前全部是 free
            "semantic_billed": billed,
            "estimated_cost_usd": round(billed / 1000 * PRICE_PER_1K_SEMANTIC, 2),
            "by_date": by_date,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"✅ {path}：語意查詢 {sem} 次（計費 {billed} 次）", file=sys.stderr)

if __name__ == "__main__":
    main()
