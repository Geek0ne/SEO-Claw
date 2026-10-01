"""
多语言与社交分享规则包（Google 生态）。

为什么这个文件是「后补」的
------------------------
两个并行的规则子任务都独立放弃了 hreflang 规则，理由相同：
`Page` 模型没有 hreflang 字段、extract 层也没采集 `<link rel="alternate" hreflang>`，
判「有 x-default 却缺 hreflang」必须**正面看到** hreflang 声明，
拿不到数据源就写出来只能是永不触发、或靠猜触发的死规则。

数据层补齐后（models.py 的 `hreflang`/`og_*` 字段 + extract.py 的采集），
这些规则才具备可实现的条件。教训记在这里：
**数据层不支持的规则，写出来比不写更糟**——它会让用户以为这个维度已被检查过。
"""

from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from ....models import Issue, Market, Page, Scope, Severity
from ....util import normalize_url
from ...engine import Rule, RuleContext, default_registry

reg = default_registry()


def _is_cjk_url(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in text)


# 站点自建的「首页别名」末段。真实样本：www.edx.org/ 的 hreflang en 指向
# https://www.edx.org/homepage，而当前 URL 是 https://www.edx.org/。
# 首页别名不是权重转移，也不该被要求补自引用（与 base 包 canonical 的
# index_or_home_alias 同一惯例：按**整段**匹配，避免 /myhomepage 被折叠）。
_HOME_ALIAS_SEGMENTS = frozenset({
    "index", "index.html", "index.htm",
    "home", "home.html", "home.htm", "homepage",
    "default", "default.html", "default.htm",
})


def _split_doc(url_norm: str) -> tuple[str, str]:
    """拆归一化 URL 成 (host, path)，query 另算。"""
    path, _, query = url_norm.partition("?")
    host, _, rest = path.partition("/")
    return host, ("/" + rest if rest else "/")


def _strip_home_alias(path: str) -> str:
    segs = [s for s in path.split("/") if s]
    if segs and segs[-1].lower() in _HOME_ALIAS_SEGMENTS:
        segs = segs[:-1]
    return "/" + "/".join(segs) if segs else "/"


def _same_document(a: str, b: str) -> bool:
    """两个归一化 URL 是否指向同一份文档（允许首页别名差异）。

    仅当 host 相同、且路径只在结尾的首页别名段上有差别时才算同一份。
    /product/index 与 /product 是同一页；/a/home 与 /b/home 不是。
    """
    if not a or not b:
        return False
    if a == b:
        return True
    ha, pa = _split_doc(a)
    hb, pb = _split_doc(b)
    if ha != hb or (a.partition("?")[2]) != (b.partition("?")[2]):
        return False
    return _strip_home_alias(pa) == _strip_home_alias(pb)


def _drop_view_params(url: str) -> str | None:
    """剥掉「同一文档的不同视图」参数（分页/CMS 内部页码）。

    只剥白名单参数名；其它 query（?sort=、?id=123…）保持不动——那些
    可能是真的另一份内容，放过去等于制造漏报。
    """
    parsed = urlparse(url)
    kept = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in HreflangSelfMissing._VIEW_PARAMS
    ]
    if len(kept) == len(parse_qsl(parsed.query, keep_blank_values=True)):
        return None  # 没有视图参数，调用方应回退到原身份
    return urlunparse(parsed._replace(query=urlencode(kept)))


