#!/usr/bin/env python3
"""量 soft404 的 68 条存疑：到底有没有可判别的信号。

背景
----
soft404 规则的判据是「HTTP 200 + 正文 < 300 词」。核对器现在一律判
unknown，理由是「需人工看内容」。但现场样本看，这个 unknown 里混着
两类完全不同的东西：

  A 真软 404：页面确实没内容
  B JS 渲染页：静态 HTML 里正文抽不出几个字，但页面本身是有结构的

B 类的典型特征很硬：japanpost.jp 首页 evidence 里写着
`internal_outbound_links: 213` —— 213 条内链的页面不可能是软 404，
那只是 trafilatura 没抽出正文（页面靠 JS 渲染）。

⚠️ 这里最容易犯的错，是看到「正文少」就判「没拿到页面」，把 B 类
也踢出分母——我今晚已经这么干过两次（95.2%→96.0% 那 0.8 个点，
以及 captcha 那次 60 条正常页面被误伤）。所以先量，看看判别式
到底能不能立住，立不住就老实说立不住。
"""
from __future__ import annotations

import glob
import json
from collections import Counter

rows = []
for p in sorted(glob.glob("reports/fp_json_v3/*.json")):
    d = json.load(open(p, encoding="utf-8"))
    for it in d.get("issues", []):
        if it["code"] == "soft404":
            rows.append((d["domain"], it.get("url") or "", it.get("evidence") or {}))

print(f"soft404 共 {len(rows)} 条\n")

# 候选判别式：都是 evidence 里已经有的字段，不新增依赖
CANDIDATES = {
    "内链 >= 20": lambda e: (e.get("internal_outbound_links") or 0) >= 20,
    "内链 >= 5": lambda e: (e.get("internal_outbound_links") or 0) >= 5,
    "入链 == 0 且 内链 == 0": lambda e: (e.get("inbound_links") or 0) == 0
    and (e.get("internal_outbound_links") or 0) == 0,
    "url_looks_like_index": lambda e: bool(e.get("url_looks_like_index")),
    "正文 < 100 词": lambda e: (e.get("word_count") or 0) < 100,
}

for name, fn in CANDIDATES.items():
    hit = [r for r in rows if fn(r[2])]
    print(f"  {name:24} 命中 {len(hit):3} / {len(rows)}")

print("\n=== 内链数分布 ===")
for k, n in sorted(Counter((e.get("internal_outbound_links") or 0) for _d, _u, e in rows).items()):
    print(f"  内链 {k:5} → {n:3} 条")

print("\n=== 内链 >= 20 的站（这类不该是软 404）===")
for d, u, e in rows:
    if (e.get("internal_outbound_links") or 0) >= 20:
        print(f"  {d:28} 内链{e.get('internal_outbound_links'):5} 词{e.get('word_count'):5}")

print("\n=== 内链 == 0 的站（这类才可能是真软 404）===")
z = [r for r in rows if not (r[2].get("internal_outbound_links") or 0)]
for d, u, e in z[:15]:
    print(f"  {d:28} 词{e.get('word_count'):5} 入链{e.get('inbound_links')} {u[:44]}")
print(f"  ...共 {len(z)} 条")
