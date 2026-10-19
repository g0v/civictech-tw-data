#!/usr/bin/env python3
"""檢查產生出來的 insight 合不合格式：四行、順序固定、每行不超過字數上限。

用法：python3 scripts/insight-check.py insights.jsonl
輸入每行一個 JSON：{"record_id": ..., "project": ..., "insight": "做什麼：…\n給誰、解決什麼：…\n…"}

字數不能靠 AI 自律，所以由這支程式把關；不合格的列出來退回重產，結束碼非 0。
"""
import json, re, sys

LINES = [("做什麼", 25), ("給誰、解決什麼", 40), ("怎麼運作", 40), ("討論在哪裡", 40)]
# 評價性形容詞：提示詞鐵則 4。只抓明顯的，誤報的代價是人多看一眼
PRAISE = re.compile(r"創新|成功|完善|廣受|重要的|優秀|領先|最好|有效地")


def check(text):
    errs = []
    rows = [r for r in text.strip().splitlines() if r.strip()]
    if len(rows) != len(LINES):
        return [f"應為 {len(LINES)} 行，實際 {len(rows)} 行"]
    for row, (label, cap) in zip(rows, LINES):
        if not row.startswith(label + "："):
            errs.append(f"「{row[:12]}…」應以「{label}：」開頭")
            continue
        body = row[len(label) + 1:].strip()
        if not body:
            errs.append(f"{label} 是空的（不知道要寫「不明」）")
        if len(body) > cap:
            errs.append(f"{label} {len(body)} 字，超過 {cap}")
        if PRAISE.search(body):
            errs.append(f"{label} 疑似評價性用語：{PRAISE.search(body).group()}")
    return errs


if __name__ == "__main__":
    bad = 0
    total = 0
    for n, line in enumerate(open(sys.argv[1]), 1):
        if not line.strip():
            continue
        total += 1
        rec = json.loads(line)
        errs = check(rec["insight"])
        if errs:
            bad += 1
            print(f"✗ {rec.get('project', rec.get('record_id'))}：" + "；".join(errs))
    print(f"{total} 則，{bad} 則不合格")
    sys.exit(1 if bad else 0)