@reg.register
class HreflangMismatchesLang(Rule):
    """hreflang 声明的语言集合与 <html lang> 不一致。

    这类错误很隐蔽：页面 lang="zh-CN" 却只声明了 en/de，
    搜索引擎会把它配对到错误的语言版本上。
    """

    code = "hreflang.inconsistent_with_lang"
    severity = Severity.MEDIUM
    market = Market.GOOGLE
    title = "hreflang 声明与 html lang 不一致"
    description = (
        "多语言站里，<html lang> 描述本页语言，hreflang 描述各语言版本的对应关系。"
        "两者不一致时，搜索引擎可能把本页配对到错误的语言版本上，"
        "导致 A 语言的用户看到 B 语言内容（或反之）。"
    )
    fix_hint = "确保 hreflang 声明里包含本页自身的语言代码，且与 <html lang> 一致。"

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        if page.status_code != 200 or not page.hreflang:
            return
        # ⚠️ x-default 必须排除：它按 "-" 切开得到 "x"，会被当成一种语言塞进
        # declared，于是「html lang=en 只声明了 x-default」会误报成不一致
        # （实测冒烟就撞到：html lang=en ∉ ['x']）。x-default 是兜底标记，
        # 不是语言。下面的 x_default_missing 规则已经单独处理它。
        declared = {
            code.split("-")[0].lower()
            for code, _ in page.hreflang
            if code and code.strip().lower() != "x-default"
        }
        if not declared:
            return
        own = (page.lang or "").split("-")[0].strip().lower()
        if not own or own in declared:
            return
        # 集合里有 x-default 时，「本页语言没被显式声明」不构成不一致——
        # 前提是 x-default 指回**本页自己**（那它就是本页的兜底条目，
        # 本页语言已被它覆盖，不需要再重复声明一次自己）。
        # 真实样本：cloudflare.com 首页 lang=en，集合里 10 种非英语言 +
        # x-default→https://www.cloudflare.com/（=本页）。要求它再补一条
        # en 指向自己，属于让用户去改本来正确的写法。
        # ⚠️ 反过来，x-default 指向**别的**页面时不能放行：那说明本页语言
        # 真的没进集合，可能被配对到错误版本——那才是真问题，仍要报。
        if any(
            code.strip().lower() == "x-default"
            and normalize_url(href) == normalize_url(page.final_url or page.url)
            for code, href in page.hreflang
        ):
            return

        yield self._issue(
            page,
            {
                "html_lang": page.lang,
                "declared_hreflang": sorted({c for c, _ in page.hreflang}),
                "verdict": "inconsistent",
                "verdict_explain": "html lang 指向的语言不在 hreflang 声明中，多语言配对可能出错",
            },
        )


@reg.register
class HreflangSelfMissing(Rule):
    """声明了 hreflang，但漏掉了指向自己且无 hreflang 属性的自引用。

    Google 明确要求：多语言页面的 hreflang 集合必须包含一个自引用条目，
    且该条目的 hreflang 必须与本页 <html lang> 对应。
    """

    code = "hreflang.self_reference_missing"
    severity = Severity.MEDIUM
    market = Market.GOOGLE
    title = "hreflang 缺少指向本页的自引用条目"
    description = (
        "Google 要求：声明了 hreflang 的页面，其 hreflang 集合里必须有一条"
        "指向自己、且 hreflang 值与 <html lang> 一致的条目。缺了这条，"
        "搜索引擎无法确认本页属于哪个语言版本，可能导致整组语言配对失效。"
    )
    fix_hint = (
        "在 hreflang 集合中加入自引用："
        '<link rel="alternate" hreflang="{lang}" href="{self_url}">'
    )
    fix_example = (
        '<link rel="alternate" hreflang="zh-CN" href="https://example.com/zh/">\n'
        '<link rel="alternate" hreflang="en" href="https://example.com/">\n'
        '<link rel="alternate" hreflang="x-default" href="https://example.com/">'
    )

    # 「同一份文档的不同视图」参数：分页、CMS 内部页码。
    # 这些参数标识的是**同一篇文档的一个位置**，不是一篇独立文档，
    # 按 Google 的说法它们本来就不该有自己的 hreflang 集合，
    # 更不该被要求有独立自引用（真实样本：meta.discourse.org 的 ?page=4、
    # pagerduty.com 的 ?page_id=36859，两者集合里都有正确的语言条目，
    # 只是 href 指的是不带该参数的主文档 URL）。
    # 刻意用**白名单参数名**而不是「忽略全部 query」：?sort= ?color= ?id=123
    # 那些确实可能是另一份内容，误当自引用会造成漏报（比误报更坏）。
    _VIEW_PARAMS = frozenset({
        "page", "p", "pag", "pageno", "page_id", "pageid",
        "offset", "start", "startindex",
    })

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        if page.status_code != 200 or not page.hreflang:
            return

        own_url = normalize_url(page.final_url or page.url)
        own_lang = (page.lang or "").split("-")[0].strip().lower()
        if not own_lang:
            return  # 没有 lang 就无从判断自引用该写什么，交给 lang.missing 报

        # 本页对外声明的身份：有 canonical 就以 canonical 为准。
        # Google 要求 hreflang 指向 canonical URL，所以拿请求 URL 去和
        # hreflang 比，在有 canonical 的站点上会稳定地比不相等。
        identity = normalize_url(page.canonical) if page.canonical else own_url
        # 分页视图：拿去掉视图参数的主文档 URL 当身份
        view_base = _drop_view_params(page.final_url or page.url)
        view_identity = normalize_url(view_base) if view_base else ""

        has_self = False
        for code, href in page.hreflang:
            same_lang = code.split("-")[0].strip().lower() == own_lang
            if not (same_lang or code.lower() == "x-default"):
                continue
            target = normalize_url(href)
            if _same_document(target, identity) or _same_document(target, view_identity):
                has_self = True
                break

        if not has_self:
            yield self._issue(
                page,
                {
                    "html_lang": page.lang,
                    "self_url": page.final_url or page.url,
                    "declared_hreflang": [c for c, _ in page.hreflang],
                    "verdict": "missing_self_reference",
                    "verdict_explain": "hreflang 集合里没有指向本页且语言匹配的条目",
                },
            )


