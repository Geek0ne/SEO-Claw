#!/usr/bin/env python3
"""回原站核对 batch200 报出的问题 —— 覆盖全部规则。

为什么不重跑我们的规则：报告里的结论是「解析层看到什么」，
用户关心的是「页面里到底有没有」。两者不一致就是误报。
直接 curl 原始 HTML grep，才是独立的第二意见。

存量核对逻辑在 verify_batch.py；这里补齐剩下 15 条规则。
两处都从同一批 issue 里取样本，回源方式一致。

用法：python3 tools/verify_batch2.py <rule_code> [样本数]
"""
import glob
import json
import re
import subprocess
import sys
import collections
from urllib.parse import urlparse, urljoin

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


def fetch_robots(url, timeout=15):
    root = f"{urlparse(url).scheme}://{urlparse(url).netloc}/robots.txt"
    return fetch(root, timeout)


def looks_js(html):
    """静态 HTML 里找不到东西时，判断是不是 JS 注入的。"""
    return bool(re.search(r"<noscript", html, re.I)
                or "__NEXT_DATA__" in html
                or "window.__NUXT__" in html
                or "data-reactroot" in html)


# ---------- 页面级 ----------

def check_title_missing(html, iss):
    if re.search(r"<title[^>]*>\s*\S", html, re.I):
        return "有 title", FALSE
    if looks_js(html):
        return "静态没有，像 JS 注入", UNSURE
    return "原始 HTML 里确实没有 title", TRUE


def check_title_too_long(html, iss):
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if not m:
        return "原始 HTML 没有 title", UNSURE
    t = re.sub(r"\s+", " ", m.group(1)).strip()
    ev = iss.get("evidence", {})
    lim = ev.get("threshold") or ev.get("limit") or ev.get("max_length")
    if lim is None:
        return f"title {len(t)} 字：{t[:50]!r}（报告没带阈值，判不了）", UNSURE
    return f"title 实际 {len(t)} 字（阈值 {lim}）：{t[:40]!r}", \
        (TRUE if len(t) > int(lim) else FALSE)


def check_title_too_short(html, iss):
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if not m:
        return "原始 HTML 没有 title", UNSURE
    t = re.sub(r"\s+", " ", m.group(1)).strip()
    ev = iss.get("evidence", {})
    lim = ev.get("threshold") or ev.get("limit") or ev.get("min_length")
    if lim is None:
        return f"title {len(t)} 字（报告没带阈值）", UNSURE
    return f"title 实际 {len(t)} 字（阈值 {lim}）：{t[:40]!r}", \
        (TRUE if len(t) < int(lim) else FALSE)


def check_noindex(html, iss):
    if not re.search(r"<meta[^>]+name=[\"']robots[\"'][^>]*>", html, re.I):
        # robots 在 X-Robots-Tag 头里也有，但这里只查 HTML，能查的范围内没有
        return "HTML 里没有 robots meta（可能在响应头，静态查不了）", UNSURE
    tag = re.search(r"<meta[^>]+name=[\"']robots[\"'][^>]*>", html, re.I).group(0)
    if re.search(r"noindex", tag, re.I):
        return f"确实有 noindex：{tag[:70]}", TRUE
    return f"有 robots meta 但没 noindex：{tag[:70]}", FALSE


def check_h1_multiple(html, iss):
    n = len(re.findall(r"<h1[\s>]", html, re.I))
    ev = iss.get("evidence", {})
    lim = ev.get("threshold") or ev.get("limit") or 1
    return f"h1 共 {n} 个（阈值 {lim}）", (TRUE if n > int(lim) else FALSE)


def check_img_alt_missing(html, iss):
    imgs = re.findall(r"<img\b[^>]*>", html, re.I)
    if not imgs:
        return "这一页没有 img（可能 URL 指错了页）", UNSURE
    no_alt = [i for i in imgs if not re.search(r"\balt\s*=", i, re.I)]
    empty = [i for i in imgs if re.search(r"\balt\s*=\s*[\"']\s*[\"']", i, re.I)]
    ev = iss.get("evidence", {})
    want = ev.get("count") or ev.get("missing_count")
    detail = f"img 共 {len(imgs)}，无 alt 属性 {len(no_alt)}，alt 为空 {len(empty)}"
    if want is None:
        return detail + "（报告没带计数，只能看方向）", UNSURE
    return detail + f"（报告称 {want} 条）", \
        (TRUE if int(want) == len(no_alt) + len(empty) else FALSE)


