#!/usr/bin/env python3
"""把一個專案能拿到的素材收成一包，附上出處與取得日期。

這是 AI insight 管線的第一步（採集）。**刻意不含「產生 insight」那一步**——
那一步要能被任何人、任何 AI 拿去跑，才接得上「社群貢獻算力」那條線。

用法：python3 scripts/insight-harvest.py <專案名稱的一部分>
環境變數：CIVICTECH_DATA（資料目錄，預設是本 repo 的 data/v0/tech）

設計上的四個前提，全部是 2026-09-19 試點實際撞出來的：

  1. **欄位名稱不可信。** 「臺灣好植地」的 github 欄位裝的是 Facebook 群組網址，
     「零時空汙觀測網」的是使用者帳號頁。一律看網址本身，不看它放在哪一欄。
  2. **抓不到要講出來。** 沒被記錄的失敗會讓後面的 AI 以為「沒有這個東西」，
     而不是「這個東西拿不到」——前者會讓它自己補一個。
  3. **抓到了不等於可信。** 見 relevance_guard()。這是整支腳本最重要的一段。
  4. 每段素材都要帶出處與取得日期，否則產出的 insight 無法被查證。
"""
import csv, gzip, io, json, os, re, subprocess, sys, tempfile, time, urllib.parse, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

TW = timezone(timedelta(hours=8))
TODAY = datetime.now(TW).strftime("%Y-%m-%d")
UA = {"User-Agent": "civictech.tw-insight/0.1 (+https://civictech.tw)"}
BROWSER_UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/140.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9",
}
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.environ.get("CIVICTECH_DATA") or os.path.join(REPO, "data", "v0", "tech")


def get(url, timeout=20, accept=None, browser=False):
    h = dict(BROWSER_UA if browser else UA)
    if accept:
        h["Accept"] = accept
    # 匿名呼叫 GitHub API 每小時只有 60 次，一次跑完全部專案會撞上限；有 token 就帶上
    if url.startswith("https://api.github.com/") and os.environ.get("GITHUB_TOKEN"):
        h["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
        charset = r.headers.get_content_charset()
    # 檔案館的 id_ 快照照原樣回傳當年的壓縮內容，沒解壓就會是一堆亂碼
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    # 早年的台灣網站常是 Big5，編碼寫在 header 或 <meta> 裡
    if not charset:
        m = re.search(rb"charset=[\"']?([\w-]+)", body[:4096], re.I)
        charset = m.group(1).decode() if m else "utf-8"
    try:
        return body.decode(charset, "replace")
    except LookupError:
        return body.decode("utf-8", "replace")


def get_page(url, timeout=20):
    """先用老實的 UA，被擋再換瀏覽器 UA 試一次。
    有些站台擋的是沒見過的 UA 而不是機器本身。"""
    try:
        return get(url, timeout)
    except urllib.error.HTTPError as e:
        if e.code in (403, 406, 429):
            return get(url, timeout, browser=True)
        raise


CHROME = os.environ.get("CHROME") or "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
NEEDS_JS = re.compile(r"enable JavaScript|JavaScript (must be|is required)|without JavaScript|啟用 JavaScript|\{\{")


def render(url):
    """用 headless Chrome 把頁面的 JS 跑完再取 DOM。沒有 Chrome 就回空字串，由呼叫端保留原本的結果。"""
    if not os.path.exists(CHROME):
        return ""
    with tempfile.TemporaryDirectory() as profile:
        try:
            r = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
                                f"--user-data-dir={profile}", "--virtual-time-budget=8000",
                                "--dump-dom", url], capture_output=True, timeout=90)
        except subprocess.TimeoutExpired:
            return ""
    return strip_html(r.stdout.decode("utf-8", "replace"))


def page_text(url, rendered_url=None):
    """一般網頁的正文。很多專案站是單頁應用，原始 HTML 只有「請啟用 JavaScript」或
    {{ 模板 }}；這種就交給 render() 再跑一次，取比較長的那份。"""
    text = strip_html(get_page(url))
    if BOT_WALL.search(text[:500]):
        return text  # 不交給瀏覽器去解驗證，由呼叫端記成「抓不到」
    if len(text) < 300 or NEEDS_JS.search(text[:500]):
        full = render(rendered_url or url)
        if len(full) > len(text):
            text = full
    return text


EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")


def get_hackmd(url):
    """HackMD 的頁面是 JS 編輯器，直接抓只拿到外殼；加 /download 才是原始 Markdown。
    共筆裡常留聯絡 email，先遮掉，免得一路被抄進 insight。"""
    base = re.sub(r"[?#].*$", "", url).rstrip("/")
    # 書本模式的子頁長這樣：/@user/book/%2F<note id>，或把整個網址編碼進路徑
    inner = urllib.parse.unquote(base.split("/", 3)[3]) if base.count("/") >= 3 else ""
    if "http" in inner:
        base = re.sub(r"[?#].*$", "", inner[inner.index("http"):]).rstrip("/")
    elif "//" in inner or re.search(r"/@[^/]+/[^/]+//?[\w-]{20,}$", "/" + inner):
        base = base.split("/", 3)[0] + "//" + base.split("/")[2] + "/" + inner.rstrip("/").split("/")[-1]
    return EMAIL.sub("[email]", get(base + "/download"))


GDOC = re.compile(r"https://docs\.google\.com/(document|presentation|spreadsheets)/d/([\w-]{20,})")


def get_gdoc(url):
    """Google 文件、簡報、試算表都有官方的純文字匯出，公開的不用登入就拿得到。"""
    kind, doc_id = GDOC.match(url).groups()
    export = {"document": "export?format=txt", "presentation": "export/txt",
              "spreadsheets": "export?format=csv"}[kind]
    return EMAIL.sub("[email]", get(f"https://docs.google.com/{kind}/d/{doc_id}/{export}", timeout=60))


# 共筆裡的這些連結追下去也不會有專案說明
NOT_FOLLOW = re.compile(r"facebook\.com|youtube\.com|youtu\.be|imgur|/uploads?/|\.(png|jpe?g|gif)$")


def doc_text(url):
    kind = classify(url)
    if kind == "hackmd":
        text = get_hackmd(url)
        # 只放了幾個連結的短共筆（2026-10 有好幾個專案是這樣），往下追一層，最多兩個
        if len(text) < 500:
            links = [u.rstrip(").,") for u in re.findall(r"https?://[^\s)\]>\"']+", text)]
            links = [u for u in dict.fromkeys(links) if not NOT_FOLLOW.search(u) and "hackmd.io/_" not in u]
            for u in links[:2]:
                try:
                    sub = get_hackmd(u) if classify(u) == "hackmd" else EMAIL.sub("[email]", page_text(u))
                    text += f"\n\n共筆連到的 {u}：{sub[:1200]}"
                except Exception as e:
                    text += f"\n\n共筆連到的 {u} 抓不到（{type(e).__name__}）"
        return text
    if kind == "gdoc":
        return get_gdoc(url)
    return EMAIL.sub("[email]", page_text(url))


def harvest_hackfoldr(url):
    """hackfoldr 是一份「連結＋標題」的清單，頁面本身由 JS 組出來。
    清單存在 Google 試算表（長 ID）或 EtherCalc（短名稱），直接讀那份 CSV，
    再順著抓第一份共筆——它通常就是專案的概念說明。"""
    m = re.search(r"hackfoldr\.org/([^/?#)\s]+)", url)
    if not m:
        raise ValueError("網址裡沒有 hackfoldr 名稱")
    fid = m.group(1)
    src = (f"https://docs.google.com/spreadsheets/d/{fid}/export?format=csv" if len(fid) >= 40
           else f"https://ethercalc.net/_/{fid}/csv")
    raw = get(src, timeout=60)
    # 早期的 EtherCalc 清單後來搬去 Google 試算表，原處只留一行「請改到…」
    moved = re.search(r"\b(1[\w-]{39,})\b", raw)
    if moved and re.search(r"此後台停止更新|has been moved to", raw):
        src = f"https://docs.google.com/spreadsheets/d/{moved.group(1)}/export?format=csv"
        raw = get(src, timeout=60)
    rows = [r for r in csv.reader(io.StringIO(raw))
            if len(r) > 1 and r[1].strip() and not r[0].startswith("#")]
    titles = [r[1].strip() for r in rows]
    text = f"目錄：{'、'.join(titles[:30])}"
    # 不往試算表追：災害類 hackfoldr 常掛著傷患、聯絡人名單
    first = next((r[0].strip() for r in rows if classify(r[0].strip()) in ("hackmd", "gdoc")
                  and "/spreadsheets/" not in r[0]), None)
    if first:
        try:
            text += f"\n\n第一份共筆（{first}）：{doc_text(first)}"
        except Exception as e:
            text += f"\n\n第一份共筆（{first}）抓不到：{type(e).__name__}"
    return {"來源": url, "清單來源": src, "正文前 3000 字": text[:3000], "全文長度": len(text)}


