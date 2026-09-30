#!/usr/bin/env python3
"""量「HTML 体积 + 无可见文本」能不能分开真软 404 和 JS 外壳。

背景
----
软 404 规则我已经加了两道闸：full_text_length >= 800 排除、likely_js_rendered
排除。但 agoda 的 5 条还是漏了，因为 likely_js_rendered 要求「有框架标记」，
而 agoda 的 HTML 里 Vue 指令 0、reactroot 0、ng-app 0、__NUXT__ 0，
挂载点叫 ``<div id="agoda-spa">``——一个标准都不沾。

可 agoda 那个页面是 **734902 字节**、可见文本 **0 字**、内链 **0 条**。
734KB 的文档不可能是「内容匮乏的 200 空页」，它是一坨 JS 包。
**HTML 体积本身就是正面证据**，我却把它丢在一边去等框架标记。

⚠️ 但我不能因为「看起来对」就改阈值——今晚栽的每一次都是这么来的
（弯引号、page.text 有损、切词器、页面薄、captcha 子串）。
所以这里做的是**分组量测**：拿 16 条候选 + 一组已知正常的薄页面做对照，
看这个信号到底分不分得开，分不开就承认它分不开。

对照组的意义：规则该报的是「真的没内容的页」。如果一个阈值会把
「本来就薄但有效」的页一起放过去，那它就是在拿漏报换误报。
"""
from __future__ import annotations

import concurrent.futures as cf
import glob
import json
import re
import subprocess
import sys
from urllib.parse import urlparse

UA = "Mozilla/5.0 (compatible; SEOAgentAudit/1.0; +https://example.com/bot)"

MOUNT_RE = re.compile(r'id\s*=\s*["\'](root|app|__next|__nuxt|__gatsby)["\']', re.I)
FW_RE = re.compile(
    r"(<[a-z][^>]*\sv-[a-z][\w-]*\s*=)|(data-reactroot)|(ng-app|ng-version)"
    r"|(__NUXT__|__NEXT_DATA__|window\.___gatsby)",
    re.I,
)


def fetch(url: str) -> str | None:
    try:
        r = subprocess.run(
            ["curl", "-sL", "--max-time", "20", "-A", UA, url],
            capture_output=True, text=True, timeout=25,
        )
        return r.stdout if r.stdout and "<html" in r.stdout.lower() else None
    except Exception:
        return None


def full_text(h: str) -> str:
    t = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", h, flags=re.I | re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t)).strip()


def probe(url: str) -> dict | None:
    h = fetch(url)
    if h is None:
        return None
    return {
        "url": url,
        "bytes": len(h),
        "text": len(full_text(h)),
        "links": len(re.findall(r"<a\b[^>]*href\s*=", h, re.I)),
        "mount": bool(MOUNT_RE.search(h)),
        "fw": bool(FW_RE.search(h)),
        "script_kb": len(
            "".join(re.findall(r"<script[^>]*>(.*?)</script>", h, re.I | re.S))
        ) // 1024,
    }


# ── 候选：16 条被报出来的 soft404 ──
cands = []
for f in sorted(glob.glob("reports/fp_json_soft404b/*.json")):
    d = json.load(open(f, encoding="utf-8"))
    for i in d.get("issues", []):
        if i["code"] == "soft404":
            cands.append((d["domain"], i.get("url") or ""))

# ── 对照：已知内容饱满的 JS 站页面（不该被 soft404 报）──
CONTROLS = [
    ("www.github.com", "https://github.com/explore"),
    ("www.reddit.com", "https://www.reddit.com/"),
    ("www.notion.so", "https://www.notion.so/product"),
    ("stripe.com", "https://stripe.com/products"),
    ("www.airbnb.com", "https://www.airbnb.com/"),
    ("www.shopify.com", "https://www.shopify.com/"),
]

allrows = [("CAND", d, u) for d, u in cands] + [("CTRL", d, u) for d, u in CONTROLS]

with cf.ThreadPoolExecutor(max_workers=8) as ex:
    res = list(ex.map(lambda r: (r[0], r[1], probe(r[2])), allrows))

print(f"{'':5}{'站':22}{'HTML':>9}{'内联JS':>8}{'文本':>7}{'出链':>6}{'挂载':>5}{'框架':>5}")
print("-" * 78)
for tag, dom, m in res:
    if m is None:
        print(f"{tag:5}{dom:22}(取不到)")
        continue
    print(f"{tag:5}{dom:22}{m['bytes']:>9}{m['script_kb']:>7}K{m['text']:>7}"
          f"{m['links']:>6}{str(m['mount']):>5}{str(m['fw']):>5}")

# 分组量测
cand = [m for t, d, m in res if t == "CAND" and m]
ctrl = [m for t, d, m in res if t == "CTRL" and m]
print(f"\n候选 {len(cand)} 条 / 对照 {len(ctrl)} 条")

for th in (5000, 20000, 50000, 100000):
    hit_c = sum(1 for m in cand if m["bytes"] >= th)
    hit_x = sum(1 for m in ctrl if m["bytes"] >= th)
    print(f"  HTML >= {th:6}B   候选命中 {hit_c:2}/{len(cand)}   对照命中 {hit_x}/{len(ctrl)}"
          f"   {'← 候选全中且对照全不中' if hit_c == len(cand) and hit_x == 0 else ''}")

print("\n=== 候选里 HTML 体积排序（小 → 大）===")
for m in sorted(cand, key=lambda x: x["bytes"]):
    print(f"  {m['bytes']:>9}B  文本{m['text']:>5}  出链{m['links']:>4}  {m['url'][:52]}")
