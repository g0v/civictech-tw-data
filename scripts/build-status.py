#!/usr/bin/env python3
"""
產生 data/status.html —— 一頁看完 civictech.tw 的運作狀況。

為什麼要有這一頁：想看細節時有個地方，而且**拿得出手**（給業師、jothon、10/24 報告）。
它不是監控層——「出事了會來找你」那一層是晨報（civictech-status.sh），
一個要人記得去看的儀表板，最後都會變成第二個「收了三個月資料沒人看」的東西。

為什麼由 cron 產生而不是手寫：這個專案反覆踩的坑是「寫下來的現況會過期，
而且會以既定事實的姿態被引用」——README 寫過「無分析工具」（錯的，它從 6/09 就在收）、
寫過「目標 9 月前搞定」（躺了三個月）。綁在 cron 上它才不會。

資料來源（缺任何一項都只是少一塊，不會讓整頁掛掉）：
  reports/traffic-*.json      最新一份流量快照
  reports/link-health-*.json  最新一份連結健檢（VPS 上另讀 ~/civictech-linkcheck/，取兩邊最新）
  data/index.json + data/v0/  資料庫本身
  ~/civictech-sync-state.json 同步狀態（只有 VPS 上有；可用 CIVICTECH_SYNC_STATE 指到別的檔）
"""
import glob, json, os, sys
from collections import Counter
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TW = timezone(timedelta(hours=8))

def newest(pattern, *dirs):
    # 檔名帶日期，用 basename 排序才能跨資料夾比新舊。相對路徑以 repo 根目錄為準
    dirs = [os.path.join(ROOT, os.path.expanduser(d)) for d in dirs or [""]]
    fs = sorted((f for d in dirs for f in glob.glob(os.path.join(d, pattern))),
                key=os.path.basename)
    if not fs: return None, None
    return json.load(open(fs[-1], encoding="utf-8")), os.path.basename(fs[-1])

def esc(s):
    return (str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
            .replace('"',"&quot;"))

# ── 收資料 ──
traffic, traffic_file = newest("reports/traffic-*.json")
# 每週健檢（~/bin/civictech-linkcheck.sh）刻意把報告寫在 repo 外面，只有 VPS 上有。
# 只讀 reports/ 的話，這一頁會永遠停在 2026-09-19 那份手動報告。
links, links_file = newest("link-health-*.json", "reports", "~/civictech-linkcheck")
index = json.load(open(os.path.join(ROOT, "data", "index.json"), encoding="utf-8"))

sync = None
# 同步腳本在部署前產這一頁，那時正式狀態檔還是上一次的結果；
# 它會把「這一次」的暫存狀態寫到別處、用這個變數指過來，頁面才不會落後一天。
sp = os.environ.get("CIVICTECH_SYNC_STATE") or os.path.expanduser("~/civictech-sync-state.json")
if os.path.exists(sp):
    try: sync = json.load(open(sp, encoding="utf-8"))
    except Exception: pass

# 資料完整度：以公民科技專案為主
proj = json.load(open(os.path.join(ROOT, "data/v0/tech/projects.json"), encoding="utf-8"))
recs = proj["records"]
def has(f, *keys): return any(f.get(k) for k in keys)
completeness = [
    ("有名稱",        sum(1 for r in recs if r["fields"].get("project name"))),
    ("有分類",        sum(1 for r in recs if r["fields"].get("影響力類別"))),
    ("有可點的連結",   sum(1 for r in recs if has(r["fields"], "Website URL", "github"))),
    ("有簡介",        sum(1 for r in recs if r["fields"].get("Intro"))),
    ("有標籤",        sum(1 for r in recs if r["fields"].get("標籤"))),
]
total_proj = len(recs)

# 連結健檢彙總
link_counts, dead_projects = Counter(), []
if links:
    rows = links["結果"]
    for r in rows: link_counts[r["狀態"]] += 1
    by_proj = {}
    for r in rows: by_proj.setdefault(r["專案"], []).append(r["狀態"])
    # 保守定義：只有「每一條連結都被證明壞掉」才算。
    # 「擋機器」（403，站台擋爬蟲）與「無法判定」（Facebook 對機器回登入牆）
    # 都不是壞掉的證據——把它們算進來會叫人去修沒有壞的東西。
    CONFIRMED_DEAD = {"死掉", "連不上"}
    dead_projects = sorted(p for p, ss in by_proj.items()
                           if ss and all(s in CONFIRMED_DEAD for s in ss))