# 網站明擺著不讓自動程式讀（Anubis 這類擋 AI 爬蟲的驗證頁）。這是站方的選擇，不去繞過它。
BOT_WALL = re.compile(r"正在確認你是不是機器人|Making sure you're not a bot|Access Denied: error code")


# 網站還回 200，但內容已經不是專案本身：伺服器預設頁、停放網域
DEAD_PAGE = re.compile(r"(?i)Apache2 \w+ Default Page|Welcome to nginx|^Laravel |domain (is|may be) for sale|This domain has expired|domain name has been registered")


# 拆專案名稱時太常見、證明不了任何事的詞
GENERIC = {"台灣", "臺灣", "taiwan", "資料", "平台", "平臺", "專案", "系統", "計畫", "計劃", "網站", "工具", "政府", "中文", "the", "and"}


def name_terms(name, name_en=""):
    """專案名稱拆成可以拿來比對的詞：英文整詞，中文另切 2 字一組。"""
    terms = {w for t in (name, name_en) for w in re.split(r"[\s／/｜|、,，_:：()（）-]+", (t or "").lower()) if len(w) >= 2}
    low = (name or "").lower()
    terms |= {low[i:i + 2] for i in range(len(low) - 1) if re.match(r"[一-鿿]{2}", low[i:i + 2])}
    return terms - GENERIC


def wayback(url, terms=None):
    """網站失效時，到網際網路檔案館找最近一個「還是這個專案」的快照。

    不能直接拿最後一個快照：網域過期後常被別人接手。2026-10 實測，
    立委投票指南的網域變成博弈站、享食台灣的變成小說站，檔案館照樣收。
    所以由新到舊往回找，跳過伺服器預設頁，並要求內文提到專案名稱裡的詞。
    快照日期一定要帶著走：它描述的是那一天的專案，不是現在的。"""
    api = ("https://web.archive.org/cdx/search/cdx?output=json&limit=-10&collapse=digest"
           "&filter=statuscode:200&filter=mimetype:text/html&url=" + urllib.parse.quote(url, safe=""))
    for wait in (0, 30, 90):  # 檔案館很容易回 429 或拒絕連線，等一下通常就好
        time.sleep(wait)
        try:
            rows = json.loads(get(api, timeout=30) or "[]")
            break
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            last = e
        except urllib.error.URLError as e:  # 連續查詢太多次時，檔案館會直接拒絕連線
            last = e
    else:
        # 連不上不等於沒有快照，兩者要分開講，否則就是把「拿不到」寫成「不存在」
        raise RuntimeError(f"網際網路檔案館暫時連不上（{last}），沒查到有沒有快照")
    if len(rows) < 2:
        return None
    failed = 0
    for ts, original in [(r[1], r[2]) for r in reversed(rows[1:])]:
        snap = f"https://web.archive.org/web/{ts}/{original}"
        # id_ 拿到的是原始 HTML；要跑 JS 時改開一般的快照頁，它的 JS 也是從檔案館載入
        try:
            text = page_text(f"https://web.archive.org/web/{ts}id_/{original}", rendered_url=snap)
        except Exception:
            failed += 1  # 抓不下來的不能算成「不像」，最後要分開講
            time.sleep(10)
            continue
        # 比對時去掉檔案館自己的工具列，它會印出原網址，什麼都對得上
        body = re.sub(r"The Wayback Machine - \S+", " ", text).lower()
        if DEAD_PAGE.search(body[:500]) or (terms and not any(t in body for t in terms)):
            continue
        return {"來源": snap, "快照日期": f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}",
                "正文前 3000 字": text[:3000], "全文長度": len(text)}
    seen = len(rows) - 1 - failed
    raise RuntimeError(f"網際網路檔案館最近 {len(rows) - 1} 個快照：{seen} 個不像這個專案（預設頁或內文沒提到專案名稱）"
                       + (f"，{failed} 個抓不下來，沒能確認" if failed else ""))


