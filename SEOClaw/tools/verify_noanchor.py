#!/usr/bin/env python3
"""按提取层的真实判据，回源核对 link.noanchor。

前两版核对器都把这条判错了，教训：

1. 只看可见文字 → 漏掉 6 层兜底里的 `img alt` / `aria-label` / `title` /
   子元素 aria-label / SVG <title> / 视觉隐藏文字。slashdot 的
   `<a ... title="Trang chủ">` 就是这样被我错判成空锚的。
2. 把「包着 img」当装饰 → 比规则宽。规则只认 `<a>` 自身带
   `aria-hidden="true"` 或 `tabindex="-1"`（见 extract.py `_is_decorative`）。

所以这里逐条对齐 `extract._anchor_text` 的 6 层 + `_is_decorative` 的 2 条，
外加 `_extract_links` 跳过的 javascript:/#/mailto/tel。

用法：python3 tools/verify_noanchor.py [样本数]
"""
import glob
import json
import re
import subprocess
import sys
import collections
from urllib.parse import urlparse

UA = "Mozilla/5.0 (compatible; SEOClawVerifier/1.0)"
# 判定三态。真问题 / 误报 / 存疑——「没测到」既不是真问题也不是误报。
TRUE, FALSE, UNSURE = "真问题", "误报", "存疑"


def fetch(url, timeout=20):
    try:
        r = subprocess.run(
            ["curl", "-sL", "--compressed", "-m", str(timeout), "-A", UA, url],
            capture_output=True, timeout=timeout + 10,
        )
        return r.stdout.decode("utf-8", "replace")
    except Exception:
        return ""


def anchor_text(attrs: str, inner: str) -> str:
    """对齐 extract._anchor_text 的 6 层兜底。"""
    # 1) 可见文字
    txt = re.sub(r"<[^>]+>", " ", inner)
    txt = re.sub(r"\s+", " ", txt).strip()
    if txt:
        return txt
    # 2) img alt
    for alt in re.findall(r"<img\b[^>]*?\balt\s*=\s*[\"']([^\"']*)", inner, re.I):
        if alt.strip():
            return alt.strip()
    # 3) <a> 自身的 aria-label / title / data-title
    for at in ("aria-label", "title", "data-title"):
        v = re.search(at + r"\s*=\s*[\"']([^\"']+)", attrs, re.I)
        if v and v.group(1).strip():
            return v.group(1).strip()
    # 4) 子元素上的 aria-label / data-title
    for v in re.findall(r"aria-label\s*=\s*[\"']([^\"']+)[\"']", inner, re.I):
        if v.strip():
            return v.strip()
    for v in re.findall(r"data-title\s*=\s*[\"']([^\"']+)[\"']", inner, re.I):
        if v.strip():
            return v.strip()
    # 5) SVG 内部 <title>
    for t in re.findall(r"<svg\b.*?<title[^>]*>(.*?)</title>", inner, re.I | re.S):
        v = re.sub(r"\s+", " ", t).strip()
        if v:
            return v
    # 6) 视觉隐藏文字
    for cls in ("visually-hidden", "sr-only", "screen-reader", "sr-only-text"):
        for node in re.findall(
            r"<[a-z]+[^>]*class=[\"'][^\"']*" + cls + r"[^\"']*[\"'][^>]*>(.*?)</[a-z]+>",
            inner, re.I | re.S,
        ):
            v = re.sub(r"<[^>]+>", "", node)
            v = re.sub(r"\s+", " ", v).strip()
            if v:
                return v
    return ""


def strip_invisible(raw: str) -> str:
    """去掉注释和 script/style/noscript —— 页面上看不见的东西不算链接。

    实测 slashdot：我 regex 到 270 个 <a>，其中 6 个藏在 <script>/<noscript>
    里。不去掉就会把 JS 模板里的字符串当成页面上的空锚。
    """
    out = raw
    for pat in (r"(?is)<!--.*?-->",
                r"(?is)<script\b.*?</script>",
                r"(?is)<style\b.*?</style>",
                r"(?is)<noscript\b.*?</noscript>"):
        out = re.sub(pat, " ", out)
    return out


