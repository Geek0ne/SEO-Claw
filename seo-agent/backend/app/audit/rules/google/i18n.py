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
from urllib.parse import urlparse

from ....models import Issue, Market, Page, Scope, Severity
from ....util import normalize_url
from ...engine import Rule, RuleContext, default_registry

reg = default_registry()


def _is_cjk_url(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in text)


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

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        if page.status_code != 200 or not page.hreflang:
            return

        own_url = normalize_url(page.final_url or page.url)
        own_lang = (page.lang or "").split("-")[0].strip().lower()
        if not own_lang:
            return  # 没有 lang 就无从判断自引用该写什么，交给 lang.missing 报

        has_self = False
        for code, href in page.hreflang:
            same_lang = code.split("-")[0].strip().lower() == own_lang
            if normalize_url(href) == own_url and (same_lang or code.lower() == "x-default"):
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
        if page.status_code != 200:
            return
        missing = []
        if not page.og_title:
            missing.append("og:title")
        if not page.og_description:
            missing.append("og:description")
        if not page.og_image:
            missing.append("og:image")
        if not missing:
            return
        yield self._issue(
            page,
            {
                "missing": missing,
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