ARCHIVE_INDEX = "https://raw.githubusercontent.com/g0v-data/g0v-hackmd-archive/main/posts.json"
ARCHIVE_CACHE = os.path.expanduser("~/.cache/civictech-insight/hackmd-posts.json")
_archive = None


def norm_title(t):
    return re.sub(r"[\s#＃「」『』\"'（）()]+", "", (t or "").lower())


def archive_notes(name, name_en=""):
    """在 g0v HackMD 封存的標題索引（約 5 萬篇，只有標題沒有內文）裡找這個專案的共筆。

    比對刻意很嚴：標題整串等於專案名稱，或用 // ｜ | : 切開後有一段相等。
    寬鬆比對試過，「公民記者證產生器」的英文名 reporter 會配到一封外國記者的來信。
    索引 24MB，快取一週。"""
    global _archive
    if _archive is None:
        fresh = os.path.exists(ARCHIVE_CACHE) and time.time() - os.path.getmtime(ARCHIVE_CACHE) < 7 * 86400
        if not fresh:
            os.makedirs(os.path.dirname(ARCHIVE_CACHE), exist_ok=True)
            with open(ARCHIVE_CACHE, "w") as fh:
                fh.write(get(ARCHIVE_INDEX, timeout=120))
        _archive = list(json.load(open(ARCHIVE_CACHE)).values())
    keys = {norm_title(k) for k in (name, name_en) if len(norm_title(k)) >= 3}
    hits = []
    for n in _archive:
        parts = {norm_title(x) for x in re.split(r"//|｜|\||：|:", n.get("title") or "")} | {norm_title(n.get("title"))}
        if keys & parts:
            hits.append({"網址": f"https://g0v.hackmd.io/{n['id']}", "標題": n["title"], "最後修改": n.get("lastchangeAt")})
    return sorted(hits, key=lambda h: h["最後修改"] or "", reverse=True)[:2]


def classify(url):
    u = url.strip()
    if re.match(r"https?://([\w-]+\.)?hackmd\.io/(?!\?)[^?#]+", u):
        return "hackmd"
    if GDOC.match(u):
        return "gdoc"
    if re.match(r"https?://(www\.)?github\.com/[^/]+/[^/]+", u):
        return "github_repo"
    if re.match(r"https?://(www\.)?github\.com/[^/]+/?$", u):
        return "github_user"
    if "facebook.com" in u:
        return "facebook"
    if "hackfoldr" in u:
        return "hackfoldr"
    if u.startswith("http"):
        return "web"
    return "other"


def strip_html(html):
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)  # 註解：有些站在這裡寫了整段開發筆記
    html = re.sub(r"<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<[^>]+>", " ", html)
    html = re.sub(r"&nbsp;?", " ", html).replace("&amp;", "&")
    return re.sub(r"\s+", " ", html).strip()


def harvest_github_repo(url):
    m = re.search(r"github\.com/([^/]+)/([^/?#]+)", url)
    owner, repo = m.group(1), m.group(2).removesuffix(".git")
    api = f"https://api.github.com/repos/{owner}/{repo}"
    meta = json.loads(get(api, accept="application/vnd.github+json"))
    pushed = meta.get("pushed_at")
    days = None
    if pushed:
        days = (datetime.now(timezone.utc) - datetime.fromisoformat(pushed.replace("Z", "+00:00"))).days
    out = {"repo": {
        "來源": api, "描述": meta.get("description"), "主要語言": meta.get("language"),
        "星數": meta.get("stargazers_count"), "主題標籤": meta.get("topics"),
        "最後 push": pushed, "距今天數": days,
        "已封存": meta.get("archived"), "授權": (meta.get("license") or {}).get("spdx_id"),
    }}
    for branch in (meta.get("default_branch"), "master", "main"):
        if not branch:
            continue
        try:
            raw = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/README.md"
            out["readme"] = {"來源": raw, "內容": get(raw)[:6000]}
            break
        except urllib.error.HTTPError:
            continue
    return out


