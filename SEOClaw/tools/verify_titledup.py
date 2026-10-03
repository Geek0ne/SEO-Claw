#!/usr/bin/env python3
"""回源核对 title.duplicate —— 跨页面比对 title，逐条不抽样。

这是 18 条规则里最后一条没核过的。前面几轮踩出来的坑，全部写进判据：

1. **curl 必须带 `Accept-Language: zh-CN`** —— crawler 带了，接了翻译的
   站点（Discourse / bellroy / airbnb）会整页机器翻译后返回。
   不带就拿到英文 title，跟报告里的中文 title 永远对不上。
2. **HTML 实体要解码** —— `&amp;` `&#x27;` 不解码则永不相等。
3. **规则报的是子集**，不要求相等；只要求「报的那些页面确实共用同一 title」。
4. **没测到 ≠ 不存在** —— 回访失败/超时/被挡，算 UNSURE，不算误报。

用法：python3 tools/verify_titledup.py
"""
import collections
import glob
import html as html_mod
import json
import re
import subprocess
import sys
from urllib.parse import urlparse

UA = "Mozilla/5.0 (compatible; SEOClawVerifier/1.0)"
TRUE, FALSE, UNSURE = "true", "false", "unsure"
MARK = {TRUE: "真问题", FALSE: "误报 ", UNSURE: "存疑 "}

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def fetch_title(url, timeout=15):
    """回访一个 URL，返回它的 title 和**最终落点 URL**。

    返回 (title, status, final_url)
    status ∈ ok / no_title / blocked / timeout

    为什么要 final_url：实测 airbnb.com 回访时跳到了 zh.airbnb.com，
    拿到的 title 是「重定向到zh.airbnb.com」——那跟当初抓的页面根本不是
    一回事。没有 final_url 就分不清「规则错了」和「页面跳走了」。
    """
    try:
        r = subprocess.run(
            ["curl", "-sL", "--compressed", "-m", str(timeout), "-A", UA,
             "-H", "Accept-Language: zh-CN,zh;q=0.9",
             "-w", "\n__M__%{http_code} %{url_effective}", url],
            capture_output=True, timeout=timeout + 8,
        )
        out = r.stdout.decode("utf-8", "replace")
    except Exception:
        return None, "timeout", None
    m = re.search(r"__M__(\d+)\s+(\S+)\s*$", out)
    if not m:
        return None, "timeout", None
    status_code = int(m.group(1))
    final_url = m.group(2)
    body = out[:m.start()]
    if status_code in (403, 429, 503):
        return None, "blocked", final_url
    tm = _TITLE_RE.search(body)
    if not tm:
        return None, "no_title", final_url
    title = html_mod.unescape(re.sub(r"\s+", " ", tm.group(1))).strip()

    # ⚠️ 域名切换壳：curl 停在原域，页面却是个 POST 表单壳。
    # 实测 airbnb.com → 返回 <title>重定向到zh.airbnb.com</title> +
    # <body onload="document.forms[0].submit()">，表单 POST 到
    # zh.airbnb.com/v2/domain_switch/handoff。curl -L 跟不动 POST，
    # 所以「最终 URL 换域了才存疑」这个守卫拦不住它 —— 域没变。
    # 判据：title 以「重定向/Redirect」开头，或 body 里有 domain_switch。
    if (re.match(r"(?i)^(重定向|redirect)", title)
            or "domain_switch" in body):
        return title, "domain_shell", final_url
    return title, "ok", final_url


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    issues = []
    for f in sorted(glob.glob("reports/batch200/*.json")):
        d = json.load(open(f))
        for iss in d.get("issues", []):
            if iss.get("code") == "title.duplicate":
                issues.append((d["domain"], iss))

    print(f"=== title.duplicate：{len(issues)} 条待核，抽 {min(limit, len(issues))}\n", flush=True)
    tally = collections.Counter()
    for domain, iss in issues[:limit]:
        ev = iss.get("evidence") or {}
        claim = (ev.get("title") or "").strip()
        urls = [u for u in (ev.get("sample_urls") or []) if u][:4]
        if not claim or len(urls) < 2:
            tally[UNSURE] += 1
            print(f"  {MARK[UNSURE]} {domain:<22} 证据不足（title 或 sample_urls 不全）", flush=True)
            continue

        same, notes, blocked, redirected = 0, [], 0, 0
        for u in urls:
            host = urlparse(u).netloc.replace("www.", "")
            t, st, final = fetch_title(u)
            # ⚠️ 先分清「页面变了/跳走了」和「规则错了」：
            # 回访时页面可能跳去别的域（实测 airbnb.com → zh.airbnb.com，
            # title 变成「重定向到zh.airbnb.com」）。此时我拿到的是重定向页的
            # title，跟当初抓的完全不是同一个页面 —— 按「没测到 ≠ 不存在」，
            # 这该记存疑，不是误报。
            if st == "ok" and final:
                fh = urlparse(final).netloc.replace("www.", "")
                if fh and fh != host:
                    redirected += 1
                    notes.append(f"{u.split('/', 3)[-1][:18] or '根'}:跳去{fh}")
                    continue
            if st == "domain_shell":
                # 这是个跳转壳，不是我抓到的那个页面 —— 没测到，不是规则错
                redirected += 1
                notes.append(f"{u.split('/', 3)[-1][:18] or '根'}:域名切换壳({t[:12]})")
                continue
            if st != "ok" or t is None:
                blocked += 1
                notes.append(f"{u.split('/', 3)[-1][:18] or '根'}:{st}")
                continue
            hit = t == claim
            same += 1 if hit else 0
            notes.append(f"{u.split('/', 3)[-1][:18] or '根'}:{'同' if hit else f'≠{t[:16]}'}")

        # 至少回访到 2 个页面、且其中 ≥2 个确实共用 → 真问题
        ok = same >= 2
        # 「没测到 ≠ 不存在」：回访不到（跳去了别的域 / 被挡 / 超时）一律存疑，
        # 不记误报。只有「都回访到了、且没有一个共用」才判误报。
        missed = blocked + redirected
        verdict = TRUE if ok else (FALSE if same == 0 and missed == 0 else UNSURE)
        tally[verdict] += 1
        detail = f"回访{same}页同题" + (f"，{missed}页取不到" if missed else "")
        print(f"  {MARK[verdict]} {domain:<22} {detail}"
              f"（规则称 {ev.get('url_count')} 页）", flush=True)
        print(f"        {' | '.join(notes)}", flush=True)

    print(f"\n=== 小结：真问题 {tally[TRUE]} · 误报 {tally[FALSE]} · 存疑 {tally[UNSURE]}",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())