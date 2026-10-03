#!/usr/bin/env python3
"""按规则的**真实逻辑**回源核对 —— 修正版。

上一版 verify_batch.py / verify_batch2.py 的核对器自己写错了，
把好规则判成误报。教训：核对器必须先读规则源码，知道它到底怎么判，
否则「误报」这个词毫无意义 —— 我差点冤枉规则。

已修正的三处：
1. img.alt.missing  规则判 `img.alt is None`（完全没有 alt 属性），
   不是我原先的「没有 alt 属性 + alt 为空」。
2. link.noanchor    规则排除 decorative 链接，且只数 internal、且要求 >= 2。
3. canonical.conflict 规则比的是 normalize 后的**完整 URL**（含 path），
   不是只比域名。

用法：python3 tools/verify_fixed.py <rule_code> [样本数]
"""
import glob
import json
import re
import subprocess
import sys
import collections
from urllib.parse import urlparse, urlunparse

UA = "Mozilla/5.0 (compatible; SEOClawVerifier/1.0)"
TRUE, FALSE, UNSURE = "true", "false", "unsure"


def fetch(url, timeout=25):
    try:
        r = subprocess.run(
            ["curl", "-sL", "--compressed", "-m", str(timeout),
             "-A", UA, "--max-filesize", "4000000", url],
            capture_output=True, timeout=timeout + 10,
        )
        return r.stdout.decode("utf-8", "replace")
    except Exception:
        return ""