def harvest_github_user(url):
    who = re.search(r"github\.com/([^/?#]+)", url).group(1)
    api = f"https://api.github.com/users/{who}/repos?sort=pushed&per_page=10"
    repos = json.loads(get(api, accept="application/vnd.github+json"))
    out = {"user_repos": {"來源": api, "帳號": who, "repo": [
        {"名稱": r["full_name"], "描述": r.get("description"), "語言": r.get("language"),
         "星數": r["stargazers_count"], "最後 push": r["pushed_at"]} for r in repos]}}
    # github 欄位只給帳號頁時，往下抓星數最高的那個 repo——
    # 否則 org 只會留下十個名字，沒有任何可讀的內容。抓到的東西交給 relevance_guard 判斷。
    if repos:
        top = max(repos, key=lambda r: r["stargazers_count"])
        try:
            got = harvest_github_repo(top["html_url"])
            got["repo"]["註記"] = f"這是帳號 {who} 底下星數最高的 repo，不是資料庫直接指定的"
            got["repo"]["可信度"] = "待驗證"
            out.update(got)
        except Exception as e:
            out["user_repos"]["最熱門 repo 抓取失敗"] = f"{type(e).__name__}: {e}"
    return out


def relevance_guard(pack):
    """標出「抓到了、但可能不是這個專案」的素材。

    實證（2026-09-19）：零時空汙觀測網的 github 欄位填的是個人帳號頁，
    往下抓星數最高的 repo 會抓到 ASPER HALO——開發者另一個跟空汙完全無關的專案，
    README 有 3354 字。素材如果只標「抓到了」，AI 會很有自信地把它寫成這個專案的介紹。

    判準刻意很笨：專案名、英文名、標籤裡的詞，有沒有出現在 repo 的名稱或描述裡。
    笨的判準會誤標一些其實相關的，那沒關係——**誤標的代價是「人去看一眼」，
    漏標的代價是「網站上出現一篇查不出錯的假介紹」。這個站的全部資產就是可信度。**
    """
    name = pack["專案"]
    fields = pack["資料庫欄位"]
    terms = set()
    for t in [name, fields.get("project name EN", "")] + fields.get("標籤", []):
        for w in re.split(r"[\s／/｜|、,，_-]+", (t or "").lower()):
            if len(w) >= 2:
                terms.add(w)
    # 中文再切成 2 字一組：「零時空汙觀測網」不會整串出現在 repo 名稱裡
    low = (name or "").lower()
    for i in range(len(low) - 1):
        if re.match(r"[一-鿿]{2}", low[i:i + 2]):
            terms.add(low[i:i + 2])

    repo = pack["素材"].get("repo")
    if not repo or repo.get("可信度") != "待驗證":
        return pack
    hay = f"{repo.get('來源','')} {repo.get('描述','') or ''} {' '.join(repo.get('主題標籤') or [])}".lower()
    hit = sorted(t for t in terms if t and t in hay)
    if hit:
        repo["可信度"] = f"名稱或描述對得上專案（命中：{'、'.join(hit[:5])}）"
    else:
        repo["可信度"] = "⚠️ 對不上專案名稱或標籤——很可能不是這個專案，產生 insight 時不得引用"
        if "readme" in pack["素材"]:
            pack["素材"]["readme"]["可信度"] = "⚠️ 同上，來源 repo 的歸屬未能確認"
    return pack


