#!/usr/bin/env python3
"""
civictech.tw 流量快照 —— 從 Cloudflare Web Analytics 抓下來，存成檔案。

為什麼要存檔：Cloudflare 免費版的 RUM 資料**只保留約半年**，過期就永久消失。
2026-09-20 發現時，最早的資料已經只剩 2026-04 左右——而網站是 2026-06 改版的，
再晚幾個月，「改版前的基準線」就沒有了，之後拿不出任何趨勢。

兩個座標陷阱（踩過，寫下來免得再踩）：
  1. 頁面上 `data-cf-beacon` 裡的 token **不是 GraphQL 要的 siteTag**。
     拿它查會得到 0 筆，而且不會報錯——看起來像「這個站沒有流量」。
     正確做法是先用 rumPageloadEventsAdaptiveGroups 不帶 siteTag 過濾，
     問出這個帳號底下有哪些站台在出資料。
  2. 同一個網域可能有**多個 siteTag 接力**（civictech.tw 就有兩個：
     b33b2857 收到 2026-08-27，ed3980ea 從 08-22 開始）。
     兩個站台各自計數、不會重複，按「日期+站台」分開記再加總。

API 限制：單次查詢跨度最多 93 天；更早的資料會回 "cannot request data older than"。
所以往回一段一段走，撞到保留邊界就停。

用法：
  CLOUDFLARE_ANALYTICS_TOKEN=... python3 scripts/traffic-report.py [--out-dir reports]
"""
import argparse, glob, json, os, sys, urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

ACCOUNT = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")  # 不寫死在公開 repo；每日同步的腳本會帶這個環境變數
HOST = "civictech.tw"
GQL = "https://api.cloudflare.com/client/v4/graphql"
CHUNK_DAYS = 90            # 低於 93 的上限，留點餘裕
MAX_CHUNKS = 12            # 最多往回三年，撞到保留邊界會自己停

def iso(d): return d.strftime("%Y-%m-%dT%H:%M:%SZ")

class Retention(Exception): pass

