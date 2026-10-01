#!/usr/bin/env python3
"""
独立回源核对器 —— M0 误报回归验收。**读 JSON，不读 markdown。**

为什么必须重写
--------------
第一版读 markdown 报告，结果 44 条里 36 条判成「存疑」，只拿到 8 条可判定，
算出的 75% 是噪声不是测量。根因：**markdown 会按根因聚合**，一行只剩
「影响 N 个页面」，**URL 被丢掉了**，核对器没法回源。JSON 保留每条 issue 的 url。

为什么判定逻辑要独立写
--------------------
拿规则自己的代码去「验证」规则等于自己给自己判卷：规则错了，复现出来的也是错的。
这里**完全不 import app.audit 下的任何代码**，只用原始正则读 live HTML。

三档判定，不只有对/错：
- true_positive  属实，且确实是用户该管的问题
- noisy          属实，但不该让用户管（噪音规则：Google 不看/可选增强）
- false_positive 不属实（漏看、解析错、页面已变）
- unknown        取不到页面 / 需人工判断，不计入分母
"""
from __future__ import annotations

import concurrent.futures as cf
import glob
import html as htmllib
import json
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

UA = "Mozilla/5.0 (compatible; SEOAgentAudit/1.0; +https://example.com/bot)"
_cache: dict[str, str | None] = {}


def fetch(url: str, timeout: int = 20) -> str | None:
    if url in _cache:
        return _cache[url]
    out = None
    try:
        r = subprocess.run(
            ["curl", "-sL", "--max-time", str(timeout), "-A", UA, url],
            capture_output=True, text=True, timeout=timeout + 5,
        )
        if r.stdout and "<html" in r.stdout.lower():
            out = r.stdout
    except Exception:
        out = None
    if out is not None and _looks_bot_blocked(out):
        # 反爬页不是「站点没做 SEO」，是「我们没拿到页面」。
        # cityofchicago.org 实测：机器人 UA 返回 375 字节 Access Denied，
        # 换浏览器 UA 返回 72584 字节、h1 数 0——同一个 URL 每次内容都不同。
        # 这种情况判误报是自己骗自己，判 true_positive 同样是凭空下结论。
        out = None
    _cache[url] = out
    return out


def _looks_bot_blocked(h: str) -> bool:
    """是不是反爬/风控页，而不是真实内容页。

    命中即视为「取不到页面」→ unknown，不进分母。这类样本在第三批里
    造成 5 条假误报（cityofchicago 的 h1.missing / h1.multiple）。
    """
    body = h.lower()
    # 只认「服务器明确拒绝我们」的时刻留下的痕迹。
    #
    # ⚠️ 踩过的坑，保留在此防止有人再犯：这里原来有 8 个 marker，其中
    # "captcha" 是裸子串。审计第三批时它命中 71 个 URL，可其中 **60 个
    # 正文超过 1500 字的正常页面**全被踢出分母——sentry.io（正文 16607 字，
    # 在发 SDK 发布稿）、intercom.com（7327 字）、techcrunch 的三篇 contributor
    # content。原因只是这些页面挂了 reCAPTCHA 脚本、或者文章里提到「验证码」。
    # 那一轮准确率从 95.2% 涨到 96.0%，涨的那部分是我自己拿样本换的。
    block_markers = (
        "access denied", "just a moment", "checking your browser",
        "enable javascript and cookies", "cf-browser-verification",
        "attention required", "request unsuccessful",
        "verify you are human", "are you a robot",
    )
    # captcha 只有在「风控语境」里才算数：标题/提示语出现，而不是页面正文提及。
    captcha_ctx = re.search(
        r"(verify|verification|checking|confirm|human|robot|sorry|unusual)"
        r"[^<]{0,40}captcha|captcha[^<]{0,40}(required|needed|verify|verification)",
        body,
    )
    # 为什么「薄」不能当证据：页面内容少 ≠ 我们没拿到页面。真的抓到了就
    # 观察到了，观察到了就能判；判 unknown 是逃避判断。
    return any(m in body for m in block_markers) or bool(captcha_ctx)