# linkcheck.py 的狀態值是中文，不是英文代碼——照著它寫，不要自己發明。
# （2026-09-20 第一版就是猜成英文，結果只有 OK 對得上，失效連結顯示 0。）
STATUS_ORDER = [("OK","打得開","good"), ("轉址","轉址","warning"),
                ("擋機器","擋機器","warning"), ("無法判定","無法判定","warning"),
                ("死掉","死掉","critical"), ("連不上","連不上","critical")]
# 報告裡若冒出沒列到的狀態，寧可吵也不要安靜漏掉
known = {k for k, _, _ in STATUS_ORDER}
unknown_status = {k: v for k, v in link_counts.items() if k not in known}
if unknown_status:
    print(f"⚠️ 連結健檢出現未知狀態，沒有被畫進圖裡：{unknown_status}", file=sys.stderr)

now = datetime.now(TW)
def ago(iso_s):
    if not iso_s: return "—"
    try: t = datetime.fromisoformat(iso_s)
    except Exception: return iso_s
    if t.tzinfo is None: t = t.replace(tzinfo=timezone.utc)
    h = (datetime.now(timezone.utc) - t).total_seconds() / 3600
    return f"{h:.0f} 小時前" if h < 48 else f"{h/24:.0f} 天前"

def days_old(date_s):
    try: return (now.date() - datetime.fromisoformat(date_s[:10]).date()).days
    except Exception: return None

def as_of(date_s, max_days, what):
    """每一區都標「資料截至哪天」；超過 max_days 就變黃——安靜過期的區塊比空白更會誤導。"""
    d = days_old(date_s)
    if d is not None and d > max_days:
        return f'<span class="stale">⚠️ 資料截至 {esc(date_s[:10])}，已 {d} 天沒更新（{what}）</span>'
    return f"資料截至 {esc(date_s[:10])}"

# ── 圖表：每月瀏覽 ──
months = list((traffic or {}).get("by_month", {}).items())
# 快照當月還沒過完，數字只算到 latest_data，不能跟整月並排比
latest = (traffic or {}).get("latest_data", "")
partial_month = latest[:7] if latest and latest[8:10] < "28" else None
mmax = max([v["count"] for _, v in months], default=1)

# ── 圖表：來源 ──
refs = list((traffic or {}).get("dimensions_recent_180d", {}).get("refererHost", {}).items())
rtot = sum(v for _, v in refs) or 1
top_refs = refs[:8]
rest = sum(v for _, v in refs[8:])
if rest: top_refs = top_refs + [("其他來源合計", rest)]
rmax = max([v for _, v in top_refs], default=1)

