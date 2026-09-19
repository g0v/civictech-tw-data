#!/usr/bin/env python3
"""掃過資料庫裡所有專案網址，回報哪些還活著。

用法：python3 scripts/linkcheck.py
沒有相依套件，只用標準函式庫。全部掃一輪約三分鐘。

不用 AI，所以不會有幻覺——這是它比 insight 可靠的地方。

會分四類：
  OK      能打開
  轉址    最後打得開，但落在不同網域（老專案的網域過期被搶註就是長這樣，
          對公益站來說比 404 更傷：連出去變成廣告或賭博站）
  死掉    4xx / 5xx
  連不上  DNS 查不到、逾時、憑證錯誤

Facebook 一律標「無法判定」——它對機器回登入牆，狀態碼是 200，
但那不代表那個粉專還在。把它算成 OK 會讓報告說謊。
"""
import json, os, socket, ssl, sys, threading, time
import urllib.request, urllib.error, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "data", "v0", "tech")
OUT = os.path.join(REPO, "reports")
TW = timezone(timedelta(hours=8))
TODAY = datetime.now(TW).strftime("%Y-%m-%d")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36",
      "Accept-Language": "zh-TW,zh;q=0.9"}

host_lock = {}
lock = threading.Lock()


def polite(host):
    """同一個網域至少隔 0.4 秒再打一次——g0v.tw 底下掛著幾十個專案。"""
    with lock:
        last = host_lock.get(host, 0)
        wait = max(0, 0.4 - (time.time() - last))
        host_lock[host] = time.time() + wait
    if wait:
        time.sleep(wait)


def root(host):
    parts = (host or "").lower().split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


BLOCKED = {401, 403, 406, 429}


def follow(url, hops=5):
    """自己處理轉址。

    urllib 的預設 redirect handler 不跟 308，地方淨零觀測站因此被第一版誤判成死掉。
    寧可自己走這幾跳，也不要把「搬家了」報成「壞掉了」。
    """
    seen = []
    cur = url
    for _ in range(hops):
        req = urllib.request.Request(cur, headers=UA, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, r.geturl(), seen
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                seen.append(cur)
                cur = urllib.parse.urljoin(cur, e.headers["Location"])
                continue
            raise
    return None, cur, seen


def check(url):
    p = urlparse(url)
    if not p.scheme.startswith("http"):
        return {"狀態": "略過", "說明": "不是 http 網址"}
    if "facebook.com" in p.netloc:
        return {"狀態": "無法判定", "說明": "Facebook 對機器回登入牆，狀態碼不能當作還活著"}
    polite(p.netloc)
    try:
        status, final, _ = follow(url)
        moved = root(urlparse(final).netloc) != root(p.netloc)
        return {"狀態": "轉址" if moved else "OK", "碼": status,
                "最終網址": final if moved else None,
                "說明": f"落到 {urlparse(final).netloc}" if moved else ""}
    except urllib.error.HTTPError as e:
        # 403 不是死掉，是站台擋自動檢查。Cofacts 官網回 403，
        # 但它的 repo 三天前還在 push——把「擋我」當成「死了」，
        # 會叫人去修沒有壞的東西。
        if e.code in BLOCKED:
            return {"狀態": "擋機器", "碼": e.code,
                    "說明": f"HTTP {e.code}：站台擋自動檢查，不代表壞掉，要人工開一次"}
        return {"狀態": "死掉", "碼": e.code, "說明": f"HTTP {e.code}"}
    except (urllib.error.URLError, socket.timeout, ssl.SSLError, ConnectionError) as e:
        reason = getattr(e, "reason", e)
        return {"狀態": "連不上", "說明": f"{type(reason).__name__}: {reason}"}
    except Exception as e:
        return {"狀態": "連不上", "說明": f"{type(e).__name__}: {e}"}


def main():
    projs = json.load(open(f"{DATA}/projects.json"))["records"]
    jobs = []
    for p in projs:
        f = p["fields"]
        name = (f.get("project name") or "").strip()
        for field in ("Website URL", "github", "document", "Facebook Page Link"):
            u = (f.get(field) or "").strip()
            if u.startswith("http"):
                jobs.append({"專案": name, "欄位": field, "網址": u})

    print(f"{len(jobs)} 個網址要掃，開始…", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda j: {**j, **check(j["網址"])}, jobs))

    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"link-health-{TODAY}.json")
    json.dump({"掃描日期": TODAY, "網址數": len(results), "結果": results},
              open(path, "w"), ensure_ascii=False, indent=1)
    print(f"\n結果寫到 {os.path.relpath(path, REPO)}", file=sys.stderr)

    from collections import Counter
    c = Counter(r["狀態"] for r in results)
    print(f"\n掃描日期 {TODAY}，共 {len(results)} 個網址")
    for k, v in c.most_common():
        print(f"  {k:6} {v}")
    return results


if __name__ == "__main__":
    main()