def _tags(h: str, pat: str) -> list[str]:
    return re.findall(pat, h, re.I | re.S)


def _strip(s: str) -> str:
    return htmllib.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def _attr(tag: str, name: str) -> str | None:
    m = re.search(rf'\b{name}\s*=\s*["\']([^"\']*)["\']', tag, re.I)
    if m:
        return m.group(1)
    m = re.search(rf'\b{name}\s*=\s*([^\s>]+)', tag, re.I)
    return m.group(1) if m else None


def _meta(h: str, key: str) -> str | None:
    for tag in _tags(h, r"<meta[^>]*>"):
        k = (_attr(tag, "property") or _attr(tag, "name") or "").strip().lower()
        if k == key.lower():
            c = _attr(tag, "content")
            if c:
                return c.strip()
    return None


def _title(h: str) -> str | None:
    m = re.search(r"<title[^>]*>(.*?)</title>", h, re.I | re.S)
    return _strip(m.group(1)) if m else None


def _visible_text(h: str) -> str:
    return _strip(re.sub(r"<(script|style|nav|footer)[^>]*>.*?</\1>", " ", h, flags=re.I | re.S))


def _canon_key(url: str) -> str:
    """canonical 比较用：仅忽略 path 大小写，其余照常。"""
    from urllib.parse import urlparse

    try:
        p = urlparse(url)
    except ValueError:
        return url.strip().rstrip("/").lower()
    host = (p.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = (p.path or "/").rstrip("/") or "/"
    return f"{host}{path}".lower()


def _abs_url(base: str, href: str) -> str:
    from urllib.parse import urljoin

    return urljoin(base, href)


def _content_same(a: str, b: str) -> bool:
    """两个页面的实质内容是否相同（只看正文，不看模板/导航）。

    ⚠️ 必须用**字符 n-gram**，不能用「按空格切词」。
    我第一版写的正则 ``[a-z0-9一-鿿]{2,}`` 有个致命缺陷：西语、中文、
    以及任何没空格排版的正文里，一整串连续字符会被切成一个巨型 token。
    实测 fotocasa 的「alertasPublicarMisAlertasPublicarAnuncioGratis」被切成
    一个词 'alertaspublicar'，naaptol 切出 4816 个巨型词——两页的
    token 集合几乎必然重合，Jaccard 直接冲到 1.000。
    后果是 canonical.conflict 一口气多出 8 条假误报，其中 purdue.edu
    首页被「判」成和 purdue.edu/home 内容相同。

    字符 n-gram 不依赖空格分隔，跨语种都稳。取 5-gram 集合的 Jaccard。
    """
    ta = _shingles(_visible_text(a))
    tb = _shingles(_visible_text(b))
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= 0.7


# 比对「两页内容相同」时，两页正文都得够长才作数。
#
# 实踩：indiehackers 的 /products/new 与 canonical 目标 /sign-in、fotocasa 的
# /es/user/alerts 与 /es/login，这两组**本不是同一篇内容**，但两次抓取各自都
# 落到了同一个登录页，于是 _content_same 判「相同」→ 报成 false_positive。
# 后果是 canonical.conflict 的 11 条「误报」里 9 条是假的，准确率被算低。
#
# 这与「判缺 X 必须先正面看到 X」是同一个错误的镜像：不是没看到「缺」，而是
# **没看到内容就下了「内容相同」的结论**。两页都短成登录页/人机挑战/JS 壳
# 时，Jaccard 再高也只说明它们同为一张壳，不说明文章相同。
MIN_CANON_TEXT = 400

_THIN_PAGE_RE = re.compile(
    r"sign\s?in|log\s?in|entra en tu cuenta|create an account|"
    r"just a moment|checking your browser|please enable javascript|"
    r"enable javascript to (run|view)",
    re.I,
)


def _too_thin_to_compare(h: str | None) -> bool:
    """正文太短、或整页就是登录/挑战壳 → 不能拿它比「内容是否相同」。"""
    if not h:
        return True
    text = _visible_text(h)
    if len(text) < MIN_CANON_TEXT:
        return True
    return bool(_THIN_PAGE_RE.search(text[:2000]))


def _shingles(text: str, n: int = 5) -> set[str]:
    """字符 n-gram 集合；文字太短就退化为整串。"""
    t = re.sub(r"\s+", "", (text or "").lower())
    if len(t) < n:
        return {t} if t else set()
    return {t[i:i + n] for i in range(len(t) - n + 1)}


def _looks_js_rendered(h: str) -> bool:
    """粗略判断页面是否依赖 JS 渲染。

    只用于「静态 HTML 里找不到某元素」时决定要不要判 unknown，
    不能用来证明页面确实没有该元素。
    """
    body = h.lower()
    if re.search(r'<div[^>]+id\s*=\s*["\'](root|app|__next|__nuxt)["\']', body):
        return True
    # 可疑信号：几乎没有 <a>/<img>，却有框架脚本
    few_tags = len(_tags(h, r"<a\b")) + len(_tags(h, r"<img\b"))
    has_fw = bool(re.search(r"(react|vue|angular|next|nuxt|svelte)", body))
    return few_tags < 5 and has_fw


@dataclass
class Verdict:
    state: str
    note: str = ""


# 每条规则的独立判定。刻意不复用 app.audit 的任何代码。
def verify(code: str, url: str, h: str | None, ev: dict[str, Any]) -> Verdict:
    if h is None:
        return Verdict("unknown", "取不到页面")

    if code == "title.missing":
        if _title(h) is not None:
            return Verdict("false_positive", "有 title")
        # ⚠️ 不能直接判「无 title」→ 误报。agoda.com 实测：1.1MB 的静态 HTML
        # 里 grep -ci '<title' 结果为 0，**规则判对了**（静态 HTML 确实没有
        # title），但我第一版核对器在这里直接判 false_positive，理由写的是
        # 「有 title」——而实测两个 UA 都是 0 个 title，核对器自己判反了。
        # 正确做法是跟 too_long 分支一样：静态 HTML 里找不到某个元素时，
        # 证据强度不足，只能判 unknown。找不到 ≠ 不存在。
        if _looks_js_rendered(h):
            return Verdict("unknown", "静态 HTML 无 title，页面疑似 JS 渲染，与抓取时不一致")
        return Verdict("true_positive", "无 <title>")

    if code in ("title.too_short", "title.too_long"):
        t = _title(h)
        if t is None:
            # ⚠️ 不能直接判「无 title」→ 误报。SPA 页面（juejin.cn 就是）
            # 的 title 是客户端注入的，静态 HTML 里根本没有，而报告里那条
            # title 明明存在。核对器 curl 到的东西和抓取器拿到的不是同一份，
            # 这时判误报是自己骗自己。真实样本：juejin.cn 4 条里 3 条被这样误判。
            if _looks_js_rendered(h):
                return Verdict("unknown", "静态 HTML 无 title，页面疑似 JS 渲染，与抓取时不一致")
            return Verdict("false_positive", "无 title")
        n = len(t)
        # ⚠️ 中文标题阈值不同（30 vs 60），必须自己判断，不能硬编码 60。
        # 我第一版核对器写死 60，把 csdn.net 的中文长标题误判成「规则误报」，
        # 其实规则判对了——是我的测量工具错了。
        # ⚠️ CJK 判定必须和规则**逐字一致**，否则「规则误报」是自己造的。
        # 规则侧 app/audit/rules/base/_is_cjk 是「含任意 CJK 字符即算中文」，
        # 我第一版核对器写成「CJK 占比 ≥30% 才算」，于是 statuspage.io 的
        # 「借助 Statuspage 提高透明度 | Atlassian」（7/31 = 0.23）被判成英文
        # 标题、按 60 字符放行，而规则按 30 判已触发——同一份标题两个标准，
        # 判出来 2 条「误报」。规则没错，是尺子错了。
        # 口径已定：含任意 CJK 字符就算中文标题。
        is_cjk = any("一" <= c <= "鿿" for c in t)
        lo, hi = ev.get("min", 15), ev.get("max", 30 if is_cjk else 60)
        hit = n < lo if code == "title.too_short" else n > hi
        if not hit:
            return Verdict("false_positive", f"len={n} 阈值[{lo},{hi}]")
        # 站名/品牌名：词数少 + 全大写开头 + 无功能词 → 属实但不该让用户改
        words = [w for w in t.split() if w]
        stop = {"a", "an", "the", "of", "for", "to", "in", "on", "and", "or",
                "with", "from", "at", "by", "is", "are", "best", "top", "guide"}
        namey = 0 < len(words) <= 3 and not (set(w.lower() for w in words) & stop) \
            and all(w[:1].isupper() or w.isupper() for w in words if w[:1].isalpha())
        return Verdict("noisy", f"title={t!r} len={n}，疑似站名") if namey \
            else Verdict("true_positive", f"title={t!r} len={n}")

    if code in ("meta.missing", "meta.too_short", "meta.too_long", "meta.duplicate"):
        d = _meta(h, "description")
        if code == "meta.missing":
            return Verdict("true_positive", "无 description") if d is None else Verdict("false_positive", "有 description")
        if d is None:
            return Verdict("false_positive", "无 description，前提不成立")
        n = len(d)
        if code == "meta.too_short":
            return Verdict("true_positive", f"len={n}") if n < 50 else Verdict("false_positive", f"len={n}")
        if code == "meta.too_long":
            return Verdict("true_positive", f"len={n}") if n > 160 else Verdict("false_positive", f"len={n}")
        return Verdict("unknown", f"len={n}")

    if code == "canonical.missing":
        has = re.search(r"<link[^>]+rel\s*=\s*[\"']?canonical", h, re.I)
        return Verdict("true_positive", "无 canonical") if not has else Verdict("false_positive", "有 canonical")

    if code == "canonical.conflict":
        m = re.search(r"<link[^>]+rel\s*=\s*[\"']?canonical[^>]*>", h, re.I)
        if not m:
            return Verdict("false_positive", "无 canonical")
        href = (_attr(m.group(0), "href") or "").rstrip("/")
        # ⚠️ 顺序有讲究：必须先判「仅大小写不同」。
        # `same` 用的是小写化比较，会把 /Foo 和 /foo 也算成一致，
        # 若放在前面就永远抢在下面这条之前命中——我自己第一版就写反了，
        # 导致新增的 _canon_key 分支是死代码，jvns.ca 那条一直算误报。
        if _canon_key(href) == _canon_key(url):
            # 规则侧对这种情况降级为 INFO 并标 case_only_difference
            # （backend/app/audit/rules/base，same_url_ignoring_path_case）。
            # 指向的仍是本页，不该让用户去改 → 算噪音，不算误报。
            return Verdict("noisy", f"canonical 仅 path 大小写不同: {href[:50]}")
        if href.lower() in (url.rstrip("/").lower(), ""):
            return Verdict("false_positive", f"canonical 与自身一致: {href[:50]}")

        # 到这里 canonical 指向了另一个 URL：是真冲突，还是合法的重复内容归一？
        # 判据：**两个 URL 的内容是否实质相同**。相同 → 归一是对的，不该让用户改；
        # 不同 → canonical 指错了页，是真问题。这可以自己取证：把 canonical
        # 目标也取回来比正文。不比就是在猜。
        target = href if href.startswith("http") else _abs_url(url, href)
        th = fetch(target) if target else None
        if th is None:
            return Verdict("unknown", f"canonical={href[:50]}，目标页取不到，无法比内容")
        # 先排除「两页都退化成登录页/壳」，再谈内容是否相同。
        # 见 _too_thin_to_compare 注释：不排除就会把抓取失败当成合法归一。
        if _too_thin_to_compare(h) or _too_thin_to_compare(th):
            side = "本页" if _too_thin_to_compare(h) else "目标页"
            return Verdict(
                "unknown",
                f"canonical={href[:44]}，但{side}正文过短或为登录/人机挑战页，"
                f"取不到真实内容，无法比",
            )
        same = _content_same(h, th)
        return Verdict("false_positive", f"canonical 指向 {href[:40]}，两页内容相同（合法归一）") \
            if same else Verdict("true_positive", f"canonical 指向 {href[:40]}，但两页内容不同")

    if code == "h1.missing":
        tags = _tags(h, r"<h1[^>]*>(.*?)</h1>")
        if not tags:
            return Verdict("true_positive", "无 h1")
        # ⚠️ 空 h1：<h1> </h1>。标签在，但没有任何文本内容。
        # 规则判的是「无有效标题」，所以这仍是属实——真实样本
        # w3.org/ja/ 就是 <h1> </h1>。早期版本只数标签存在与否，
        # 会把这种情况错判成误报。
        nonempty = [t for t in tags if _strip(t)]
        if not nonempty:
            return Verdict("true_positive", f"{len(tags)} 个 h1 但内容全为空（如 <h1> </h1>）")
        return Verdict("false_positive", f"有 {len(nonempty)} 个非空 h1")

    if code == "h1.multiple":
        texts = [_strip(x) for x in _tags(h, r"<h1[^>]*>(.*?)</h1>")]
        if len(texts) <= 1:
            return Verdict("false_positive", f"h1={len(texts)}")
        uniq = len({t.lower() for t in texts if t})
        # 多个 h1 且内容互不相同 → Google 不惩罚，属噪音
        return Verdict("noisy", f"h1={len(texts)} 去重={uniq}") if uniq == len(texts) \
            else Verdict("true_positive", f"h1={len(texts)} 含重复({uniq})")

    if code == "img.alt.missing":
        miss = [t for t in _tags(h, r"<img[^>]*>") if _attr(t, "alt") is None]
        if not miss:
            return Verdict("false_positive", "全部有 alt")
        deco = sum(1 for t in miss if re.search(r'class\s*=\s*["\'][^"\']*(logo|avatar|icon)', t, re.I))
        return Verdict("noisy", f"{len(miss)} 张无 alt，其中装饰图 {deco}") if deco else \
            Verdict("true_positive", f"{len(miss)} 张无 alt")

    if code == "og.basic_missing":
        miss = [k for k in ("og:title", "og:description", "og:image") if _meta(h, k) is None]
        return Verdict("noisy", f"缺 {miss}，仅影响分享卡片") if miss else Verdict("false_positive", "og 齐全")

    if code == "noindex.present":
        r = (_meta(h, "robots") or "").lower()
        return Verdict("unknown", f"robots={r!r}，是否有意需业务判断") if "noindex" in r \
            else Verdict("false_positive", f"robots={r!r}")

    if code == "soft404":
        # ⚠️ 这里的 unknown 是我留给自己的坑，也是我今晚最大的一个发现。
        #
        # 规则判 soft404 的依据是 `content_is_thin`，而 content_is_thin 来自
        # trafilatura 抽出的 page.text——**trafilatura 会主动剥掉 nav/footer**
        # （extract.py 的降级路径明确 remove //nav|//footer|//header）。
        # 于是「导航重的页面」正文数必然被压到 300 词阈值以下：
        # japanpost.jp 首页有 223 条站内链接，静态可见文本只有 74 字符——
        # 那不是空页面，是我们自己把导航剥掉后数不出东西。
        # 72 条 soft404 里有 56 条内链 >= 20。
        #
        # 所以判别式不能是「正文少」（那是尺子的缺陷），
        # 得是**页面自身有没有站内结构**——这个可以从 HTML 直接数，是独立证据。
        #
        # ⚠️ 关键：不能用 evidence 里的 internal_outbound_links / verdict。
        # 那是规则自己算的，拿它「验证」规则等于自己给自己判卷。必须自己数 <a>。
        outlinks = len(_tags(h, r"<a\b[^>]*href\s*="))
        words = len(_visible_text(h).split())
        if outlinks >= 10:
            # 有结构、有大量站内出链 → 不可能是空页面。规则自己也把它降级成
            # INFO + likely_index_or_hub，所以这条**属实但不该让用户管**。
            return Verdict("noisy", f"正文 {words} 词但有 {outlinks} 条站内出链，"
                                     f"是被剥掉导航的枢纽/列表页，不是空页面")
        if outlinks == 0 and _looks_js_rendered(h):
            return Verdict("unknown", f"正文 {words} 词、无出链，但页面疑似 JS 渲染，"
                                      f"静态 HTML 不足以判断是否空页面")
        if outlinks == 0:
            return Verdict("true_positive", f"正文 {words} 词且无任何站内出链，符合软 404 特征")
        return Verdict("unknown", f"正文 {words} 词、出链 {outlinks} 条，信号不明确")

    if code == "schema.missing":
        return Verdict("noisy", "无 JSON-LD（可选增强）") if "ld+json" not in h.lower() \
            else Verdict("false_positive", "有 JSON-LD")

    if code == "lang.missing":
        m = re.search(r"<html[^>]*>", h, re.I)
        lv = _attr(m.group(0), "lang") if m else None
        return Verdict("false_positive", f"lang={lv!r}") if lv else Verdict("true_positive", "html 无 lang")

    if code == "lang.not_html_lang":
        return Verdict("unknown", "需按语种判定书写体系")

    if code == "viewport.missing":
        return Verdict("true_positive", "无 viewport") if _meta(h, "viewport") is None else Verdict("false_positive", "有 viewport")

    if code == "viewport.not_responsive":
        v = (_meta(h, "viewport") or "")
        bad = []
        if re.search(r"user-scalable\s*=\s*no", v, re.I):
            bad.append("user-scalable=no")
        if re.search(r"width\s*=\s*\d{3,}", v, re.I):
            bad.append("固定像素宽度")
        return Verdict("true_positive", f"viewport={v!r} {bad}") if bad else Verdict("false_positive", f"viewport={v!r}")

    if code == "title.pixel_overflow":
        t = _title(h)
        if t is None:
            return Verdict("false_positive", "无 title")
        # 独立估算像素宽：CJK 约 14px/字，其余约 7.5px/字
        w = sum(14 if ord(c) > 0x2E80 else 7.5 for c in t)
        return Verdict("true_positive", f"约 {w:.0f}px > 580") if w > 580 else Verdict("false_positive", f"约 {w:.0f}px")

    if code == "title.duplicate":
        return Verdict("unknown", "需跨页比对")

    if code == "sitemap.missing":
        return Verdict("unknown", "需回源 /sitemap.xml 与 robots 声明")

    if code == "http.mixed_content":
        # 协议相对 URL（//host/x）在 https 页面上不构成混合内容，
        # 所以只作提示、不计入准确率分母。
        n = len(re.findall(r'(?:src|href)\s*=\s*["\']//', h, re.I))
        return Verdict("unknown", f"协议相对 URL {n} 处，需看页面协议")

    if code == "link.noanchor":
        bad = [t for t in _tags(h, r"<a\b[^>]*>.*?</a>") if not _strip(t) and "aria-label" not in t and "title=" not in t]
        if not bad:
            # 没有空链接，但也不能直接判误报：页是 JS 渲染时，静态 HTML
            # 根本看不到客户端插入的链接。真实样本 www.csdn.net 就是这种。
            # 判 unknown（不计入分母）比判误报诚实。
            if _looks_js_rendered(h):
                return Verdict("unknown", "静态 HTML 无空链接，但页面疑似 JS 渲染，结论不可靠")
            return Verdict("false_positive", "无空链接")
        return Verdict("true_positive", f"{len(bad)} 个空链接")

    if code.startswith("hreflang."):
        has = re.search(r'rel\s*=\s*["\'][^"\']*alternate', h, re.I) and "hreflang" in h.lower()
        if code == "hreflang.missing":
            return Verdict("unknown", "多语言站需判断是否该有")
        return Verdict("false_positive", "有 hreflang") if has else Verdict("true_positive", "确实无 hreflang 声明")

    return Verdict("unknown", f"核对器未覆盖 {code}")


FIELD = {"true_positive": "tp", "false_positive": "fp", "noisy": "noisy", "unknown": "unknown"}


@dataclass
class Stat:
    tp: int = 0
    fp: int = 0
    noisy: int = 0
    unknown: int = 0
    samples: list[str] = field(default_factory=list)


def main(argv: list[str]) -> int:
    paths: list[str] = []
    for a in argv[1:]:
        paths.extend(sorted(glob.glob(a)) if "*" in a else [a])
    if not paths:
        print("用法: verify_findings.py reports/fp_json/*.json", file=sys.stderr)
        return 2

    rows: list[tuple[str, str, str, dict]] = []
    for p in paths:
        site = p.rsplit("/", 1)[-1][:-5]
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        for iss in d.get("issues", []):
            rows.append((iss.get("code", "?"), iss.get("url", ""), site, iss.get("evidence") or {}))

    print(f"站点 {len(paths)} 个，发现项 {len(rows)} 条，开始回源核对…\n", file=sys.stderr)

    def work(r):
        code, url, site, ev = r
        if not url:
            return (code, site, "unknown", "无 url（站点级规则）", ev)
        v = verify(code, url, fetch(url), ev)
        return (code, site, v.state, v.note, ev)

    results: list[tuple[str, str, str, str, dict]] = []
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for i, out in enumerate(ex.map(work, rows), 1):
            results.append(out)
            if i % 40 == 0:
                print(f"  …{i}/{len(rows)}", file=sys.stderr)

    stats: dict[str, Stat] = defaultdict(Stat)
    for code, site, state, note, _ev in results:
        s = stats[code]
        f = FIELD.get(state, "unknown")
        setattr(s, f, getattr(s, f) + 1)
        if state in ("false_positive", "noisy") and len(s.samples) < 3:
            s.samples.append(f"{site}: {note}")

    print(f"\n{'规则':<32}{'报':>4}{'属实':>5}{'噪音':>5}{'误报':>5}{'存疑':>5}  {'准确率'}")
    print("-" * 76)
    tot = Stat()
    for code in sorted(stats, key=lambda c: -(stats[c].tp + stats[c].fp + stats[c].noisy)):
        s = stats[code]
        dec = s.tp + s.fp + s.noisy
        acc = f"{s.tp / dec * 100:.0f}%" if dec else "—"
        if dec and s.noisy:
            acc += f" (+{s.noisy / dec * 100:.0f}% 噪音)"
        print(f"{code:<32}{s.tp+s.fp+s.noisy+s.unknown:>4}{s.tp:>5}{s.noisy:>5}{s.fp:>5}{s.unknown:>5}  {acc}")
        for k in ("tp", "fp", "noisy", "unknown"):
            setattr(tot, k, getattr(tot, k) + getattr(s, k))

    dec = tot.tp + tot.fp + tot.noisy
    print("-" * 76)
    print(f"站点 {len(paths)} · 报告 {len(results)} 条 · 可判定 {dec} 条 · 存疑 {tot.unknown} 条")
    print(f"  属实 {tot.tp} · 属实但噪音 {tot.noisy} · 真误报 {tot.fp}")
    if dec:
        print(f"\n  严格准确率 {tot.tp / dec * 100:.1f}%  (PLAN 要求 ≥90%)")
        print(f"  含噪音容忍 {(tot.tp + tot.noisy) / dec * 100:.1f}%")

    act = [(c, s) for c, s in stats.items() if s.fp or s.noisy]
    if act:
        print("\n=== 需要处置 ===")
        for c, s in sorted(act, key=lambda x: -(x[1].fp + x[1].noisy)):
            if s.samples:
                print(f"\n{c}  (误报 {s.fp} / 噪音 {s.noisy})")
                for x in s.samples:
                    print(f"    - {x}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