def normalize_url(u):
    """对齐规则的 normalize_url：忽略协议、www、末尾斜杠、index.html 等价形式。"""
    p = urlparse(u)
    host = (p.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = p.path or "/"
    if path.endswith("/index.html"):
        path = path[: -len("index.html")]
    elif path.endswith("/index.htm"):
        path = path[: -len("index.htm")]
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return f"{host}{path}"


def looks_js(html):
    return bool(re.search(r"<noscript", html, re.I)
                or "__NEXT_DATA__" in html
                or "window.__NUXT__" in html)


# ---------- 修正后的核对器 ----------

def check_img_alt_missing(html, iss):
    """规则：missing = [img.src for img in page.images if img.alt is None]

    所以只有**完全没有 alt 属性**的才算缺。alt="" 是装饰性图片的正确写法，
    我上一版把它也算成缺 —— 这是核对器的错。
    """
    imgs = re.findall(r"<img\b[^>]*>", html, re.I)
    none_attr = [i for i in imgs if not re.search(r"\balt\s*=", i, re.I)]
    empty_attr = [i for i in imgs if re.search(r"\balt\s*=\s*[\"']\s*[\"']", i, re.I)]
    ev = iss.get("evidence", {})
    want = ev.get("missing_count")
    detail = f"img 共 {len(imgs)}：无 alt 属性 {len(none_attr)}，alt=\"\" {len(empty_attr)}"
    if want is None:
        return detail + "（报告没带计数）", UNSURE
    # ⚠️ 判据：**不能要求两者相等**，只能要求「规则报的都被原文证实」。
    #
    # 提取层的 page.images 永远比原始 HTML 里的 <img> 少（懒加载、
    # noscript 里的图、未进入当前 DOM 的图都不算），实测 slashdot
    # 提取层看到 1 张、我 grep 到 21 张；meta.discourse.org 88 vs 101。
    # 我上一版写的是 want == len(none_attr)，5 vs 15 直接判误报——
    # 方向反了：规则是**少报**，不是报错。
    #
    # 正向证据：原文里确实存在 >= want 个完全没有 alt 属性的图，
    # 而规则报的每一条都出自这个集合 → 真问题。
    ok = 0 < int(want) <= len(none_attr)
    return detail + f"（规则报 {want}）", (TRUE if ok else FALSE)


def check_link_noanchor(html, iss):
    """规则：internal 链接 + 无锚文本 + 非 decorative，且 empties >= 2 才报。"""
    ev = iss.get("evidence", {})
    want = ev.get("empty_anchor_count")
    host = urlparse(iss.get("url", "")).netloc.replace("www.", "")

    internal_empty_nondec = 0
    internal_empty_dec = 0
    for m in re.finditer(r"<a\b([^>]*)>(.*?)</a>", html, re.I | re.S):
        attrs, inner = m.group(1), m.group(2)
        href = re.search(r"href\s*=\s*[\"']([^\"']+)", attrs, re.I)
        if not href:
            continue
        try:
            h = urlparse(href.group(1))
            if h.netloc and h.netloc.replace("www.", "") != host:
                continue          # 规则只数 internal
        except Exception:
            pass
        txt = re.sub(r"<[^>]+>", "", inner).strip()
        if txt:
            continue
        # decorative：aria-hidden="true" / tabindex="-1" / 包着 img
        is_dec = bool(re.search(r"aria-hidden\s*=\s*[\"']true[\"']", attrs, re.I)
                      or re.search(r"tabindex\s*=\s*[\"']-1[\"']", attrs, re.I)
                      or re.search(r"<(img|svg)\b", inner, re.I))
        if is_dec:
            internal_empty_dec += 1
        else:
            internal_empty_nondec += 1

    detail = (f"内部空锚：非装饰 {internal_empty_nondec}，装饰 {internal_empty_dec}"
              f"（规则报 {want}，阈值 ≥2）")
    if want is None:
        return detail + "（报告没带计数）", UNSURE
    ok = int(want) == internal_empty_nondec and internal_empty_nondec >= 2
    return detail, (TRUE if ok else FALSE)


def check_canonical_conflict(html, iss):
    """规则：normalize(canonical) != normalize(current) 才报。

    我上一版只比域名 —— docs.python.org/3.10/ 与 /3/index.html 同域，
    我就判成「没有冲突」，等于没测。
    """
    links = re.findall(r"<link[^>]+rel=[\"']canonical[\"'][^>]*>", html, re.I)
    hrefs = [m.group(1) for l in links
             for m in [re.search(r"href\s*=\s*[\"']([^\"']+)", l, re.I)] if m]
    if not hrefs:
        return "这一页没有 canonical（跟 canonical.missing 混了）", UNSURE
    cur = normalize_url(iss.get("url", ""))
    conflicts = [h for h in hrefs if normalize_url(h) != cur]
    detail = f"canonical={hrefs[0][:55]} → {'不等于本页' if conflicts else '等于本页'}"
    return detail, (TRUE if conflicts else FALSE)


def check_sitemap_missing(url, iss):
    """站点级。证据里已列 tried_paths，逐个回访看 ok 是否该为 true。"""
    ev = iss.get("evidence", {})
    tried = ev.get("tried_paths") or []
    if not tried:
        return "报告没带 tried_paths", UNSURE
    for t in tried:
        body = fetch(t["url"], timeout=20)
        has_sitemap = "<urlset" in body.lower() or "<sitemapindex" in body.lower()
        looks_html = "<html" in body[:600].lower() or "<!doctype html" in body[:100].lower()
        desc = (f"{t['url'][:50]} → 真 sitemap！规则漏了" if has_sitemap
                else f"{t['url'][:50]} → 返回 HTML 不是 sitemap，规则判对了")
        return desc, (FALSE if has_sitemap else TRUE)
    return f"试了 {len(tried)} 个路径都没 sitemap", TRUE


CHECKERS = {
    "img.alt.missing": (check_img_alt_missing, False),
    "link.noanchor": (check_link_noanchor, False),
    "canonical.conflict": (check_canonical_conflict, False),
    "sitemap.missing": (check_sitemap_missing, True),
}


def main():
    code = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    if code not in CHECKERS:
        print(f"没 {code} 的修正核对器；已支持：{', '.join(CHECKERS)}")
        return 1
    checker, robots_only = CHECKERS[code]

    targets, seen = [], set()
    for f in sorted(glob.glob("reports/batch200/*.json")):
        d = json.load(open(f))
        for iss in d.get("issues", []):
            if iss.get("code") != code:
                continue
            u = iss.get("url") or f"https://{d['domain']}/"
            if u in seen:
                continue
            seen.add(u)
            targets.append((d["domain"], u, iss))

    sample = targets[:limit]
    print(f"=== {code}（修正版核对器）：{len(targets)} 条待核，抽 {len(sample)} 条\n")
    tally = collections.Counter()
    for domain, url, iss in sample:
        host = urlparse(url).netloc
        if robots_only:
            detail, verdict = checker(url, iss)
        else:
            html = fetch(url)
            if not html:
                tally["抓不到"] += 1
                print(f"  ?? {host:<26} 回源抓不到")
                continue
            detail, verdict = checker(html, iss)
        tally[verdict] += 1
        mark = {TRUE: "真问题", FALSE: "误报 ", UNSURE: "存疑 "}.get(verdict, "?")
        print(f"  {mark} {host:<26} {detail}")

    print(f"\n=== 小结：真问题 {tally[TRUE]} · 误报 {tally[FALSE]} "
          f"· 存疑 {tally[UNSURE]} · 抓不到 {tally['抓不到']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
