#!/usr/bin/env python3
"""回原站核对 batch200 报出的问题。

为什么要回源：报告里的结论是「我们的解析层看到什么」，
而用户关心的是「页面里到底有没有」。两者一旦不一致——
就是误报。之前 agoda 就是这么发现的：静态 HTML 里真没 title，
但那是 JS 注入的，解析层拿不到 ≠ 页面没有。

所以这里**不重跑我们的规则**，直接 curl 原始 HTML grep。
这样才是独立的第二意见。

用法：python3 tools/verify_batch.py <rule_code> [样本数]
"""
import glob
import json
import re
import subprocess
import sys
import collections
from urllib.parse import urlparse

UA = "Mozilla/5.0 (compatible; SEO-ClawVerifier/1.0)"

# 每条规则的核对方式：返回 (回源后的真实状态, 结论)
#   结论 ∈ {'true' 真的有问题, 'false' 误报, 'unsure' 没法判}
def check_meta_missing(html, iss):
    if re.search(r'<meta[^>]+name=["\']description["\']', html, re.I):
        return "有 description", "false"
    if re.search(r"<noscript", html, re.I) or "window\.__NUXT__" in html or "__NEXT_DATA__" in html:
        return "静态没有，但像 JS 注入", "unsure"
    return "原始 HTML 里确实没有", "true"

def check_canonical_missing(html, iss):
    if re.search(r'<link[^>]+rel=["\']canonical["\']', html, re.I):
        return "有 canonical", "false"
    if re.search(r"<noscript", html, re.I) or "__NEXT_DATA__" in html:
        return "静态没有，但像 JS 注入", "unsure"
    return "原始 HTML 里确实没有", "true"

def check_h1_missing(html, iss):
    if re.search(r"<h1[\s>]", html, re.I):
        return "有 h1", "false"
    return "原始 HTML 里确实没有 h1", "true"

def check_sitemap_missing(html, iss):
    return None, "unsure"  # sitemap 要单独请求 robots.txt，交给专门的逻辑

def check_title_too_long(html, iss):
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if not m:
        return "原始 HTML 里没有 title", "unsure"
    t = re.sub(r"\s+", " ", m.group(1)).strip()
    lim = iss.get("evidence", {}).get("threshold") or iss.get("evidence", {}).get("limit")
    n = len(t)
    return f"title 实际 {n} 字：{t[:60]!r}", None if lim is None else ("true" if n > int(lim) else "false")

def check_img_alt_missing(html, iss):
    imgs = re.findall(r"<img\b[^>]*>", html, re.I)
    no_alt = [i for i in imgs if not re.search(r'\balt\s*=', i, re.I)]
    empty = [i for i in imgs if re.search(r'\balt\s*=\s*["\']\s*["\']', i, re.I)]
    return f"img 共 {len(imgs)}，无 alt 属性 {len(no_alt)}，alt 为空 {len(empty)}", None

CHECKERS = {
    "meta.missing": check_meta_missing,
    "canonical.missing": check_canonical_missing,
    "h1.missing": check_h1_missing,
    "title.too_long": check_title_too_long,
    "img.alt.missing": check_img_alt_missing,
}


def fetch(url, timeout=25):
    """只取原始 HTML 前 400KB。"""
    try:
        r = subprocess.run(
            ["curl", "-sL", "--compressed", "-m", str(timeout),
             "-A", UA, "--max-filesize", "4000000", url],
            capture_output=True, timeout=timeout + 10,
        )
        return r.stdout.decode("utf-8", "replace")
    except Exception as e:
        return ""


def main():
    code = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    checker = CHECKERS.get(code)
    if not checker:
        print(f"没写 {code} 的核对逻辑；已支持：{', '.join(CHECKERS)}")
        return 1

    # 同一站同一 URL 只核对一次
    targets, seen = [], set()
    for f in sorted(glob.glob("reports/batch200/*.json")):
        d = json.load(open(f))
        for iss in d.get("issues", []):
            if iss.get("code") != code:
                continue
            u = iss.get("url")
            if u and u not in seen:
                seen.add(u)
                targets.append((d["domain"], u, iss))
    random = targets[:limit]

    print(f"=== {code}：{len(targets)} 条待核，抽 {len(random)} 条回原站\n")
    tally = collections.Counter()
    for domain, url, iss in random:
        host = urlparse(url).netloc
        html = fetch(url)
        if not html:
            tally["抓不到"] += 1
            print(f"  ?? {host:<28} 回源抓不到")
            continue
        detail, verdict = checker(html, iss)
        tally[verdict] += 1
        mark = {"true": "真问题", "false": "误报 ", "unsure": "存疑 "}[verdict]
        print(f"  {mark} {host:<28} {detail}")

    print(f"\n=== 小结：真问题 {tally['true']} · 误报 {tally['false']} "
          f"· 存疑 {tally['unsure']} · 抓不到 {tally['抓不到']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
