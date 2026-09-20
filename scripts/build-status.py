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
  reports/link-health-*.json  最新一份連結健檢
  data/index.json + data/v0/  資料庫本身
  ~/civictech-sync-state.json 同步狀態（只有 VPS 上有）
"""
import glob, json, os, sys
from collections import Counter
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TW = timezone(timedelta(hours=8))

def newest(pattern):
    fs = sorted(glob.glob(os.path.join(ROOT, pattern)))
    if not fs: return None, None
    return json.load(open(fs[-1], encoding="utf-8")), os.path.basename(fs[-1])

def esc(s):
    return (str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
            .replace('"',"&quot;"))

# ── 收資料 ──
traffic, traffic_file = newest("reports/traffic-*.json")
links, links_file = newest("reports/link-health-*.json")
index = json.load(open(os.path.join(ROOT, "data", "index.json"), encoding="utf-8"))

sync = None
sp = os.path.expanduser("~/civictech-sync-state.json")
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

# ── 圖表：每月瀏覽 ──
months = list((traffic or {}).get("by_month", {}).items())
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
<style>
:root{{
  --plane:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --s1:#2a78d6;
  --good:#0ca30c; --warn:#fab219; --serious:#ec835a; --crit:#d03b3b;
}}
@media (prefers-color-scheme:dark){{ :root:not([data-theme="light"]){{
  --plane:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --s1:#3987e5;
}} }}
:root[data-theme="dark"]{{
  --plane:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --s1:#3987e5;
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--plane);color:var(--ink);
  font:15px/1.6 -apple-system,BlinkMacSystemFont,"Noto Sans TC","Helvetica Neue",sans-serif}}
main{{max-width:900px;margin:0 auto;padding:44px 20px 80px}}
h1{{font-size:1.5rem;margin:0 0 .25rem;letter-spacing:-.01em}}
.sub{{color:var(--ink2);margin:0 0 2rem;font-size:.9rem}}
h2{{font-size:1rem;margin:2.6rem 0 .3rem}}
.note{{color:var(--muted);font-size:.8rem;margin:0 0 1rem}}
.card{{background:var(--surface);border:1px solid var(--grid);border-radius:10px;padding:18px}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}}
.tile .k{{color:var(--ink2);font-size:.78rem;margin-bottom:.35rem}}
.tile .v{{font-size:1.5rem;font-weight:700;line-height:1.15;font-variant-numeric:tabular-nums}}
.tile .m{{color:var(--muted);font-size:.75rem;margin-top:.3rem}}
.pill{{display:inline-flex;align-items:center;gap:.35em;font-size:.95rem;font-weight:700}}
.dot{{width:.62em;height:.62em;border-radius:50%;flex:none}}
table{{width:100%;border-collapse:collapse;font-size:.86rem}}
td{{padding:.32rem .5rem .32rem 0;vertical-align:middle}}
td.lbl{{color:var(--ink2);white-space:nowrap;width:1%}}
td.num{{text-align:right;font-variant-numeric:tabular-nums;color:var(--ink2);white-space:nowrap;width:1%}}
.bar{{height:11px;border-radius:0 4px 4px 0;background:var(--s1);min-width:2px}}
.track{{background:var(--grid);border-radius:0 4px 4px 0;height:11px}}
.stack{{display:flex;height:22px;border-radius:5px;overflow:hidden;gap:2px;background:var(--surface)}}
.stack i{{display:block}}
.legend{{display:flex;flex-wrap:wrap;gap:.35rem 1.1rem;margin-top:.7rem;font-size:.82rem;color:var(--ink2)}}
.legend span{{display:inline-flex;align-items:center;gap:.4em}}
.cols{{display:grid;grid-template-columns:1fr;gap:12px}}
@media(min-width:720px){{.cols{{grid-template-columns:1fr 1fr}}}}
.chips{{display:flex;flex-wrap:wrap;gap:.3rem;margin-top:.6rem}}
.chip{{font-size:.78rem;background:var(--plane);border:1px solid var(--grid);
  border-radius:999px;padding:.15rem .6rem;color:var(--ink2)}}
footer{{margin-top:3rem;padding-top:1rem;border-top:1px solid var(--grid);
  color:var(--muted);font-size:.8rem}}
a{{color:var(--s1)}}
svg text{{fill:var(--muted);font-size:11px}}
</style></head><body><main>
<h1>civictech.tw 運作狀況</h1>
<p class="sub">每日 04:00 自動更新　·　產生於 {now:%Y-%m-%d %H:%M}（台灣時間）</p>
""")

# ── 狀態磚 ──
# 「不知道」不等於「壞掉」。狀態檔只有 VPS 上有，在別處產生這一頁時讀不到——
# 那時畫成紅色是假警報，而假警報會訓練人忽略真警報。
if sync is None:
    sync_col, sync_txt, sync_sub = "var(--muted)", "未知", "此頁非由排程主機產生"
elif sync.get("last_status") == "ok":
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
    <div class="v pill"><span class="dot" style="background:{col}"></span>{dead_n}</div>
    <div class="m">共檢查 {links['網址數']} 個網址</div></div>""")
A("</div>")

# ── 每月瀏覽 ──
if months:
    A('<h2>每月瀏覽次數</h2>')
    A(f'<p class="note">⚠️ Cloudflare Web Analytics 免費版為<strong>抽樣估計</strong>，數字一律是 10 的倍數——趨勢可信，精確度不可信。資料最早只到 {traffic["earliest_data"]}（更早的已過保留期）。</p>')
    A('<div class="card"><table>')
    for m, v in months:
        w = v["count"] / mmax * 100
        A(f'<tr><td class="lbl">{m}</td><td><div class="track"><div class="bar" style="width:{w:.1f}%"></div></div></td>'
          f'<td class="num">{v["count"]:,}</td></tr>')
    A('</table><div class="legend"><span><span class="dot" style="background:var(--s1)"></span>瀏覽次數</span></div></div>')

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
    A(f'<p class="note">{links["掃描日期"]}　純 HTTP 檢查，沒有用 AI。</p>')
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
原始快照在 <a href="https://gitlab.com/dsw4work/civictech-tw-data">repo 的 reports/</a>。
API 在 <a href="/">data.civictech.tw</a>　·　<a href="https://civictech.tw">civictech.tw</a>
</footer></main></body></html>""")

path = os.path.join(ROOT, "data", "status.html")
with open(path, "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print(f"✅ 寫出 {path}（{os.path.getsize(path)/1024:.0f}KB）")
