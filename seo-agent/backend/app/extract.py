"""
HTML 提取层：把原始 HTML 变成结构化的 `Page` 对象。

设计要点：
  - 一次性把所有规则可能用到的字段抽出来，规则层不再碰 HTML（只读结构化数据）
  - 任何单点解析失败都不能让整页解析崩溃，坏字段降级为 None
  - 中英文的「长度阈值」差异集中在这里处理，不散落到规则里
"""

from __future__ import annotations

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

    return page


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

    # 常见的视觉隐藏文字 span/p（SEO 框架爱用）
    for hidden in el.xpath(
        ".//*[contains(@class,'visually-hidden') or contains(@class,'sr-only')"
        " or contains(@class,'screen-reader') or contains(@class,'sr-only-text')]"
    ):
        value = _clean(" ".join(hidden.itertext()))
        if _has_meaningful_text(value):
            return value

    return text  # 保留原样（哪怕是符号），让 link.noanchor 规则能提示


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
        page.links.append(
            LinkRef(
                href=absolute,
                anchor=_anchor_text(el),
                kind=LinkKind.INTERNAL if internal else LinkKind.EXTERNAL,
                nofollow="nofollow" in rel,
            )
        )
    page.internal_link_count = sum(1 for l in page.links if l.kind == LinkKind.INTERNAL)
    page.external_link_count = sum(1 for l in page.links if l.kind == LinkKind.EXTERNAL)


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


def _derive(page: Page, raw_html: str, domain: str) -> None:
    """派生标记，避免每条规则重复计算。"""
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
