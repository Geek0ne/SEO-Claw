#!/usr/bin/env python3
"""只重跑 canonical.conflict，把每条的判定理由原样打出来。

背景
----
107 站全集核对报「canonical.conflict 误报 11 / 噪音 9」，但汇总里列的样本
全是「仅 path 大小写不同」——那是 _canon_key 分支产出的 noisy，不是误报。
也就是说**汇总展示的样本和计数不是同一批**，我对着样本看不出 11 条是什么。

核对的三个来源：4 个 ok 站、10 个早报 2~4 条的站、1 个「全错但唯一没改
完的站」golf.com → 合计 17 站，误报 2+2+3+1+3=11。

做法：复用 verify_findings 的 fetch/verify，不重写一遍逻辑——
重写就会出现「核对器和我以为的核对器不是同一个」这种更糟的情况。
"""
import glob
import json
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, "/root/.openclaw/workspace/SEOClaw/tools")
from verify_findings import fetch, verify  # noqa: E402

rows = []
for f in glob.glob("/root/.openclaw/workspace/SEOClaw/reports/fp_json_v4/*.json"):
    d = json.load(open(f, encoding="utf-8"))
    for iss in d.get("issues", []):
        if iss.get("code") == "canonical.conflict":
            rows.append((iss["url"], d.get("domain", ""), iss.get("evidence") or {}))

print(f"canonical.conflict 共 {len(rows)} 条，逐条重判…\n", file=sys.stderr)


def work(r):
    url, dom, ev = r
    try:
        v = verify("canonical.conflict", url, fetch(url), ev)
        return dom, url, ev, v.state, v.note
    except Exception as e:  # noqa: BLE001
        return dom, url, ev, "error", f"{type(e).__name__}: {str(e)[:60]}"


with ThreadPoolExecutor(max_workers=6) as ex:
    out = list(ex.map(work, rows))

tally = {}
for dom, url, ev, state, note in out:
    tally[state] = tally.get(state, 0) + 1
    print(f"[{state:14}] {dom:26} {url[:44]}")
    print(f"                 canonical={str(ev.get('canonical'))[:56]}")
    print(f"                 {note[:100]}")

print("\n=== 判定分布 ===")
for k, v in sorted(tally.items(), key=lambda x: -x[1]):
    print(f"  {k:16} {v}")