def check_img_alt_generic(html, iss):
    generic = {"logo", "image", "img", "icon", "photo", "banner", "avatar", "截图", "图片"}
    alts = re.findall(r"<img\b[^>]*\balt\s*=\s*[\"']([^\"']*)[\"'][^>]*>", html, re.I)
    bad = [a for a in alts if a.strip().lower() in generic]
    if not alts:
        return "没抓到带 alt 的 img", UNSURE
    return f"alt 共 {len(alts)} 个，其中通用词 {len(bad)} 个", None if not bad else TRUE


def check_meta_duplicate(html, iss):
    metas = re.findall(r"<meta[^>]+name=[\"']description[\"'][^>]*content=[\"']([^\"']*)[\"']",
                       html, re.I)
    if len(metas) < 2:
        return f"原始 HTML 里 description 只有 {len(metas)} 个，没重复", FALSE
    uniq = len(set(m.strip() for m in metas))
    return f"description 共 {len(metas)} 个，去重后 {uniq} 个", \
        (TRUE if uniq < len(metas) else FALSE)


def check_mixed_content(html, iss):
    """混合内容：页面是 https 却引了 http 资源。"""
    if not html.lower().startswith("<!doctype html") and "://" not in html[:200]:
        return "没抓到页面", UNSURE
    n = len(re.findall(r"(?:src|href)\s*=\s*[\"']http://", html, re.I))
    return f"页面里引了 {n} 个 http:// 资源（https 页面不该有）", \
        (TRUE if n > 0 else FALSE)


def check_soft404(html, iss):
    """软 404：返回 200 但内容是「页面不存在」。"""
    t = re.sub(r"<[^>]+>", " ", html[:200000])
    t = re.sub(r"\s+", " ", t)
    markers = ["页面不存在", "找不到该页", "page not found", "404 not found",
               "this page does not exist", "内容不存在", "该内容已被删除"]
    hit = [m for m in markers if m.lower() in t.lower()]
    return (f"正文里出现「{hit[0]}」" if hit else "正文里没找到软 404 标志语"), \
        (TRUE if hit else UNSURE)


# ---------- 站点级 ----------

def check_sitemap_missing(url, iss):
    r = fetch_robots(url)
    if not r:
        return "robots.txt 抓不到，判不了", UNSURE
    sm = re.findall(r"(?im)^\s*sitemap\s*:\s*(\S+)", r)
    if sm:
        return f"robots.txt 里声明了 {len(sm)} 个 sitemap：{sm[0][:60]}", FALSE
    # robots 里没声明，再试 /sitemap.xml
    root = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    body = fetch(urljoin(root, "/sitemap.xml"), timeout=20)
    if body and "<urlset" in body.lower():
        return "robots.txt 没声明，但 /sitemap.xml 存在", FALSE
    if body and "<html" in body[:500].lower():
        return "/sitemap.xml 返回的是 HTML（多半 404 页），没有 sitemap", TRUE
    return "robots.txt 无声明，/sitemap.xml 也没拿到", UNSURE


def check_robots_blocks_own_site(url, iss):
    """robots.txt 把本站所有 UA 都挡住了。"""
    r = fetch_robots(url)
    if not r:
        return "robots.txt 抓不到", UNSURE
    blocks_all = False
    for m in re.finditer(r"(?is)user-agent\s*:\s*(\*)[^\n]*\n((?:[ \t]*\w+[ \t]*:.*\n?)+)", r):
        for line in m.group(2).splitlines():
            if re.match(r"\s*disallow\s*:\s*/\s*$", line, re.I):
                blocks_all = True
    return "robots.txt 里 User-agent:* Disallow:/ 全站封死", \
        (TRUE if blocks_all else FALSE)


def check_link_noanchor(html, iss):
    """无锚文本内链。空 <a> 里有 img 是正常的（看 alt），纯空才是问题。"""
    anchors = re.findall(r"<a\b[^>]*>(.*?)</a>", html, re.I | re.S)
    pure_empty, img_wrap, has_text = 0, 0, 0
    for inner in anchors:
        if re.search(r"<(img|svg)\b", inner, re.I):
            img_wrap += 1
            continue
        txt = re.sub(r"<[^>]+>", "", inner).strip()
        if txt:
            has_text += 1
        else:
            pure_empty += 1
    return (f"<a> 共 {len(anchors)}：有文字 {has_text}，包图片 {img_wrap}，"
            f"纯空 {pure_empty}"), (TRUE if pure_empty > 0 else FALSE)