@reg.register
class HreflangNoXDefault(Rule):
    """多语言站缺 x-default。"""

    code = "hreflang.x_default_missing"
    severity = Severity.LOW
    market = Market.GOOGLE
    title = "hreflang 集合缺少 x-default"
    description = (
        "x-default 用于指定「该语言版本都匹配不上时」回退到哪个版本，"
        "常见于语言选择页。缺了它通常不影响已有语言对的收录，"
        "但会削弱语言选择的兜底能力。"
    )
    fix_hint = '补一条 <link rel="alternate" hreflang="x-default" href="..."> 指向默认版本（通常是英文版或语言选择页）。'

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        if page.status_code != 200 or not page.hreflang:
            return
        # 只有多语言站才需要 x-default；只有一两个语言时不报
        langs = {c.split("-")[0].lower() for c, _ in page.hreflang if c and c != "x-default"}
        if len(langs) < 2:
            return
        if any(c.lower() == "x-default" for c, _ in page.hreflang):
            return
        yield self._issue(
            page,
            {
                "declared_hreflang": [c for c, _ in page.hreflang],
                "verdict": "missing_x_default",
                "verdict_explain": "已声明多个语言版本但没有 x-default 兜底",
            },
        )


@reg.register
class HreflangPointsToNonHtml(Rule):
    """hreflang 指向了明显不是 HTML 的资源。"""

    code = "hreflang.suspicious_target"
    severity = Severity.HIGH
    market = Market.GOOGLE
    title = "hreflang 指向了可疑地址"
    description = (
        "hreflang 应当指向语言版本页面的完整 URL。若指向了 PDF、图片、"
        "或与语言无关的地址，搜索引擎会把它当作一个独立页面参与配对，"
        "形成指向非内容页的错误语言版本。"
    )
    fix_hint = "把 hreflang 指向对应语言版本的实际页面 URL。"

    _BAD_EXT = re.compile(r"\.(pdf|jpg|jpeg|png|gif|zip|mp4|docx?|xlsx?)$", re.I)

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        if page.status_code != 200 or not page.hreflang:
            return
        bad = [
            {"hreflang": code, "href": href}
            for code, href in page.hreflang
            if self._BAD_EXT.search(urlparse(href).path)
        ]
        if bad:
            yield self._issue(
                page,
                {
                    "suspicious": bad,
                    "verdict": "likely_bug",
                    "verdict_explain": "hreflang 指向了非 HTML 资源，多半是模板填错",
                },
            )