def harvest(project):
    f = project["fields"]
    name = (f.get("project name") or "").strip()
    pack = {"專案": name, "取得日期": TODAY, "資料庫欄位": {}, "素材": {}, "抓不到": []}

    for k in ("Intro", "project name EN"):
        if (f.get(k) or "").strip():
            pack["資料庫欄位"][k] = f[k].strip()
    pack["資料庫欄位"]["影響力類別"] = [c["name"] for c in f.get("影響力類別", [])]
    pack["資料庫欄位"]["標籤"] = [t["name"] for t in f.get("標籤", [])]

    # 討論在哪裡：insight 的「討論在哪裡」那一行主要靠這兩欄（2026-10-19）。
    # 只帶欄位值，不去抓頻道內容——封存站「最後發言」多半是加入／離開訊息，不能當活動訊號。
    slack = (f.get("slack channel") or "").strip().lstrip("#")
    if slack:
        pack["資料庫欄位"]["slack channel"] = f"#{slack}（g0v Slack）"
    if f.get("non-slack"):
        pack["資料庫欄位"]["non-slack"] = f["non-slack"]

    for field in ("github", "Website URL", "document", "Facebook Page Link"):
        url = (f.get(field) or "").strip()
        if not url:
            continue
        kind = classify(url)
        try:
            if kind == "github_repo":
                pack["素材"].update(harvest_github_repo(url))
            elif kind == "github_user":
                pack["素材"].update(harvest_github_user(url))
            elif kind in ("hackmd", "gdoc"):
                text = doc_text(url)
                pack["素材"][f"網頁:{url}"] = {"來源": url, "正文前 3000 字": text[:3000], "全文長度": len(text)}
            elif kind == "web":
                try:
                    text = page_text(url)
                    if BOT_WALL.search(text[:500]):
                        pack["抓不到"].append(f"{url}（{field} 欄位，站方用驗證頁擋自動程式，依其意願不繞過）")
                        continue
                    dead = DEAD_PAGE.search(text[:500])
                except Exception as e:
                    text, dead = "", f"{type(e).__name__}: {e}"
                if dead:
                    if not isinstance(dead, str):
                        dead = f"只剩「{dead.group(0)}」"
                    try:
                        snap = wayback(url, name_terms(name, f.get("project name EN", "")))
                    except Exception as e:
                        raise RuntimeError(f"{dead}；{e}") from e
                    if not snap:
                        raise RuntimeError(f"{dead}；網際網路檔案館也沒有快照")
                    pack["抓不到"].append(f"{url}（{field} 欄位，{dead}；改用 {snap['快照日期']} 的快照）")
                    pack["素材"][f"網頁:{snap['來源']}"] = snap
                else:
                    pack["素材"][f"網頁:{url}"] = {"來源": url, "正文前 3000 字": text[:3000], "全文長度": len(text)}
            elif kind == "facebook":
                pack["抓不到"].append(f"{url}（Facebook 有登入牆，機器取不到）")
            elif kind == "hackfoldr":
                pack["素材"][f"網頁:{url}"] = harvest_hackfoldr(url)
        except Exception as e:
            pack["抓不到"].append(f"{url}（{field} 欄位，{type(e).__name__}: {e}）")

    # 一個網址都沒有的專案，退而求其次：用專案名稱去比對 g0v HackMD 封存的共筆標題。
    if not any((f.get(k) or "").strip() for k in ("github", "Website URL", "document", "Facebook Page Link")):
        for note in archive_notes(name, f.get("project name EN", "")):
            try:
                text = get_hackmd(note["網址"])
            except Exception as e:
                pack["抓不到"].append(f"{note['網址']}（封存比對到的共筆，{type(e).__name__}: {e}）")
                continue
            pack["素材"][f"網頁:{note['網址']}"] = {
                "來源": note["網址"], "取得方式": f"專案沒有任何網址；以名稱比對 g0v HackMD 封存標題「{note['標題']}」",
                "正文前 3000 字": text[:3000], "全文長度": len(text)}

    # 大松發表紀錄：專案的歷程（event+date）與人力需求（manpower）。
    # 只涵蓋得到三、四十個專案，但那是現成的、不需要抓網頁的。
    talks = json.load(open(os.path.join(DATA, "talks.json")))["records"]
    hits = []
    for t in talks:
        tf = t["fields"]
        if (tf.get("related project") and name in str(tf["related project"])) \
           or (tf.get("presentation name") or "").strip() == name:
            hits.append({"場次": tf.get("event name"), "日期": tf.get("date"),
                         "需要的人力": tf.get("manpower"), "影片": tf.get("video link")})
    if hits:
        pack["素材"]["大松發表紀錄"] = {"來源": "civictech-tw-data / talks.json", "場次": hits}

    return relevance_guard(pack)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("用法：python3 scripts/insight-harvest.py <專案名稱的一部分>")
    projs = json.load(open(os.path.join(DATA, "projects.json")))["records"]
    key = sys.argv[1]
    hit = [p for p in projs if key in (p["fields"].get("project name") or "")]
    if not hit:
        sys.exit(f"找不到符合「{key}」的專案")
    print(json.dumps(harvest(hit[0]), ensure_ascii=False, indent=1))