def count_empty_anchors(html: str, host: str):
    """返回 (非装饰空锚数, 装饰空锚数, 抽到的总链接数)。"""
    empty = dec = total = 0
    for m in re.finditer(r"<a\b([^>]*)>(.*?)</a>", strip_invisible(html), re.I | re.S):
        attrs, inner = m.group(1), m.group(2)
        href = re.search(r"href\s*=\s*[\"']?([^\"'\s>]*)", attrs, re.I)
        if not href:
            continue
        raw = href.group(1).strip()
        # _extract_links 跳过的形态
        if not raw or raw.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absolute = raw if raw.startswith("http") else f"https://{host}{raw if raw.startswith('/') else '/' + raw}"
        u = urlparse(absolute)
        if u.netloc and u.netloc.replace("www.", "") != host.replace("www.", ""):
            continue  # 只数 internal
        total += 1
        if anchor_text(attrs, inner).strip():
            continue
        # _is_decorative：只认 <a> 自身的 aria-hidden / tabindex
        if (re.search(r"aria-hidden\s*=\s*[\"']true[\"']", attrs, re.I)
                or re.search(r"tabindex\s*=\s*[\"']-1[\"']", attrs, re.I)):
            dec += 1
        else:
            empty += 1
    return empty, dec, total


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    targets, seen = [], set()
    for f in sorted(glob.glob("reports/batch200/*.json")):
        d = json.load(open(f))
        for iss in d.get("issues", []):
            if iss.get("code") != "link.noanchor" or not iss.get("url"):
                continue
            if iss["url"] in seen:
                continue
            seen.add(iss["url"])
            targets.append((d["domain"], iss))

    sample = targets[:limit]
    print(f"=== link.noanchor（对齐 6 层兜底的核对器）：{len(targets)} 条待核，"
          f"抽 {len(sample)}\n", flush=True)
    tally = collections.Counter()
    for domain, iss in sample:
        html = fetch(iss["url"])
        if not html:
            tally["抓不到"] += 1
            print(f"  ?? {domain:<24} 回源抓不到", flush=True)
            continue
        want = iss["evidence"].get("empty_anchor_count")
        empty, dec, total = count_empty_anchors(html, domain)
        # ⚠️ 判据：**不要求两者相等**。
        #
        # 我第一版写的是 empty == want，结果 34 条里 15 条判成误报。实跑看：
        #   - slashdot 规则报 6、我数 24 → 规则报的是**子集**，它**少报**不是报错。
        #     这跟 img.alt.missing 是同一个错（那边 1 vs 21），我改了那边忘了改这边。
        #   - www.csdn.net 规则报 25、我数 1；edx 规则报 11、我数 0 → 页面变了
        #     或要渲染，**这该记存疑**，跟 airbnb 跳去 zh.airbnb.com 一个道理。
        #
        # 正向证据：原文里确实存在 >= want 个真空锚，且 want >= 2（规则阈值）→ 真问题。
        # 我数得比规则少 → 存疑，不是我能判的。
        if want is None:
            verdict, mark = UNSURE, "存疑 "
        elif empty >= want >= 2:
            verdict, mark = TRUE, "真问题"
        elif empty < want:
            verdict, mark = UNSURE, "存疑 "
        else:
            verdict, mark = FALSE, "误报 "
        tally[mark.strip()] += 1
        note = ""
        if empty > want:
            note = f"（我多数 {empty - want} 个——规则报的是子集）"
        elif empty < want:
            note = f"（我少数 {want - empty} 个，页面可能变了）"
        print(f"  {mark} {domain:<24} 规则报 {want} · 实测 {empty}"
              f"（内链 {total}，装饰性空锚 {dec}）{note}", flush=True)

    print(f"\n=== 小结：真问题 {tally['真问题']} · 误报 {tally['误报']} "
          f"· 存疑 {tally['存疑']} · 抓不到 {tally['抓不到']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
