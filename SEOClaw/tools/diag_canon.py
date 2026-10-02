#!/usr/bin/env python3
"""查 canonical.conflict 那 8 条新误报：_content_same 是不是判太松。

背景
----
我给 canonical.conflict 加了「两个 URL 内容是否实质相同」的判定，想把
10 条 unknown 转成可判定。结果转出 8 条 false_positive，理由是
「canonical 指向 X，两页内容相同（合法归一）」。

**这个理由听起来对，但我不信。** 判据是正文词集合的 Jaccard >= 0.7。
词集合这东西在两个场景下会骗人：
  1. 站点导航/页脚文字占比高时，不同页面也会共享大量词
  2. 中文站用「字符 n-gram」切词，两个不同页面共享的模板字更多

所以必须把 8 条逐个打开看：canonical 指向哪、两页正文各是什么、
Jaccard 到底多少、词集合重叠是谁贡献的。
"""
from __future__ import annotations

import concurrent.futures as cf
import glob
import json
import re
import sys
from collections import Counter

sys.path.insert(0, "tools")
import verify_findings as vf  # noqa: E402

rows = []
for p in sorted(glob.glob("reports/fp_json_v3/*.json")):
    d = json.load(open(p, encoding="utf-8"))
    for iss in d.get("issues", []):
        if iss["code"] == "canonical.conflict" and iss.get("url"):
            rows.append((d["domain"], iss["url"], iss.get("evidence") or {}))

print(f"canonical.conflict 带 url 的共 {len(rows)} 条\n")


def work(r):
    dom, url, ev = r
    h = vf.fetch(url)
    if h is None:
        return dom, url, ev, None, None
    m = re.search(r"<link[^>]+rel\s*=\s*[\"']?canonical[^>]*>", h, re.I)
    href = (vf._attr(m.group(0), "href") or "") if m else ""
    href = href.rstrip("/")
    if not href or vf._canon_key(href) == vf._canon_key(url):
        return dom, url, ev, href, "前置分支(大小写/一致)"
    target = href if href.startswith("http") else vf._abs_url(url, href)
    th = vf.fetch(target)
    if th is None:
        return dom, url, ev, href, "目标页取不到"
    ta = set(w for w in re.findall(r"[a-z0-9一-鿿]{2,}", vf._visible_text(h).lower()))
    tb = set(w for w in re.findall(r"[a-z0-9一-鿿]{2,}", vf._visible_text(th).lower()))
    if not ta or not tb:
        return dom, url, ev, href, "有一侧正文为空"
    jac = len(ta & tb) / len(ta | tb)
    # 重叠词里，有多少是「只在两边都出现的模板/导航词」——用两侧词频差
    # 粗略区分：词数少的页面里这些词更可能是模板
    return dom, url, ev, href, (jac, len(ta), len(tb), ta & tb, vf._visible_text(h)[:110])


with cf.ThreadPoolExecutor(max_workers=8) as ex:
    res = list(ex.map(work, rows))

fp = 0
for dom, url, ev, href, info in res:
    if isinstance(info, tuple):
        jac, na, nb, inter, prev = info
        same = jac >= 0.7
        if same:
            fp += 1
        print(f"\n{'判 fp' if same else '判 tp'}  Jaccard={jac:.3f}  词数 {na}/{nb}")
        print(f"  页面 : {url[:78]}")
        print(f"  canon: {href[:78]}")
        print(f"  正文 : {prev!r}")
        print(f"  重叠词样例: {sorted(inter)[:14]}")
    else:
        print(f"\n--  {dom}: {info}")
print(f"\n其中判成 false_positive 的: {fp} 条")
