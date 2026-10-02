#!/usr/bin/env python3
"""审计 _looks_bot_blocked 的 markers 到底命中了什么。

为什么必须查：改成「只认反爬标记」后，可判定从 398 掉到 283，**115 条样本
被我推出了分母**。这个数字要站得住，就得证明每一条推出分母的样本是真的
被服务器挡了，而不是 marker 误伤。

最大嫌疑：`"captcha"` 是纯子串匹配。任何一个讲验证码的正常技术博客、
任何挂了 reCAPTCHA 脚本但正常返回内容的页面，都会命中——那不是被挡，
那是页面内容提到了「captcha」。这类误伤会把合法样本推出分母，
又变成一次「调口径换数字」。
"""
from __future__ import annotations

import concurrent.futures as cf
import glob
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict

UA = "Mozilla/5.0 (compatible; SEOAgentAudit/1.0; +https://example.com/bot)"
MARKERS = (
    "access denied", "just a moment", "checking your browser",
    "enable javascript and cookies", "cf-browser-verification",
    "attention required", "request unsuccessful", "captcha",
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


def visible_len(h: str) -> int:
    t = re.sub(r"<(script|style|nav|footer)[^>]*>.*?</\1>", " ", h, flags=re.I | re.S)
    return len(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t)).strip())


rows: list[tuple[str, str, list[str], int, int]] = []
urls: set[str] = set()
for p in sorted(glob.glob("reports/fp_json_v3/*.json")):
    d = json.load(open(p))
    for iss in d.get("issues", []):
        if iss.get("url"):
            urls.add(iss["url"])

print(f"待取 {len(urls)} 个 URL…", file=sys.stderr)


def work(u: str):
    h = fetch(u)
    if h is None:
        return (u, None, [], 0, 0)
    body = h.lower()
    hit = [m for m in MARKERS if m in body]
    return (u, h, hit, len(h), visible_len(h))


with cf.ThreadPoolExecutor(max_workers=12) as ex:
    for u, h, hit, raw, vis in ex.map(work, sorted(urls)):
        if hit:
            rows.append((u, ",".join(hit), hit, raw, vis))

print(f"\n命中 markers 的 URL: {len(rows)} / {len(urls)}")
print("\n--- 哪个 marker 命中最多 ---")
for m, n in Counter(m for _, _, hs, _, _ in rows for m in hs).most_common():
    print(f"  {m:32} {n}")

print("\n--- 可疑：正文很长却命中 captcha 的（页面在讲验证码，不是被挡）---")
susp = [r for r in rows if "captcha" in r[2] and r[4] > 1500]
for u, _, hs, raw, vis in susp[:12]:
    print(f"  正文{vis:6}字 HTML{raw:8}B  [{hs}]  {u[:78]}")
print(f"  ...共 {len(susp)} 条")

print("\n--- 正文极短的（这些才是真被挡）---")
real = [r for r in rows if r[4] < 500]
print(f"  共 {len(real)} 条，marker 分布:",
      dict(Counter(m for r in real for m in r[2])))

print("\n--- 结论用：真被挡 vs 误伤 ---")
print(f"  疑似误伤（正文>1500 字）: {len(susp)}")
print(f"  疑似真被挡（正文<500 字）: {len(real)}")
print(f"  灰区（500~1500 字）:      {len(rows) - len(susp) - len(real)}")