out = []
A = out.append
A(f"""<!doctype html>
<html lang="zh-Hant-TW"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>civictech.tw 運作狀況</title>
<meta name="description" content="civictech.tw 的流量、資料完整度與連結健檢，每日自動更新。">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@300..700&family=Geist+Mono:wght@400..600&display=swap">
<style>
/* 色票與字體照 civictech.tw 的 src/styles/global.css，讓兩站看起來是同一家。
   主站的深色模式掛在 data-theme 上、靠 JS 決定；這頁是純靜態，所以跟系統設定走。
   狀態色（好／注意／壞）主站沒有，飽和度壓到跟冷底同一個色溫。 */
:root{{
  --paper:#f4f7f7; --surface:#ffffff; --surface-2:#e9eff0;
  --ink:#0f1a1d; --ink-2:#33434a; --ink-muted:#56676e;
  --line:#dde5e7; --line-strong:#c6d2d5;
  --accent:#0d5f74; --accent-soft:#e0eef1;
  --good:#2f7d55; --warn:#c58a1a; --crit:#b6453c;
  --font-sans:'Geist','PingFang TC','Noto Sans TC','Microsoft JhengHei',system-ui,sans-serif;
  --font-mono:'Geist Mono','SF Mono',ui-monospace,monospace;
  color-scheme:light;
}}
@media (prefers-color-scheme:dark){{ :root:not([data-theme="light"]){{
  --paper:#0e1319; --surface:#161d26; --surface-2:#1d2631;
  --ink:#e8eef5; --ink-2:#c3ccd8; --ink-muted:#93a0b2;
  --line:#263140; --line-strong:#35424f;
  --accent:#2e9cb8; --accent-soft:#0f3340;
  --good:#5fbf8a; --warn:#f2b94b; --crit:#ec7b70;
  color-scheme:dark;
}} }}
:root[data-theme="dark"]{{
  --paper:#0e1319; --surface:#161d26; --surface-2:#1d2631;
  --ink:#e8eef5; --ink-2:#c3ccd8; --ink-muted:#93a0b2;
  --line:#263140; --line-strong:#35424f;
  --accent:#2e9cb8; --accent-soft:#0f3340;
  --good:#5fbf8a; --warn:#f2b94b; --crit:#ec7b70;
  color-scheme:dark;
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--paper);color:var(--ink);font-family:var(--font-sans);
  font-size:15px;line-height:1.7;-webkit-font-smoothing:antialiased}}
::selection{{background:var(--accent-soft);color:var(--ink)}}
.topbar{{border-bottom:1px solid var(--line);background:var(--surface)}}
.topbar div{{max-width:900px;margin:0 auto;padding:.85rem 16px;display:flex;
  justify-content:space-between;align-items:center;gap:1rem;font-size:.85rem}}
.brand{{font-weight:600;letter-spacing:-.02em;color:var(--ink);text-decoration:none}}
.brand span{{color:var(--accent)}}
.topbar nav{{display:flex;gap:1.1rem}}
.topbar nav a{{color:var(--ink-2);text-decoration:none}}
.topbar nav a:hover{{color:var(--accent)}}
main{{max-width:900px;margin:0 auto;padding:40px 16px 80px}}
h1,h2{{letter-spacing:-.02em;line-height:1.25;text-wrap:balance}}
h1{{font-size:1.75rem;font-weight:650;margin:0 0 .4rem}}
.sub{{color:var(--ink-muted);margin:0 0 2rem;font-size:.85rem}}
h2{{font-size:1.05rem;font-weight:600;margin:2.6rem 0 .3rem}}
.note{{color:var(--ink-muted);font-size:.8rem;margin:0 0 1rem}}
.card{{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:18px}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}}
.tile .k{{color:var(--ink-2);font-size:.78rem;margin-bottom:.35rem}}
.tile .v{{font-family:var(--font-mono);font-size:1.6rem;font-weight:500;line-height:1.15;
  font-variant-numeric:tabular-nums;letter-spacing:-.03em}}
.tile .m{{color:var(--ink-muted);font-size:.75rem;margin-top:.3rem}}
.tile .v.pill{{font-family:var(--font-sans);display:inline-flex;align-items:center;gap:.4em;
  font-size:1rem;font-weight:600;letter-spacing:0}}
.tile .v.pill.n{{font-family:var(--font-mono);font-size:1.6rem;font-weight:500}}
.dot{{width:.62em;height:.62em;border-radius:50%;flex:none}}
table{{width:100%;border-collapse:collapse;font-size:.86rem}}
td{{padding:.32rem .5rem .32rem 0;vertical-align:middle}}
td.lbl{{color:var(--ink-2);white-space:nowrap;width:1%}}
td.num{{text-align:right;font-family:var(--font-mono);font-variant-numeric:tabular-nums;color:var(--ink-2);white-space:nowrap;width:1%}}
.bar{{height:11px;border-radius:0 4px 4px 0;background:var(--accent);min-width:2px}}
.track{{background:var(--surface-2);border-radius:0 4px 4px 0;height:11px}}
.stack{{display:flex;height:22px;border-radius:5px;overflow:hidden;gap:2px;background:var(--surface)}}
.stack i{{display:block}}
.legend{{display:flex;flex-wrap:wrap;gap:.35rem 1.1rem;margin-top:.7rem;font-size:.82rem;color:var(--ink-2)}}
.legend span{{display:inline-flex;align-items:center;gap:.4em}}
.cols{{display:grid;grid-template-columns:1fr;gap:12px}}
@media(min-width:720px){{.cols{{grid-template-columns:1fr 1fr}}}}
.chips{{display:flex;flex-wrap:wrap;gap:.3rem;margin-top:.6rem}}
.chip{{font-size:.78rem;background:var(--surface-2);border:1px solid var(--line);
  border-radius:999px;padding:.15rem .6rem;color:var(--ink-2)}}
footer{{margin-top:3rem;padding-top:1rem;border-top:1px solid var(--line);
  color:var(--ink-muted);font-size:.8rem}}
a{{color:var(--accent);text-underline-offset:3px}}
code{{font-family:var(--font-mono);font-size:.9em}}
svg text{{fill:var(--ink-muted);font-size:11px}}
.stale{{color:var(--ink);background:color-mix(in srgb,var(--warn) 22%,transparent);
  border-radius:4px;padding:.05rem .35rem}}
.partial{{color:var(--ink-muted);font-size:.75rem}}
.bar-partial{{background:repeating-linear-gradient(135deg,var(--accent) 0 4px,transparent 4px 7px)}}
.dot-partial{{background:repeating-linear-gradient(135deg,var(--accent) 0 2px,transparent 2px 4px);
  box-shadow:inset 0 0 0 1px var(--accent)}}
</style></head><body>
<header class="topbar"><div><a class="brand" href="https://civictech.tw">civictech<span>.tw</span></a>
<nav><a href="https://civictech.tw">回主站</a><a href="/">資料 API</a></nav></div></header>
<main>
<h1>civictech.tw 運作狀況</h1>
<p class="sub">每日 04:00 自動更新　·　產生於 {now:%Y-%m-%d %H:%M}（台灣時間）</p>
""")