def check_canonical_conflict(html, iss):
    """canonical 冲突：页面声明的 canonical 指向别人。"""
    links = re.findall(r"<link[^>]+rel=[\"']canonical[\"'][^>]*>", html, re.I)
    hrefs = [re.search(r"href\s*=\s*[\"']([^\"']+)", l, re.I).group(1)
             for l in links if re.search(r"href\s*=", l, re.I)]
    if not hrefs:
        return "这一页没有 canonical（跟 missing 混了）", UNSURE
    self_url = urlparse(iss.get("url", "")).path or "/"
    self_host = urlparse(iss.get("url", "")).netloc
    bad = [h for h in hrefs
           if urlparse(h).netloc and urlparse(h).netloc.replace("www.", "") != self_host.replace("www.", "")]
    return f"canonical 指向 {len(bad)} 个外部域名：{bad[0][:50] if bad else '无'}", \
        (TRUE if bad else FALSE)


CHECKERS = {
    "title.missing": check_title_missing,
    "title.too_long": check_title_too_long,
    "title.too_short": check_title_too_short,
    "title.duplicate": None,   # 需跨页比对，先跳过
    "noindex.present": check_noindex,
    "h1.multiple": check_h1_multiple,
    "img.alt.missing": check_img_alt_missing,
    "img.alt.generic": check_img_alt_generic,
    "meta.duplicate": check_meta_duplicate,
    "meta.missing": None,      # verify_batch.py 已有
    "canonical.missing": None, # 同上
    "h1.missing": None,        # 同上
    "canonical.conflict": check_canonical_conflict,
    "link.noanchor": check_link_noanchor,
    "sitemap.missing": check_sitemap_missing,
    "robots.blocks_own_site": check_robots_blocks_own_site,
    "soft404": check_soft404,
    "http.mixed_content": check_mixed_content,
}

# 站点级要单独请求 robots.txt，不能先抓页面
ROBOTS_ONLY = {"sitemap.missing", "robots.blocks_own_site"}


def main():
    code = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 15
    checker = CHECKERS.get(code, "MISSING")
    if checker == "MISSING":
        print(f"没 {code} 的核对逻辑；已支持：{', '.join(k for k, v in CHECKERS.items() if v)}")
        return 1
    if checker is None:
        print(f"{code} 暂不支持回源核对")
        return 1

    # ⚠️ 站点级问题（scope=site）的 url 是 None。
    # 早先我写 `if u and u not in seen`，把空值全丢了 ——
    # 结果 sitemap.missing(58) / meta.duplicate(25) / robots.blocks_own_site(1)
    # 三条规则一条没核，日志却写「0 条待核」，看着像没问题。
    #
    # **「0 条待核」和「都没问题」长得一模一样。** 这跟当初
    # .example 那个 400 是 SSRF 给的一模一样：没测到 ≠ 通过。
    targets, seen = [], set()
    for f in sorted(glob.glob("reports/batch200/*.json")):
        d = json.load(open(f))
        for iss in d.get("issues", []):
            if iss.get("code") != code:
                continue
            if iss.get("url"):
                u = iss["url"]
            else:
                # 站点级：拿域名兜底，robots.txt 就在域名根上
                u = f"https://{d['domain']}/"
            if u in seen:
                continue
            seen.add(u)
            targets.append((d["domain"], u, iss))

    sample = targets[:limit]
    print(f"=== {code}：{len(targets)} 条待核，抽 {len(sample)} 条回原站\n")
    tally = collections.Counter()
    for domain, url, iss in sample:
        host = urlparse(url).netloc
        if code in ROBOTS_ONLY:
            detail, verdict = checker(url, iss)
        else:
            html = fetch(url)
            if not html:
                tally["抓不到"] += 1
                print(f"  ?? {host:<28} 回源抓不到")
                continue
            detail, verdict = checker(html, iss)
        tally[verdict] += 1
        mark = {TRUE: "真问题", FALSE: "误报 ", UNSURE: "存疑 ", None: "自相矛盾"}.get(verdict, "?")
        print(f"  {mark} {host:<28} {detail}")

    print(f"\n=== 小结：真问题 {tally[TRUE]} · 误报 {tally[FALSE]} "
          f"· 存疑 {tally[UNSURE]} · 抓不到 {tally['抓不到']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
