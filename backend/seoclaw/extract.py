"""
HTML 提取层：把原始 HTML 变成结构化的 `Page` 对象。

设计要点：
  - 一次性把所有规则可能用到的字段抽出来，规则层不再碰 HTML（只读结构化数据）
  - 任何单点解析失败都不能让整页解析崩溃，坏字段降级为 None
  - 中英文的「长度阈值」差异集中在这里处理，不散落到规则里
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import trafilatura
from lxml import html as lxml_html

from .models import ImageRef, LinkKind, LinkRef, Page
from .util import is_internal, normalize_url

# --------------------------------------------------------------------------
# 站点级判定
# --------------------------------------------------------------------------

# 常见的非 HTML 资源：抓到了直接标 is_html=False
NON_HTML_CONTENT_TYPES = {
    "text/css", "application/javascript", "text/javascript",
    "application/json", "image/", "video/", "audio/", "font/",
    "application/pdf", "application/zip", "text/csv",
}

# robots meta 里表示「不要收录」的指令
NOINDEX_TOKENS = {"noindex", "none"}


def is_html_response(content_type: str) -> bool:
    ct = (content_type or "").lower()
    if not ct:
        return True  # 没声明时按 HTML 处理，后续解析失败会标记
    if ct.startswith("text/html") or ct.startswith("application/xhtml"):
        return True
    return not any(ct.startswith(p) or p in ct for p in NON_HTML_CONTENT_TYPES)


# --------------------------------------------------------------------------
# 文本长度阈值（中英文分开）
# --------------------------------------------------------------------------

# 中文标题按「字符」算，15~30 字最佳；英文按字符数算，50~60 字符最佳
TITLE_MAX_CHARS_ZH = 30
TITLE_MAX_CHARS_EN = 60
TITLE_MIN_CHARS = 15
META_MAX_CHARS_ZH = 78
META_MAX_CHARS_EN = 160

# 软 404 判定：正文低于此字数且返回 200
THIN_CONTENT_WORDS = 300

# 「内容靠 JS 渲染」的启发式阈值。四个数都写在代码里而不是散在规则里，
# 因为它们是同一个判据的几条腿，改一条就要能同时看到另外几条。
# 数值来自 diag_js.py 的分组量测（候选 11 条 vs 已知饱满的 JS 站 4 个），
# 详见 _looks_js_rendered_shell 的 docstring。
_JS_RENDERED_MAX_TEXT = 300      # 静态可见文本上限（字符）
_JS_RENDERED_MIN_BYTES = 50000   # HTML 体积下限：远高于错误页的 2-20KB
_JS_RENDERED_MAX_LINKS = 10      # 站内出链上限
_JS_MOUNT_RE = re.compile(
    r'id\s*=\s*["\'](root|app|__next|__nuxt|__gatsby)["\']', re.I
)
# ⚠️ 光有上面那个不够。我第一版只认 root/app/__next/__nuxt/__gatsby 四个
# 标准挂载点，结果 www.agoda.com 的 5 条一条没抓住——它用的是
# ``<div id="agoda-spa">``，挂载点既不叫 root 也不叫 app。
# 真实站点里挂载点叫什么是自由的（agoda-spa、main、my-app……），
# 把「框架」等同于「标准挂载点」是错的。
# 改用框架指令特征：Vue 的 v-xxx、React 的 data-reactroot、Angular 的 ng-app
# —— 这些是渲染后必然存在于 DOM 上的痕迹，比挂载点名稳定得多。
_JS_FRAMEWORK_RE = re.compile(
    r"(<[a-z][^>]*\sv-[a-z][\w-]*\s*=)"   # Vue 指令：v-if / v-for / v-model
    r"|(data-reactroot)"
    r"|(ng-app|ng-version)"
    r"|(__NUXT__|__NEXT_DATA__|window\.___gatsby)",
    re.I,
)

# 客户端渲染失败壳：服务端返回 200，但页面正文其实是「JS 没跑起来」的
# 报错页。这种页面量它没有 h1/description/canonical 是**我们没拿到页面**，
# 不是**站点没做 SEO**——同一个坑我已经在核对器里栽过一次。
#
# 实测：pypi.org/project/256-encrypt/ 等 3 个 URL 抓取时返回 200，正文是
# "A required part of this site couldn't load. This may be due to a browser
# extension, network issues, or browser settings."（209 词），于是
# h1.missing / meta.missing / canonical.missing / soft404 四条规则齐刷刷开火。
# 复测时同一批 URL 又全部正常——说明是当时前端加载失败，不是我们解析错。
#
# ⚠️ 为什么这里可以用「文案」而核对器里的「页面薄」被我删掉了：
# 判据必须是**正面证据**。页面薄只说明内容少，thin page 依然是真页面；
# 而「服务器自己承认 JS 加载失败了」是确凿的失败信号。两者性质不同。
#
# 命中后写入 page.error —— 审计引擎会跳过所有页面级规则
# （engine.py: `if not page.is_html or page.error: continue`），
# 也就不会被算成站点问题。跟 4xx 页面的处理路径一致。
_CLIENT_RENDER_FAILURE = (
    "a required part of this site couldn't load",
    "a required part of this site could not load",
    "a required part of the site couldn't load",
    "this site can't be reached",
    "application error: a client-side exception has occurred",
    "chunk load error",
    "loading chunk",
)
# ⚠️ 引号必须归一化。真实 pypi 页面写的是 U+2019 弯引号「couldn’t」，
# 我第一版规则表里写的是直引号「couldn't」——同一句话两个字符，匹配不上。
# 而单元测试全绿，因为我照着自己写的样本写的：又是自己给自己判卷。
# 这个坑的代价很贵：真实扫描里 8 条误报一条没少，测试却 216 全过。
_APOSTROPHES = str.maketrans({"‘": "'", "’": "'", "ʼ": "'", "`": "'", "´": "'"})


def _norm_quotes(text: str) -> str:
    return (text or "").translate(_APOSTROPHES).lower()


_CLIENT_ERROR_RE = re.compile("|".join(re.escape(s) for s in _CLIENT_RENDER_FAILURE), re.I)

# 人机挑战 / 风控拦截页：服务器不让我们看正文。
#
# ⚠️ 这跟「客户端渲染失败」是两回事，不能混：
#   客户端渲染失败 = 框架存在，但 chunk 没加载起来（需要框架证据）
#   人机挑战       = 服务器直接拿挑战页代替正文（**不需要**框架证据）
# 我第一版把两者合在一起、且要求「页面有框架标记」才判失败，结果 pypi
# 的挑战页两条都不满足 → 8 条误报原样留着。挑战页里恰恰没有框架标记，
# 因为真页面压根没被送到我们手上。
_BOT_CHALLENGE = (
    "client challenge",
    "enable javascript to proceed",
    "checking your browser",
    "just a moment",
    "verify you are human",
    "cf-browser-verification",
    "ddos protection by",
    "enable javascript and cookies to continue",
)
_BOT_CHALLENGE_RE = re.compile("|".join(re.escape(s) for s in _BOT_CHALLENGE), re.I)

_JS_ROOT_RE = re.compile(
    r'<div[^>]+id\s*=\s*["\'](root|app|__next|__nuxt|__gatsby)["\']', re.I
)
_FW_RE = re.compile(r"(react|vue|angular|next|nuxt|svelte|webpack)", re.I)

# 报错壳的正文都很短。放宽到 600 字符而不是 200：宁可漏判也别误伤
# 真正内容短但有效的页面。
_CLIENT_SHELL_MAX_CHARS = 600


def _looks_client_render_failure(raw_html: str, page: Page) -> bool:
    """是不是「HTTP 200 但正文不是真页面」的两种情况。

    路径 A —— 人机挑战 / 风控页：**不需要**框架证据。
      服务器拿挑战页代替了正文（pypi 实测："Client Challenge JavaScript
      is disabled in your browser. Please enable JavaScript to proceed."）。
      这时候页面里根本不会有框架标记——真页面压根没送到我们手上，
      拿「有框架标记」当条件会永远漏掉它。我第一版就是这么错的。

    路径 B —— 客户端渲染失败：**需要**框架证据。
      框架在、挂载点在，但 chunk 没加载起来（"A required part of this
      site couldn't load"）。这条要框架证据，是为了不把技术博客里
      讨论 "chunk load error" 的文章误判成坏页。

    两条路径都要求正文很短：真页面不会同时是报错文案 + 极短正文。

    ⚠️ 判据必须是**正面证据**。「页面薄」不能当证据——thin page 依然是
    真页面，我们观察到了就该拿规则去量它。判「没拿到」必须有服务器或
    浏览器明确留下的失败痕迹。
    """
    if not page.text:
        return False
    # ⚠️ 判据必须看**原始 HTML 的可见文本**，不能看 page.text。
    # page.text 来自 trafilatura，是另一个有损步骤——它会把报错壳里的
    # <h1> 当导航标题丢掉，只留下 <p>。我第一版用 page.text 判，
    # 四个用例全挂：page.text = 'This may be due to a browser extension...'
    # 而真正标记「加载失败」的那句在 <h1> 里，已经被 trafilatura 吃掉了。
    # 判定「页面根本没加载出来」这件事，不该依赖正文抽取器恰好保留哪句话。
    visible = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>", " ", raw_html, flags=re.I | re.S
    )
    visible = re.sub(r"<[^>]+>", " ", visible)
    visible = _WS_RE.sub(" ", visible).strip()
    if not visible or len(visible) > _CLIENT_SHELL_MAX_CHARS:
        return False

    low = _norm_quotes(visible)
    if _BOT_CHALLENGE_RE.search(low):
        return True
    return bool(
        _CLIENT_ERROR_RE.search(low)
        and (_JS_ROOT_RE.search(raw_html) or _FW_RE.search(raw_html))
    )

_WS_RE = re.compile(r"\s+")


def _clean(text: Optional[str]) -> str:
    if not text:
        return ""
    return _WS_RE.sub(" ", text).strip()


# --------------------------------------------------------------------------
# 主解析入口
# --------------------------------------------------------------------------


def extract_page(
    url: str,
    raw_html: str,
    *,
    status_code: int = 200,
    content_type: str = "text/html",
    final_url: Optional[str] = None,
    depth: int = 0,
    discovered_from: Optional[str] = None,
    elapsed_ms: Optional[int] = None,
) -> Page:
    """把原始 HTML 解析为 `Page`。

    这是产品里最关键的一次「信息损失」发生地——尽量多保留字段，
    后面规则才有依据。
    """
    base_url = final_url or url
    domain = urlparse(base_url).netloc

    page = Page(
        url=url,
        final_url=final_url,
        status_code=status_code,
        content_type=content_type,
        depth=depth,
        discovered_from=discovered_from,
        elapsed_ms=elapsed_ms,
        is_html=is_html_response(content_type),
    )
    if not raw_html or not page.is_html:
        return page

    try:
        doc = lxml_html.fromstring(raw_html)
    except Exception as exc:  # noqa: BLE001 — 坏 HTML 不能让整页失败
        page.error = f"html_parse_failed: {exc}"
        return page

    _extract_head(doc, page, base_url, domain)
    _extract_i18n_and_social(doc, page, base_url)
    _extract_headings(doc, page)
    _extract_images(doc, page, base_url, domain)
    _extract_links(doc, page, base_url, domain)
    _extract_structured_data(doc, page)
    _extract_text(raw_html, base_url, page)
    _derive(page, raw_html, domain)

    # HTTP 200 但正文是 JS 报错壳：标记 error，让审计引擎跳过所有页面级规则。
    # 放在最后：必须先抽完正文/框架特征才能判断，否则拿到的是半成品。
    if _looks_client_render_failure(raw_html, page):
        page.error = "client_render_failed"

    page.content_hash = _content_hash(page)
    return page


def _content_hash(page: Page) -> str:
    """规范化内容的摘要 —— 增量扫描的判定基准。

    ⚠️ 只覆盖**规则会读的语义字段**，且必须排除每次都变的值：
    fetched_at / elapsed_ms / not_modified 一旦参与比较，哈希每次都不同，
    全部页面每次都会被判「已变」，60+ 条规则无限重跑，增量扫描等于没做。

    刻意**不**包含 raw_html 整体：广告位轮播、CSRF token、时间戳都会让
    同一篇文章的哈希天天变，而那些东西规则根本不读。

    提取失败时返回空串 —— 上一轮算不出 hash 时不能当成「内容没变」。
    """
    if not page.text and not page.title and not page.status_code:
        return ""
    parts = [
        str(page.status_code),
        page.title or "",
        page.meta_description or "",
        page.canonical or "",
        page.robots_meta or "",
        page.viewport or "",
        page.lang or "",
        repr(sorted(page.hreflang)),
        page.og_title or "",
        page.og_description or "",
        page.og_image or "",
        page.twitter_card or "",
        repr(page.h1),
        repr(sorted(page.headings)),
        page.text,
        repr(page.links),
        repr([(i.src, i.alt) for i in page.images]),
        repr(page.microdata_types),
        str(page.jsonld),
    ]
    return hashlib.sha256("\u0000".join(parts).encode("utf-8")).hexdigest()[:32]


# --------------------------------------------------------------------------
# 各字段提取
# --------------------------------------------------------------------------


def _meta_content(doc: Any, name: str) -> Optional[str]:
    """按 name 找 meta（兼容大小写与属性顺序差异）。"""
    for el in doc.xpath(f"//meta[@name='{name}']"):
        return (el.get("content") or "").strip() or None
    # 大小写兜底
    for el in doc.xpath("//meta[@name]"):
        if (el.get("name") or "").lower() == name.lower():
            return (el.get("content") or "").strip() or None
    return None


def _extract_head(doc: Any, page: Page, base_url: str, domain: str) -> None:
    # <title>
    titles = doc.xpath("//head/title/text() | //title/text()")
    page.title = _clean(titles[0]) if titles else None

    # meta description / robots / viewport
    page.meta_description = _clean(_meta_content(doc, "description")) or None
    page.robots_meta = _meta_content(doc, "robots")
    page.viewport = _meta_content(doc, "viewport")

    # canonical
    canon_nodes = doc.xpath("//link[@rel='canonical']/@href")
    if not canon_nodes:
        canon_nodes = doc.xpath("//link[@rel='Canonical']/@href")
    if canon_nodes:
        raw = canon_nodes[0].strip()
        page.canonical = urljoin(base_url, raw) if raw else None

    # <html lang>
    html_nodes = doc.xpath("//html")
    if html_nodes:
        page.lang = html_nodes[0].get("lang")

    page.title_length = len(page.title or "")
    page.meta_description_length = len(page.meta_description or "")


def _extract_i18n_and_social(doc: Any, page: Page, base_url: str) -> None:
    """采集 hreflang 与 Open Graph / Twitter Card。

    这两组字段是被规则子任务反复卡住后补上的：没有它们，
    hreflang、社交分享卡片类规则只能靠猜——要么永不触发，要么乱触发。
    数据层不支持的规则写出来比不写更糟。
    """
    # hreflang: <link rel="alternate" hreflang="zh-CN" href="...">
    for el in doc.xpath("//link[@rel]"):
        rel = (el.get("rel") or "").lower().strip()
        if "alternate" not in rel.split():
            continue
        code = (el.get("hreflang") or "").strip()
        if not code:
            continue
        href = (el.get("href") or "").strip()
        if not href:
            continue
        page.hreflang.append((code, urljoin(base_url, href)))

    # Open Graph / Twitter Card：社交分享卡片的来源
    for el in doc.xpath("//meta[@property] | //meta[@name]"):
        key = (el.get("property") or el.get("name") or "").strip().lower()
        content = (el.get("content") or "").strip()
        if not content:
            continue
        if key == "og:title":
            page.og_title = content
        elif key == "og:description":
            page.og_description = content
        elif key == "og:image":
            page.og_image = urljoin(base_url, content)
        elif key == "og:type":
            page.og_type = content
        elif key == "og:url":
            page.og_url = urljoin(base_url, content)
        elif key == "twitter:card":
            page.twitter_card = content


def _extract_headings(doc: Any, page: Page) -> None:
    for level in range(1, 7):
        for el in doc.xpath(f"//h{level}"):
            text = _clean(" ".join(el.itertext()))
            if text:
                page.headings.append((level, text))
                if level == 1:
                    page.h1.append(text)


def _extract_images(doc: Any, page: Page, base_url: str, domain: str) -> None:
    for el in doc.xpath("//img"):
        src = (el.get("src") or el.get("data-src") or "").strip()
        if not src:
            continue
        absolute = urljoin(base_url, src)
        if not is_internal(absolute, domain):
            # 只统计站内图片，外站图片的 alt 不影响本站 SEO
            continue
        try:
            width = int(el.get("width")) if el.get("width") else None
        except (TypeError, ValueError):
            width = None
        try:
            height = int(el.get("height")) if el.get("height") else None
        except (TypeError, ValueError):
            height = None
        page.images.append(
            ImageRef(src=absolute, alt=el.get("alt"), width=width, height=height)
        )


# 纯符号/装饰性字符：作为锚文本对 SEO 毫无价值
_SYMBOL_ONLY_RE = re.compile(r"^[\W_]*$", re.UNICODE)


def _has_meaningful_text(text: str) -> bool:
    """锚文本是否含有实际内容。

    纯符号（› « → ＋ …）虽然非空，但对 SEO 毫无价值，
    这类链接应回退到 img[alt] / aria-label / title。
    """
    if not text:
        return False
    if _SYMBOL_ONLY_RE.match(text):
        return False
    # 中日韩字符也算有意义
    return True


def _anchor_text(el: Any) -> str:
    """提取链接的锚文本。

    只取 itertext() 会遗漏三种很常见的情况（实测踩过的坑）：
      1. <a><img alt="Python logo"></a>  —— 图片 logo 链接，文本在 img[alt] 里
      2. <a aria-label="上一页">›</a>    —— 可见文字是纯符号，无语义
      3. <a title="上一页"><span>←</span></a> —— 文字藏在 title 属性里
    这三类在导航和分页里极常见，漏掉会造成大面积假阳性
    （实测 docs.python.org 上一次扫出 28 条）。
    """
    text = _clean(" ".join(el.itertext()))
    if _has_meaningful_text(text):
        return text

    # 回退：img[alt] → aria-label → title → 图标类 class 名
    for img in el.xpath(".//img[@alt]"):
        alt = _clean(img.get("alt") or "")
        if _has_meaningful_text(alt):
            return alt

    for attr in ("aria-label", "title", "data-title"):
        value = _clean(el.get(attr) or "")
        if _has_meaningful_text(value):
            return value

    # ⚠️ 2026-09-30 修：只看 <a> 自身的 aria-label 会漏掉**嵌套在子元素上的**。
    # 实测 figma.com/pricing 的 logo 链接是：
    #     <a href="..."><svg aria-label="Homepage">…</svg></a>
    # 标签在 <svg> 上，<a> 本身没有，于是被判成「空锚」——19 站回归里 5 条误报
    # 全部是这个形态。这是**提取层的缺陷**，不是规则的错。
    for node in el.xpath(
        ".//*[@aria-label or @data-title]"
    ):
        value = _clean(node.get("aria-label") or node.get("data-title") or "")
        if _has_meaningful_text(value):
            return value

    # SVG 内部的 <title> 同样是常见命名方式
    for t in el.xpath(".//svg/title"):
        value = _clean(" ".join(t.itertext()))
        if _has_meaningful_text(value):
            return value

    # 常见的视觉隐藏文字 span/p（SEO 框架爱用）
    for hidden in el.xpath(
        ".//*[contains(@class,'visually-hidden') or contains(@class,'sr-only')"
        " or contains(@class,'screen-reader') or contains(@class,'sr-only-text')]"
    ):
        value = _clean(" ".join(hidden.itertext()))
        if _has_meaningful_text(value):
            return value

    return text  # 保留原样（哪怕是符号），让 link.noanchor 规则能提示


def _is_decorative(el: Any, anchor: str) -> bool:
    """纯装饰性链接：对可见用户、读屏软件和爬虫都不构成锚文本。

    判据是 **<a> 自身** 被显式排除在可访问性树之外，且拿不到任何锚文本：

        <a href="/x" aria-hidden="true" tabindex="-1"><img src="logo.svg" alt=""></a>

    这类在大型站点上极常见——ocw.mit.edu 首页 887 个链接里 114 个锚文本
    为空，其中 **96 个**正是这种 logo 图标链接（实测），且它们的
    ``<img alt="">`` 也为空。

    不排除的话 link.noanchor 会在该站永久亮红灯，而用户能做的只是往
    alt 里填字 —— 而这些图标对读屏用户本就不可见，填了也没用。

    两个条件都成立才算：
      1. ``aria-hidden="true"`` 或 ``tabindex="-1"`` 写在 <a> 自己身上
         （不是内部的 <img> 身上 —— 后者只说明图片被隐藏，链接仍可见）
      2. 抽出来的锚文本为空（含 img alt / aria-label / title 都为空）
    """
    if anchor.strip():
        return False
    return (el.get("aria-hidden") or "").strip().lower() == "true" or (
        el.get("tabindex") or ""
    ).strip() == "-1"


def _extract_links(doc: Any, page: Page, base_url: str, domain: str) -> None:
    for el in doc.xpath("//a[@href]"):
        href = (el.get("href") or "").strip()
        # href="" 指向当前页，不是真链接（实测某些模板会输出这种空壳 <a>）
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absolute = urljoin(base_url, href)
        # urljoin 会把 href="" 解析成 base_url，这里再挡一次
        if normalize_url(absolute) == normalize_url(base_url):
            continue
        internal = is_internal(absolute, domain)
        rel = (el.get("rel") or "").lower()
        anchor = _anchor_text(el)
        page.links.append(
            LinkRef(
                href=absolute,
                anchor=anchor,
                kind=LinkKind.INTERNAL if internal else LinkKind.EXTERNAL,
                nofollow="nofollow" in rel,
                decorative=_is_decorative(el, anchor),
            )
        )
    page.internal_link_count = sum(
        1 for link in page.links if link.kind == LinkKind.INTERNAL
    )
    page.external_link_count = sum(
        1 for link in page.links if link.kind == LinkKind.EXTERNAL
    )


def _extract_structured_data(doc: Any, page: Page) -> None:
    """解析 JSON-LD 脚本块。

    优先自己解 JSON（比引入 extruct 轻量），失败则跳过——
    Schema.org 检查项只关心「有没有、类型对不对、字段全不全」。
    """
    import json

    for el in doc.xpath("//script[@type='application/ld+json']"):
        raw = (el.text or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue
        # JSON-LD 顶层可能是对象、数组，或 @graph 包裹
        candidates: list[Any]
        if isinstance(data, list):
            candidates = data
        elif isinstance(data, dict):
            if "@graph" in data and isinstance(data["@graph"], list):
                candidates = data["@graph"]
            else:
                candidates = [data]
        else:
            continue
        for item in candidates:
            if isinstance(item, dict):
                page.jsonld.append(item)

    # Microdata：只记 itemtype，用于「有没有用结构化数据」的判断
    for itemtype in doc.xpath("//*[@itemtype]/@itemtype"):
        if itemtype:
            page.microdata_types.append(itemtype.split("/")[-1].rstrip("/"))


def _full_visible_text(raw_html: str) -> str:
    """全量可见文本：只去掉 script/style，导航与页脚都保留。

    与 page.text 的区别就在这里——page.text 是 trafilatura 抽的「主体正文」，
    导航/页脚/页眉都被它剥掉了；这个函数保留它们，所以能回答
    「这个页面上到底有没有东西」而不只是「主体段落写了多少」。
    """
    t = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", raw_html, flags=re.I | re.S)
    return _WS_RE.sub(" ", re.sub(r"<[^>]+>", " ", t)).strip()


def _extract_text(raw_html: str, base_url: str, page: Page) -> None:
    """正文抽取用 trafilatura（去导航/页脚/广告效果最好）。"""
    try:
        extracted = trafilatura.extract(
            raw_html,
            url=base_url,
            include_comments=False,
            include_tables=True,
            favor_precision=True,
        )
    except Exception:  # noqa: BLE001
        extracted = None

    if not extracted:
        # trafilatura 对极简页面会返回 None，退化为标签剥离
        try:
            doc = lxml_html.fromstring(raw_html)
            for bad in doc.xpath("//script|//style|//nav|//footer|//header|//noscript"):
                bad.getparent().remove(bad)
            extracted = " ".join(doc.itertext())
        except Exception:  # noqa: BLE001
            extracted = ""

    page.text = _clean(extracted)
    # 中英文混排时用「字符数」比「分词数」更稳定，这里取两者较大值避免误判
    page.word_count = max(
        len(page.text),
        len(page.text.split()),
    )
    page.content_is_thin = page.word_count < THIN_CONTENT_WORDS

    # ⚠️ 第二个尺子：全量可见文本（只去 script/style，导航页脚都算）。
    #
    # 为什么必须要有它：page.text 来自 trafilatura，而 trafilatura **会主动
    # 剥掉 nav/footer/header**。于是导航重的页面 word_count 必然被压低——
    # japanpost.jp 首页剥后 74 字符、含导航 1433 字符、223 条站内出链。
    # soft404 规则拿 word_count 判「这页是不是空的」，是在用一把有偏的尺子量，
    # 结果给 55 个正常页面报了「疑似软 404」。
    #
    # 两个尺子各有用途，别互相替代：
    #   word_count        → 看主体内容质量（该字段存在的原因）
    #   full_text_length  → 看页面到底有没有东西（反「尺子量错了」）
    page.full_text_length = len(_full_visible_text(raw_html))


# 浏览器会自动发起子资源请求的 <link rel> 值。
# 不在这个白名单里的（alternate/hreflang、canonical、me、license、author、
# search、next、prev 等）只是声明关系，不会加载资源，因此不构成混合内容。
_FETCHED_LINK_RELS = {
    "stylesheet", "icon", "shortcut", "apple-touch-icon", "apple-touch-icon-precomposed",
    "mask-icon", "manifest", "preload", "prefetch", "preconnect",
    "dns-prefetch", "prerender", "modulepreload", "subresource", "pingback",
}


def _is_fetched_link(el: Any) -> bool:
    """判断一个 <link> 是否会被浏览器自动加载。

    必须做这个区分：<link rel="alternate" href="http://..."> 和
    <link rel="canonical" href="http://..."> 只是声明元数据，
    不会发起请求，判成混合内容就是误报。
    """
    rel = (el.get("rel") or "").strip().lower().split()
    if not rel:
        # 没有 rel 的 <link> 不当作资源加载（严格来说无效元素）
        return False
    # hreflang 会被 rel="alternate" 修饰，此时取第一个有意义的关系即可
    return any(r in _FETCHED_LINK_RELS for r in rel)


def _looks_js_rendered_shell(page: Page, raw_html: str) -> bool:
    """正文是不是靠 JS 客户端渲染，静态 HTML 里看不到。

    ⚠️ 这个标记存在的原因：没有它，soft404 规则会把「没渲染出来」当成
    「页面是空的」。实测 www.agoda.com 一个 733KB 的页面，全量可见文本
    **0 字**，被判成 likely_true_soft404 + HIGH——用户会收到
    「高危：你这页是空页面」，然后去改一个内容饱满的电商首页。

    规则层光看 word_count=0 分不出两件事：
        这页没内容        vs        这页内容我看不见
    必须提取层把事实递给它。

    ⚠️ 判据是靠**量测**定下来的，不是拍的。diag_js.py 拿 11 条候选对比
    4 个已知饱满的 JS 站页面：
      - 单独用「HTML 体积」当判别式 **不成立**：>=100KB 时候选命中 6/11、
        对照全中（shopify 662KB / airbnb 651KB / stripe 625KB）。
        正常页面比 JS 空壳还大。
      - 成立的是**组合信号**：大体积本身无意义，但「大到不像错误页」
        与「静态里一个字都没有」同时成立，就只能是内容在 JS 里。
          agoda      733KB  文本 0    出链 0-3   → 命中
          intercom   318KB  文本 32   出链 0     → 命中
          shopify    662KB  文本 6859 出链 186   → 不命中（它有真内容）
          ghost.org 2618B  文本 174  出链 3     → 不命中（那才是真空页）
    50KB 的下限来自错误页的实际体量：带样板导航的错误页通常 2-20KB，
    50KB 远在其上；同时对照组全部有正文，不存在误伤。

    第 3 个条件（出链少）不能省：内容在 JS 里时，静态 HTML 里通常也没
    几条 <a>。少了它，shopify 那种「有内容但链接也少」的页可能被误标。
    """
    if page.full_text_length >= _JS_RENDERED_MAX_TEXT:
        return False
    if page.internal_link_count >= _JS_RENDERED_MAX_LINKS:
        return False
    # 体积够大：说明这不是一个「老实」的错误页，而是一堆 JS 包
    if len(raw_html) >= _JS_RENDERED_MIN_BYTES:
        return True
    # 体积不大时，只认明确的框架痕迹（Vue 指令 / reactroot / ng-app /
    # __NUXT__ 等）。⚠️ 不能只认标准挂载点 id=root|app|__next|__nuxt：
    # agoda 用的是 <div id="agoda-spa">，挂载点叫什么在真实站点里是自由的。
    return bool(_JS_MOUNT_RE.search(raw_html) or _JS_FRAMEWORK_RE.search(raw_html))


def _derive(page: Page, raw_html: str, domain: str) -> None:
    """派生标记，避免每条规则重复计算。"""
    page.likely_js_rendered = _looks_js_rendered_shell(page, raw_html)

    # 混合内容：HTTPS 页面里引用了 http:// 的非锚点资源
    if page.final_url and page.final_url.lower().startswith("https://"):
        try:
            doc = lxml_html.fromstring(raw_html)
            mixed: list[str] = []
            # 只看子资源，<a href> 是用户主动点击的链接，浏览器不会拦截，不算混合内容
            # （曾踩坑：用 src|href 正则匹配全页，把 <a href="http://..."> 也当成混合内容，
            #   在 rust-lang.org 上造成 8 条纯误报）
            for el in doc.xpath(
                "//img[@src] | //script[@src] | //link[@href] | //iframe[@src]"
                " | //embed[@src] | //object[@data] | //video[@src] | //audio[@src]"
                " | //source[@src] | //track[@src] | //input[@src]"
            ):
                tag = el.tag if isinstance(el.tag, str) else ""
                for attr in ("src", "href", "data"):
                    value = (el.get(attr) or "").strip()
                    if not value.lower().startswith("http://"):
                        continue
                    # <link> 需要看 rel：浏览器只会自动拉取少数几种 rel，
                    # rel=alternate(hreflang/canonical/RSS)、rel=me、rel=license
                    # 等只是声明关系，不会发起子资源请求，不构成混合内容。
                    if tag == "link" and not _is_fetched_link(el):
                        continue
                    mixed.append(f"<{tag} {attr}={value[:80]}>")
                    break
            page.has_mixed_content = bool(mixed)
            page.mixed_content_samples = mixed[:10]
        except Exception:  # noqa: BLE001
            page.has_mixed_content = False