@reg.register
class SocialMetaMissing(Rule):
    """缺少 og: 基础标签。

    这条会**降级**而不是报 HIGH：og 标签只影响社交分享卡片，
    完全不影响搜索排名。报成高危会让用户以为网站出了问题。
    """

    code = "og.basic_missing"
    severity = Severity.LOW
    market = Market.GOOGLE
    # 为什么改成 SITE 级：og 标签写在模板里，是**站点级**属性，不是页面级。
    # 同一站点 5 页全缺 → 本来就是同一个问题的 5 份拷贝。107 站实测这条
    # 贡献 149 条发现、135 条「属实但噪音」、0 条误报——占了全部噪音的 93%，
    # 而没有一条是用户「必须修」的问题。按页报 N 遍就是纯噪音。
    #
    # ⚠️ SITE 级规则的 page 参数是哨兵对象（status_code=0），
    # **绝不能读 page 的字段**——读到的永远是空值，规则会静默失效。
    # 必须走 ctx.all_pages。这个坑真的踩过：改完不报错，就是不触发。
    scope = Scope.SITE
    title = "缺少 Open Graph 标签（影响社交分享卡片）"
    description = (
        "og:title / og:description / og:image 决定链接分享到微信、微博、"
        "Slack、Facebook 时长什么样。缺失时各平台会自己猜标题，"
        "通常是「域名 + 页面标题」，很难看，也不利于点击。\n"
        "⚠️ 这只影响分享效果，**不影响搜索排名**，请按需处理。"
    )
    fix_hint = "至少补 og:title、og:description、og:image 三项。"
    fix_example = (
        '<meta property="og:type" content="website">\n'
        '<meta property="og:title" content="页面标题">\n'
        '<meta property="og:description" content="一句话说明这页在讲什么">\n'
        '<meta property="og:image" content="https://example.com/cover.png">'
    )

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        # ⚠️ 这里**故意不加** ctx.has_enough_data()。
        #
        # 那个门槛（抓够 20 页 + 覆盖率 ≥50%）只适用于靠「**没看到**」下结论的
        # 规则——没发现指向 X 的内链，不代表 X 不存在。og 不是这种：og:title
        # 就写在 <head> 里，我们对每个页面都**正面看到或没看到**，是直接证据。
        #
        # 我第一版照抄了 schema.missing 的守卫，结果扫描用 --max-pages 5，
        # crawled 永远 <20 → 这条规则**永远不会触发**。准确率会因为它闭眼
        # 而"变好看"——那是我一整晚在治的同一个病：把沉默当成修复。
        observed = [p for p in ctx.all_pages if p.status_code == 200 and p.is_html]
        if not observed:
            return

        # 只有当**所有**观察到的页面都缺才算站点级问题。部分页面有、
        # 部分没有 → 说明作者只在部分模板里写了，那是另一回事，
        # 按页报出来更准确，不该在这里被抹平。
        full = [
            p
            for p in observed
            if not (p.og_title and p.og_description and p.og_image)
        ]
        if len(full) < len(observed):
            return

        # 全部页面都缺 → 缺的就是这三项（任一页有就不算站点级问题）
        missing = [
            tag
            for attr, tag in (
                ("og_title", "og:title"),
                ("og_description", "og:description"),
                ("og_image", "og:image"),
            )
            if not getattr(observed[0], attr)
        ]
        yield self._issue(
            page,
            {
                "missing": missing,
                "pages_checked": len(observed),
                "pages_missing": len(full),
                "note": "og 标签只影响社交分享卡片，不影响搜索排名",
                "verdict": "affects_sharing_only",
            },
        )


@reg.register
class SocialImageInvalid(Rule):
    """og:image 指向了站内不存在的图片。"""

    code = "og.image_broken"
    severity = Severity.MEDIUM
    market = Market.GOOGLE
    title = "og:image 指向的图片不可用"
    description = (
        "分享卡片指定的封面图打不开时，各平台会显示空白或占位图，"
        "看起来像站点坏了。这是少数「看起来像故障、实际不影响排名」的问题。"
    )
    fix_hint = "确认 og:image 指向的图片真实可访问，且尺寸建议 ≥1200×630。"

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        if not page.og_image:
            return
        facts = ctx.site_facts or {}
        checked = facts.get("og_image_status") or {}
        status = checked.get(normalize_url(page.og_image))
        if status is None:
            return  # 没做回访就不猜——「没检查过」不等于「有问题」
        if status >= 400:
            yield self._issue(
                page,
                {
                    "og_image": page.og_image,
                    "status": status,
                    "verdict": "likely_bug",
                    "verdict_explain": "封面图回访失败，分享卡片会显示空白",
                },
            )
