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
import json, os, re, sys, time, urllib.parse, urllib.request, urllib.error
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
        return r.read().decode("utf-8", "replace")


def get_page(url, timeout=20):
    """先用老實的 UA，被擋再換瀏覽器 UA 試一次。
    有些站台擋的是沒見過的 UA 而不是機器本身。"""
    try:
        return get(url, timeout)
    except urllib.error.HTTPError as e:
        if e.code in (403, 406, 429):
            return get(url, timeout, browser=True)
        raise


EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")


def get_hackmd(url):
    """HackMD 的頁面是 JS 編輯器，直接抓只拿到外殼；加 /download 才是原始 Markdown。
    共筆裡常留聯絡 email，先遮掉，免得一路被抄進 insight。"""
    base = re.sub(r"[?#].*$", "", url).rstrip("/")
    return EMAIL.sub("[email]", get(base + "/download"))


# 網站還回 200，但內容已經不是專案本身：伺服器預設頁、停放網域
DEAD_PAGE = re.compile(r"Apache2 \w+ Default Page|Welcome to nginx|domain (is|may be) for sale|This domain has expired")


def wayback(url):
    """網站失效時查網際網路檔案館最後一個正常的快照。
    快照日期一定要帶著走：它描述的是那一天的專案，不是現在的。"""
    api = ("https://web.archive.org/cdx/search/cdx?output=json&limit=-1"
           "&filter=statuscode:200&filter=mimetype:text/html&url=" + urllib.parse.quote(url, safe=""))
    for wait in (0, 15, 45):  # 檔案館很容易回 429，等一下通常就好
        time.sleep(wait)
        try:
            rows = json.loads(get(api, timeout=30) or "[]")
            break
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
    else:
        return None
    if len(rows) < 2:
        return None
    ts, original = rows[-1][1], rows[-1][2]
    snap = f"https://web.archive.org/web/{ts}/{original}"
    text = strip_html(get(f"https://web.archive.org/web/{ts}id_/{original}", timeout=30))
    return {"來源": snap, "快照日期": f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}",
            "正文前 3000 字": text[:3000], "全文長度": len(text)}


def classify(url):
    u = url.strip()
    if re.match(r"https?://([\w-]+\.)?hackmd\.io/(?!\?)[^?#]+", u):
        return "hackmd"
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
            elif kind == "hackmd":
                text = get_hackmd(url)
                pack["素材"][f"網頁:{url}"] = {"來源": url, "正文前 3000 字": text[:3000], "全文長度": len(text)}
            elif kind == "web":
                try:
                    text = strip_html(get_page(url))
                    dead = DEAD_PAGE.search(text[:500])
                except Exception as e:
                    text, dead = "", f"{type(e).__name__}: {e}"
                if dead:
                    if not isinstance(dead, str):
                        dead = f"只剩「{dead.group(0)}」"
                    snap = wayback(url)
                    if not snap:
                        raise RuntimeError(f"{dead}；網際網路檔案館也沒有快照")
                    pack["抓不到"].append(f"{url}（{field} 欄位，{dead}；改用 {snap['快照日期']} 的快照）")
                    pack["素材"][f"網頁:{snap['來源']}"] = snap
                else:
                    pack["素材"][f"網頁:{url}"] = {"來源": url, "正文前 3000 字": text[:3000], "全文長度": len(text)}
            elif kind == "facebook":
                pack["抓不到"].append(f"{url}（Facebook 有登入牆，機器取不到）")
            elif kind == "hackfoldr":
                pack["抓不到"].append(f"{url}（hackfoldr 內容由 JS 載入，抓到的是外殼）")
        except Exception as e:
            pack["抓不到"].append(f"{url}（{field} 欄位，{type(e).__name__}: {e}）")

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