def gq(token, query, variables):
    req = urllib.request.Request(
        GQL, data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    d = json.load(urllib.request.urlopen(req, timeout=90))
    if d.get("errors"):
        msgs = [e.get("message", "") for e in d["errors"]]
        if any("older than" in m for m in msgs):
            raise Retention(msgs[0])
        raise RuntimeError("; ".join(msgs))
    accts = d["data"]["viewer"]["accounts"]
    return accts[0] if accts else None

Q_DAILY = """query($acc:String!,$s:Time!,$e:Time!){viewer{accounts(filter:{accountTag:$acc}){
 rumPageloadEventsAdaptiveGroups(limit:5000,filter:{datetime_geq:$s,datetime_leq:$e},orderBy:[date_ASC]){
   count sum{visits} dimensions{date siteTag requestHost}}}}}"""

def Q_DIM(field):
    return ("query($acc:String!,$s:Time!,$e:Time!){viewer{accounts(filter:{accountTag:$acc}){"
            "rumPageloadEventsAdaptiveGroups(limit:200,filter:{datetime_geq:$s,datetime_leq:$e},"
            f"orderBy:[count_DESC]){{count dimensions{{{field}}}}}}}}}}}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="reports")
    args = ap.parse_args()
    token = os.environ.get("CLOUDFLARE_ANALYTICS_TOKEN")
    if not token:
        sys.exit("缺少 CLOUDFLARE_ANALYTICS_TOKEN（只需 Account Analytics: Read）")

    now = datetime.now(timezone.utc)
    daily = {}            # (date, siteTag) -> {count, visits}
    dims = defaultdict(lambda: defaultdict(int))
    oldest_ok = None
    chunks = 0
    windows = []          # 每一段實際查到的 (起, 迄) 日期，對帳用

    for i in range(MAX_CHUNKS):
        end = now - timedelta(days=CHUNK_DAYS * i)
        start = end - timedelta(days=CHUNK_DAYS)
        try:
            a = gq(token, Q_DAILY, {"acc": ACCOUNT, "s": iso(start), "e": iso(end)})
        except Retention:
            print(f"  撞到保留邊界，停在 {start.date()}", file=sys.stderr)
            break
        chunks += 1
        rows = (a or {}).get("rumPageloadEventsAdaptiveGroups", [])
        got = 0
        for r in rows:
            d = r["dimensions"]
            # 完全相等才算：用「包含」會把 data.civictech.tw 的瀏覽也算進主站
            if d.get("requestHost") and d["requestHost"] != HOST:
                continue
            key = (d["date"], d["siteTag"])
            # 兩段在同一個時間點交接、不重疊，所以交界日是兩個半天，要相加
            if key not in daily:
                daily[key] = {"count": 0, "visits": 0}
                got += 1
            daily[key]["count"] += r["count"]; daily[key]["visits"] += r["sum"]["visits"]
        oldest_ok = start.date().isoformat()
        windows.append((start.date().isoformat(), end.date().isoformat()))
        print(f"  {start.date()} ~ {end.date()}：{len(rows)} 列，新增 {got} 天", file=sys.stderr)
        # 維度統計只取最近兩段（更早的維度價值低、查詢也慢）
        if i < 2:
            for field in ("refererHost", "countryName", "deviceType", "userAgentBrowser", "requestPath"):
                try:
                    b = gq(token, Q_DIM(field), {"acc": ACCOUNT, "s": iso(start), "e": iso(end)})
                except Exception as e:
                    print(f"    維度 {field} 取不到：{e}", file=sys.stderr); continue
                for r in (b or {}).get("rumPageloadEventsAdaptiveGroups", []):
                    v = r["dimensions"].get(field) or "(無／直接進入)"
                    dims[field][v] += r["count"]

    if not daily:
        sys.exit("沒有抓到任何資料")

    # ── 彙總 ──
    by_date = defaultdict(lambda: {"count": 0, "visits": 0})
    by_site = defaultdict(lambda: {"count": 0, "visits": 0, "days": []})
    for (date, tag), v in daily.items():
        by_date[date]["count"] += v["count"]; by_date[date]["visits"] += v["visits"]
        s = by_site[tag]; s["count"] += v["count"]; s["visits"] += v["visits"]; s["days"].append(date)

    # ── 跟上一份快照對帳，再合併 ──
    # 2026-10-25 起，凌晨的自動執行有時只拿回極少的列（一次只剩「10/23 一萬次」，
    # 一次 8 月後全空），手動重跑卻是完整的。腳本照單全收、覆蓋掉好的那份，
    # /status 就退回「資料截至 7/31」，而且沒有任何地方出聲。所以：
    #   1. 這次拿到的天數，比上一份在同一段期間少一半以上 → 判定為殘缺，不寫檔、以失敗結束
    #   2. 上一份有、這次沒有的日子（例如已過 Cloudflare 保留期）→ 沿用上一份
    prev_path = max(glob.glob(os.path.join(args.out_dir, "traffic-*.json")), default=None)
    prev = {}
    if prev_path:
        with open(prev_path, encoding="utf-8") as f:
            prev = json.load(f).get("by_date", {})
    # 一段一段比：殘缺通常只出在其中一段，整段平均會把它蓋過去
    for ws, we in windows:
        p_days = [d for d in prev if ws <= d < we]
        n_days = [d for d in by_date if ws <= d < we]
        if len(p_days) >= 10 and len(n_days) < len(p_days) / 2:
            sys.exit(f"{ws} ~ {we} 這次只拿到 {len(n_days)} 天，上一份（{os.path.basename(prev_path)}）"
                     f"同期間有 {len(p_days)} 天，判定為殘缺，不覆蓋")
    kept = 0
    for date, v in prev.items():
        if date not in by_date:
            by_date[date] = {"count": v["count"], "visits": v["visits"]}
            kept += 1
    if kept:
        print(f"  沿用上一份快照的 {kept} 天", file=sys.stderr)

    by_month = defaultdict(lambda: {"count": 0, "visits": 0, "days": 0})
    for date, v in by_date.items():
        m = by_month[date[:7]]; m["count"] += v["count"]; m["visits"] += v["visits"]; m["days"] += 1

    dates = sorted(by_date)
    out = {
        "generated_at": now.isoformat(timespec="seconds"),
        "host": HOST,
        "retention_note": "Cloudflare 免費版 RUM 資料約保留半年；本檔是為了讓資料過期後仍留得住。",
        "oldest_queryable": oldest_ok,
        "earliest_data": dates[0],
        "latest_data": dates[-1],
        "days_with_traffic": len(dates),
        "total_pageviews": sum(v["count"] for v in by_date.values()),
        "total_visits": sum(v["visits"] for v in by_date.values()),
        "sites": {t: {"pageviews": v["count"], "visits": v["visits"],
                      "first_day": min(v["days"]), "last_day": max(v["days"]),
                      "days_with_traffic": len(v["days"])} for t, v in by_site.items()},
        "by_month": {k: by_month[k] for k in sorted(by_month)},
        "by_date": {k: by_date[k] for k in dates},
        "dimensions_recent_180d": {k: dict(sorted(v.items(), key=lambda x: -x[1])) for k, v in dims.items()},
    }

    os.makedirs(args.out_dir, exist_ok=True)
    # 按「月」命名而不是「日」：每天重跑會覆寫當月那一份，月底那份就含完整的
    # 半年回溯。一年 12 個檔而不是 365 個，而且每一份都是當下能查到的全部歷史。
    stamp = now.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m")
    jpath = os.path.join(args.out_dir, f"traffic-{stamp}.json")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"✅ 寫出 {jpath}", file=sys.stderr)
    print(json.dumps({k: out[k] for k in
        ("earliest_data","latest_data","days_with_traffic","total_pageviews","total_visits")},
        ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