# ── 狀態磚 ──
# 「不知道」不等於「壞掉」。狀態檔只有 VPS 上有，在別處產生這一頁時讀不到——
# 那時畫成紅色是假警報，而假警報會訓練人忽略真警報。
if sync is None:
    sync_col, sync_txt, sync_sub = "var(--ink-muted)", "未知", "此頁非由排程主機產生"
elif sync.get("last_status") == "ok":
    # 同步成功但有步驟被跳過或失敗（例如沒有 analytics token），不能只亮綠燈：
    # 2026-09 到 10 月流量快照每天都被跳過，狀態檔有寫，頁面卻一直顯示「正常」。
    issues = [s for s in (sync.get("last_message") or "").split("；")
              if "跳過" in s or "失敗" in s]
    if issues:
        sync_col, sync_txt, sync_sub = "var(--warn)", "部分異常", "；".join(issues)
    else:
        sync_col, sync_txt = "var(--good)", "正常"
        sync_sub = f"最後成功 {ago(sync.get('last_success'))}"
else:
    sync_col, sync_txt = "var(--crit)", "異常"
    sync_sub = sync.get("last_message") or f"最後成功 {ago(sync.get('last_success'))}"
dead_n = link_counts["死掉"] + link_counts["連不上"]
A('<div class="tiles">')
A(f"""<div class="card tile"><div class="k">每日同步</div>
<div class="v pill"><span class="dot" style="background:{sync_col}"></span>{sync_txt}</div>
<div class="m">{esc(sync_sub)}</div></div>""")
A(f"""<div class="card tile"><div class="k">公民科技專案</div><div class="v">{total_proj}</div>
<div class="m">另有公民科學計畫 {next((t['recordCount'] for d in index['datasets'] for t in d['tables'] if t['slug']=='programs'), '—')} 筆</div></div>""")
if traffic:
    A(f"""<div class="card tile"><div class="k">累計瀏覽</div><div class="v">{traffic['total_pageviews']:,}</div>
    <div class="m">{traffic['earliest_data']} 起，{traffic['days_with_traffic']} 天有流量</div></div>""")
if links:
    col = "var(--crit)" if dead_n > 20 else "var(--warn)"
    A(f"""<div class="card tile"><div class="k">失效連結</div>
    <div class="v pill n"><span class="dot" style="background:{col}"></span>{dead_n}</div>
    <div class="m">共檢查 {links['網址數']} 個網址</div></div>""")
A("</div>")

# ── 每月瀏覽 ──
if months:
    A('<h2>每月瀏覽次數</h2>')
    A(f'<p class="note">{as_of(latest, 7, "流量快照沒有在跑")}。Cloudflare Web Analytics 免費版為<strong>抽樣估計</strong>，數字一律是 10 的倍數——趨勢可信，精確度不可信。資料最早只到 {traffic["earliest_data"]}（更早的已過保留期）。</p>')
    A('<div class="card"><table>')
    for m, v in months:
        w = v["count"] / mmax * 100
        part = m == partial_month
        lbl = f'{m}<span class="partial">（至 {latest[5:]}）</span>' if part else m
        A(f'<tr><td class="lbl">{lbl}</td><td><div class="track"><div class="bar{" bar-partial" if part else ""}" style="width:{w:.1f}%"></div></div></td>'
          f'<td class="num">{v["count"]:,}</td></tr>')
    A('</table><div class="legend"><span><span class="dot" style="background:var(--accent)"></span>瀏覽次數</span>')
    if partial_month:
        A('<span><span class="dot dot-partial"></span>當月未過完</span>')
    A('</div></div>')

# ── 來源 ──
if top_refs:
    A('<h2>流量來源</h2>')
    A('<p class="note">近 180 天。「無／直接進入」＝有人把網址傳給另一個人（Line、私訊、簡報），或從不帶 referrer 的 AI App 點進來。</p>')
    A('<div class="card"><table>')
    for k, v in top_refs:
        w = v / rmax * 100
        A(f'<tr><td class="lbl">{esc(k)[:30]}</td><td><div class="track"><div class="bar" style="width:{w:.1f}%"></div></div></td>'
          f'<td class="num">{v/rtot*100:.1f}%</td></tr>')
    A('</table></div>')

# ── 連結健檢 + 資料完整度 ──
A('<div class="cols">')
if links:
    A('<div><h2>連結健檢</h2>')
    A(f'<p class="note">{as_of(links["掃描日期"], 10, "每週健檢沒有讀到")}。每週一自動掃描，純 HTTP 檢查，沒有用 AI。</p>')
    A('<div class="card"><div class="stack">')
    tot_l = sum(link_counts.values()) or 1
    varmap = {"good":"var(--good)","warning":"var(--warn)","critical":"var(--crit)"}
    for key, label, role in STATUS_ORDER:
        n = link_counts.get(key, 0)
        if n: A(f'<i style="width:{n/tot_l*100:.2f}%;background:{varmap[role]}" title="{label} {n}"></i>')
    A('</div><div class="legend">')
    for key, label, role in STATUS_ORDER:
        n = link_counts.get(key, 0)
        if n: A(f'<span><span class="dot" style="background:{varmap[role]}"></span>{label} {n}</span>')
    A('</div>')
    if dead_projects:
        A(f'<p class="note" style="margin:.9rem 0 0"><strong>{len(dead_projects)} 個專案的連結全部確認失效</strong>——使用者點進去每條路都是死的（403 與 Facebook 不算，那兩種沒被證明壞掉）：</p>')
        A('<div class="chips">' + "".join(f'<span class="chip">{esc(p)[:22]}</span>' for p in dead_projects[:16]) + '</div>')
    A('</div></div>')

A('<div><h2>資料完整度</h2>')
A(f'<p class="note">公民科技專案共 {total_proj} 筆。能端上桌的是有分類又有連結的那些。</p>')
A('<div class="card"><table>')
for label, n in completeness:
    A(f'<tr><td class="lbl">{label}</td><td><div class="track"><div class="bar" style="width:{n/total_proj*100:.1f}%"></div></div></td>'
      f'<td class="num">{n}</td></tr>')
A('</table></div></div>')
A('</div>')

A(f"""<footer>
資料來源：Cloudflare Web Analytics（流量）、<code>{esc(links_file or '—')}</code>（連結）、<code>{esc(os.path.basename('index.json'))}</code>（資料庫）。
流量快照在 <a href="https://github.com/g0v/civictech-tw-data/tree/main/reports">repo 的 reports/</a>；每週連結健檢的報告只留在排程主機上。
API 在 <a href="/">data.civictech.tw</a>　·　<a href="https://civictech.tw">civictech.tw</a>
</footer></main></body></html>""")

path = os.path.join(ROOT, "data", "status.html")
with open(path, "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print(f"✅ 寫出 {path}（{os.path.getsize(path)/1024:.0f}KB）")
