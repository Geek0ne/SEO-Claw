"""基础检查项包：所有市场通用。"""

from __future__ import annotations

from typing import Iterable

from ....models import Issue, Market, Page, Scope, Severity
from ....util import normalize_url
from ...engine import Rule, RuleContext, default_registry

reg = default_registry()


@reg.register
class TitleMissing(Rule):
    code = "title.missing"
    severity = Severity.CRITICAL
    title = "页面缺少 title 标签"
    description = "title 是搜索结果里最重要的可点击文案。缺失时搜索引擎会自行从页面内容里截取，排名与点击率都会受损。"
    fix_hint = "在 <head> 里加一个 <title>，写成「核心关键词 - 品牌名」的结构。"
    fix_example = "<head>\n  <title>防水登山鞋 男款防滑 - 品牌名</title>\n</head>"

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        if page.status_code == 200 and not page.title:
            yield self._issue(page, {"html_title_found": False})


@reg.register
class TitleTooLong(Rule):
    code = "title.too_long"
    severity = Severity.MEDIUM
    title = "title 过长会被截断"
    description = "title 超出显示长度时会被搜索结果截断，关键信息放不进去就白写了。中文建议 ≤30 字，英文建议 ≤60 字符。"
    fix_hint = "把最重要的关键词前置，删掉形容词和冗余修饰。"

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        limit = 30 if _is_cjk(page.title or "") else 60
        if limit == 30 and len(page.title or "") > 30:
            yield self._issue(
                page,
                {"title": page.title, "length": page.title_length, "limit": limit},
            )
        elif limit == 60 and page.title_length > 60:
            yield self._issue(
                page,
                {"title": page.title, "length": page.title_length, "limit": limit},
            )


@reg.register
class TitleTooShort(Rule):
    code = "title.too_short"
    severity = Severity.LOW
    title = "title 过短，浪费了黄金位置"
    description = "过短的 title 通常意味着没覆盖到用户搜索的关键词，浪费了搜索结果里最显眼的位置。"
    fix_hint = "补充用户真实会用到的搜索词，保持自然可读。"

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        if page.title and 0 < page.title_length < 15:
            yield self._issue(
                page, {"title": page.title, "length": page.title_length, "min": 15}
            )


@reg.register
class TitleDuplicate(Rule):
    code = "title.duplicate"
    severity = Severity.HIGH
    scope = Scope.SITE
    title = "多个页面 title 完全相同"
    description = "重复的 title 会让搜索引擎无法区分这些页面，权重被分散，还可能触发重复内容判断。"
    fix_hint = "为每个页面写能体现其独特价值的 title，用页面主题词区分。"

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        # 不需要覆盖率门槛：重复 title 是「正面证据」——看到两个页面
        # title 相同就能确认，与抓没抓完无关。
        # （孤岛页那类靠「没看到」下结论的规则才需要完整性门槛）
        for title, urls in ctx.title_index.items():
            if len(urls) < 2:
                continue
            yield self._site_issue(
                ctx,
                {
                    "title": title,
                    "url_count": len(urls),
                    "duplicate_ratio": round(len(urls) / max(len(ctx.all_pages), 1), 3),
                    "sample_urls": urls[:10],
                },
            )


@reg.register
class MetaDescriptionMissing(Rule):
    code = "meta.missing"
    severity = Severity.HIGH
    title = "页面缺少 meta description"
    description = "description 不直接影响排名，但它是搜索结果里的广告文案。缺失时搜索引擎自动截取正文，通常读起来不连贯，会明显降低点击率。"
    fix_hint = "补一段 70~160 字符的描述，包含核心关键词和一个明确的行动理由。"
    fix_example = '<meta name="description" content="专业防水登山鞋，防滑耐磨，7天无理由退换。限时立减 200 元。">'

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        if page.status_code == 200 and not page.meta_description:
            yield self._issue(page, {"meta_description_found": False})


@reg.register
class MetaDescriptionDuplicate(Rule):
    code = "meta.duplicate"
    severity = Severity.MEDIUM
    scope = Scope.SITE
    title = "多个页面 meta description 相同"
    description = "相同的 description 让这些页面在搜索结果里长得一样，用户没有理由点开第二个。"
    fix_hint = "每页 description 描述该页面独有的内容与卖点。"

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        for desc, urls in ctx.meta_index.items():
            if len(urls) < 2:
                continue
            yield self._site_issue(
                ctx,
                {
                    "meta_description": desc[:200],
                    "url_count": len(urls),
                    "sample_urls": urls[:10],
                },
            )


@reg.register
class H1Missing(Rule):
    code = "h1.missing"
    severity = Severity.HIGH
    title = "页面没有 H1 标题"
    description = "H1 是页面主题的最强信号。没有 H1 时，搜索引擎只能靠正文猜测这页在讲什么。"
    fix_hint = "加一个 H1 写清页面主标题，位置放在正文开头。"

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        if page.status_code == 200 and not page.h1:
            yield self._issue(page, {"h1_count": 0})


@reg.register
class H1Multiple(Rule):
    code = "h1.multiple"
    severity = Severity.MEDIUM
    title = "页面有多个 H1"
    description = "多个 H1 会让主题信号分散。HTML5 允许多个 H1，但实践中一个主 H1 对 SEO 更稳妥。"
    fix_hint = "保留一个主 H1，其余同级标题降为 H2。"

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        if len(page.h1) > 1:
            yield self._issue(page, {"h1_count": len(page.h1), "h1_list": page.h1[:5]})


@reg.register
class CanonicalMissing(Rule):
    code = "canonical.missing"
    severity = Severity.MEDIUM
    title = "页面缺少 canonical 标签"
    description = "URL 带参数（?utm_source、分页、筛选条件）时，搜索引擎会把它们当成不同页面，权重被分散。canonical 明确指定权威版本。"
    fix_hint = '在 <head> 里加 <link rel="canonical" href="本页的规范地址">。'
    fix_example = '<link rel="canonical" href="https://example.com/product/123">'

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        # 首页通常不需要 canonical，跳过以减少噪音
        if page.url.rstrip("/") in (f"https://{ctx.domain}", f"http://{ctx.domain}"):
            return
        if page.status_code == 200 and not page.canonical:
            yield self._issue(page, {"canonical_found": False})


@reg.register
class CanonicalConflict(Rule):
    code = "canonical.conflict"
    severity = Severity.MEDIUM
    title = "canonical 指向了其他页面（需确认是否有意为之）"
    description = (
        "canonical 与当前页面不一致时，搜索引擎会把本页权重转移给目标页。"
        "这可能是有意为之（内容已合并、历史版本别名、分页主页面），"
        "也可能是模板复制时漏改。⚠️ 工具无法自动区分这两种情况，"
        "请逐条确认：目标页存在且内容相近 → 通常没问题；目标页 404 → 确定是 bug。"
    )
    fix_hint = "逐条打开 canonical 目标页确认：如果是有意合并，保持现状即可；如果是模板漏改，改成指向本页自身。"

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        if not page.canonical or page.status_code != 200:
            return
        # 比较时忽略协议、www、末尾斜杠与 index.html 等价形式
        if normalize_url(page.canonical) == normalize_url(page.final_url or page.url):
            return

        # 回访 canonical 目标，用结果区分「真 bug」与「有意合并」
        target_status = (ctx.site_facts or {}).get("canonical_target_status", {}).get(
            normalize_url(page.canonical)
        )

        evidence: dict[str, object] = {
            "canonical": page.canonical,
            "page_url": page.final_url or page.url,
            "canonical_target_status": target_status,
        }

        if target_status in (404, 410, None) and target_status is not None:
            # 目标页不存在 → 确定是 bug
            evidence["verdict"] = "likely_bug"
            yield self._issue(page, evidence, severity=Severity.CRITICAL)
        elif target_status and target_status >= 400:
            evidence["verdict"] = "likely_bug"
            yield self._issue(page, evidence, severity=Severity.HIGH)
        else:
            # 目标页正常存在 → 多半是有意为之，只作提醒
            evidence["verdict"] = "possibly_intentional"
            yield self._issue(page, evidence)


@reg.register
class NoindexPresent(Rule):
    code = "noindex.present"
    severity = Severity.CRITICAL
    title = "页面被 noindex 屏蔽收录"
    description = "noindex 会让页面完全不出现在搜索结果里。这通常是开发环境忘记删，或者模板改版时误加。"
    fix_hint = "如果页面应该被收录，删掉 noindex；如果是故意屏蔽（如分页页），请在 sitemap 中也排除它。"

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        robots = (page.robots_meta or "").lower()
        tokens = set(robots.replace(",", " ").split())
        if tokens & {"noindex", "none"}:
            yield self._issue(page, {"robots_meta": page.robots_meta})


@reg.register
class ImageAltMissing(Rule):
    code = "img.alt.missing"
    severity = Severity.MEDIUM
    title = "图片缺少 alt 文本"
    description = "alt 决定了图片在图片搜索和屏幕阅读器里的表现。缺失等于放弃了这部分流量，也影响可访问性合规。"
    fix_hint = '补上描述性 alt，格式建议「图片内容 + 上下文」。装饰性图片用 alt=""。'
    fix_example = '<img src="shoe.jpg" alt="黑色防水登山鞋 侧视图">'

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        missing = [img.src for img in page.images if img.alt is None]
        if missing:
            yield self._issue(
                page,
                {
                    "missing_count": len(missing),
                    "total_images": len(page.images),
                    "sample_srcs": missing[:5],
                },
            )


@reg.register
class ImageAltGeneric(Rule):
    code = "img.alt.generic"
    severity = Severity.LOW
    title = "图片 alt 是无意义占位文本"
    description = 'alt 写成 "image"、"图片"、"1.jpg" 这类等于没写，图片搜索拿不到任何语义信息。'
    fix_hint = "改成描述图片实际内容的文字。"

    _GENERIC = {
        "image", "img", "picture", "photo", "图片", "图像", "照片",
        "1", "2", "3", "图片1", "图片2", "untitled", "placeholder", "icon",
    }

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        generic = [
            img.src
            for img in page.images
            if img.alt and img.alt.strip().lower() in self._GENERIC
        ]
        if generic:
            yield self._issue(page, {"generic_count": len(generic), "sample_srcs": generic[:5]})


@reg.register
class LinkNoAnchor(Rule):
    code = "link.noanchor"
    severity = Severity.MEDIUM
    title = "内部链接锚文本为空"
    description = "空锚文本（如 `<a href=\"/x\"></a>`）对用户和搜索引擎都没有传递任何信息，也会带来可访问性问题。"
    fix_hint = "给链接加上描述性锚文本。"

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        empties = [l.href for l in page.links if l.kind.value == "internal" and not l.anchor]
        # 只报「本页有多个空锚」的情况：单个往往是无害的 UI 元素
        if len(empties) >= 2:
            yield self._issue(
                page, {"empty_anchor_count": len(empties), "sample_hrefs": empties[:5]}
            )


@reg.register
class DepthExcessive(Rule):
    code = "depth.excessive"
    severity = Severity.MEDIUM
    title = "页面点击层级过深"
    description = "超过 4 层的页面很难被抓取和被用户点到，权重传递也会被削弱。"
    fix_hint = "在导航或页脚增加直达链接，把重要页面压到 3 层以内。"

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        if page.depth > 4:
            yield self._issue(
                page, {"depth": page.depth, "url": page.url}, title=self.title
            )


@reg.register
class OrphanPage(Rule):
    code = "orphan.page"
    severity = Severity.HIGH
    scope = Scope.SITE
    title = "孤岛页面：没有任何内链指向"
    description = "既不在导航里、也没有其他页面链向它，只能靠 sitemap 被发现。这类页面很难获得权重，也几乎不可能有流量。"
    fix_hint = "在相关内容的文章或列表页中加入指向它的内链。"

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        # ★ 数据充分性门槛：只抓到一小部分页面时，“没有入链”可能只是没被抓到。
        # 覆盖率不够时保持沉默——大面积误报会直接毁掉工具的可信度。
        if not ctx.has_enough_data():
            return
        # 只看可索引的 HTML 页面，PDF/图片等不参与孤岛判断
        candidates = [
            p for p in ctx.all_pages if p.status_code == 200 and p.is_html and not p.error
        ]
        orphans = []
        for p in candidates:
            inbound = ctx.inbound_links.get(p.url, 0) + ctx.inbound_links.get(
                p.final_url or p.url, 0
            )
            if inbound == 0:
                orphans.append(p.url)
        if orphans:
            yield self._site_issue(
                ctx,
                {
                    "orphan_count": len(orphans),
                    "scanned_pages": len(candidates),
                    "total_discovered": ctx.discovered,
                    "coverage": round(ctx.coverage, 3),
                    "sample_urls": orphans[:20],
                },
            )


@reg.register
class MixedContent(Rule):
    code = "http.mixed_content"
    severity = Severity.HIGH
    title = "HTTPS 页面存在混合内容"
    description = "HTTPS 页面里加载 http:// 资源时，浏览器会拦截或降级，Chrome 会直接标记页面为「不安全」，影响排名与用户信任。"
    fix_hint = "把所有 http:// 资源改成 https://，或用协议相对路径。"
    fix_example = '把 <img src="http://cdn.x.com/a.jpg"> 改为 <img src="https://cdn.x.com/a.jpg">'

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        if page.has_mixed_content:
            yield self._issue(
                page,
                {
                    "page_url": page.final_url or page.url,
                    "offending_resources": page.mixed_content_samples,
                    "note": "只统计 img/script/link/iframe 等子资源，不含 <a href> 超链接",
                },
            )


@reg.register
class SchemaMissing(Rule):
    code = "schema.missing"
    severity = Severity.LOW
    title = "页面没有结构化数据"
    description = "结构化数据让搜索引擎理解页面实体（商品、文章、FAQ），是拿到富媒体搜索结果的前提。"
    fix_hint = "按页面类型添加对应的 JSON-LD：商品页用 Product，文章页用 Article。"
    fix_example = (
        '<script type="application/ld+json">\n'
        '{"@context":"https://schema.org","@type":"Product",'
        '"name":"防水登山鞋","offers":{"@type":"Offer","price":"299"}}\n'
        "</script>"
    )

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        if page.status_code == 200 and not page.jsonld and not page.microdata_types:
            yield self._issue(page, {"jsonld_count": 0, "microdata_count": 0})


@reg.register
class Soft404(Rule):
    code = "soft404"
    severity = Severity.MEDIUM
    title = "疑似软 404（需确认）"
    description = (
        "页面返回 200 但正文极少，搜索引擎会识别为软 404 并停止索引。"
        "⚠️ 但索引页、目录页、标签页天生内容少，不一定是问题——"
        "工具会提供判定信号，请确认：这个页面是“该有内容却没有”，还是“本身就是列表页”。"
    )
    fix_hint = "如果确实是空页面：返回真正的 404 状态码，或补上内容。如果是索引/列表页：忽略本条即可。"

    # 这些 URL 形态本身就代表目录/索引页
    _INDEX_HINTS = (
        "index", "genindex", "py-modindex", "category", "/tag/", "/list",
        "archives", "sitemap", "?page=", "/page/",
    )

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        if page.status_code != 200 or not page.content_is_thin:
            return

        path = (page.url or "").lower()
        # 入链数在 ctx 上（build_context 算的），不是 site_facts
        inbound = ctx.inbound_links.get(page.url, 0) + ctx.inbound_links.get(
            page.final_url or page.url, 0
        )

        # ── 区分「真软 404」与「正常的短索引页」 ──
        # 判据：目录/索引页会挂大量出链（供用户跳转），且往往被很多页面链接；
        #       而真正的空页面既无出链也几乎无入链。
        outbound = page.internal_link_count
        looks_like_index = any(h in path for h in self._INDEX_HINTS)

        if looks_like_index or outbound >= 10:
            verdict = "likely_index_or_hub"
            severity = Severity.INFO
        elif inbound == 0 and outbound <= 3:
            verdict = "likely_true_soft404"
            severity = Severity.HIGH
        else:
            verdict = "uncertain"
            severity = Severity.MEDIUM

        yield self._issue(
            page,
            {
                "word_count": page.word_count,
                "text_preview": page.text[:120],
                "status_code": page.status_code,
                "internal_outbound_links": outbound,
                "inbound_links": inbound,
                "url_looks_like_index": looks_like_index,
                "verdict": verdict,
                "verdict_explain": {
                    "likely_index_or_hub": "出链多、URL 形似索引页，大概率是正常的目录/列表页",
                    "likely_true_soft404": "既无出链也几乎无入链且内容极少，大概率是空页面",
                    "uncertain": "信号不明确，请人工看一眼",
                }[verdict],
            },
            severity=severity,
        )


@reg.register
class SitemapMissing(Rule):
    code = "sitemap.missing"
    severity = Severity.HIGH
    scope = Scope.SITE
    title = "站点没有可用的 sitemap"
    description = "没有 sitemap 时，搜索引擎只能靠内链发现页面，新页面和深埋页面的收录速度会明显变慢，抓取预算也用得更浪费。"
    fix_hint = "生成 XML sitemap，在 robots.txt 里声明它，并提交到 Google Search Console 和百度搜索资源平台。"
    fix_example = (
        "User-agent: *\n"
        "Allow: /\n"
        "Sitemap: https://example.com/sitemap.xml"
    )

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        facts = ctx.site_facts or {}
        if "sitemap_found" not in facts:
            return  # 爬虫没探测 sitemap（如手工喂的页面），不误报
        if not facts["sitemap_found"]:
            yield self._site_issue(
                ctx,
                {
                    "tried_paths": facts.get("sitemap_tried", []),
                    "error": facts.get("sitemap_error"),
                },
            )


@reg.register
class RobotsMissing(Rule):
    code = "robots.missing"
    severity = Severity.MEDIUM
    scope = Scope.SITE
    title = "缺少 robots.txt"
    description = "robots.txt 不是必需的，但它的存在能控制抓取范围、声明 sitemap，并避免爬虫浪费预算在后台等无价值路径上。"
    fix_hint = "放一个 robots.txt 到根目录，并声明 sitemap 地址。"
    fix_example = "User-agent: *\nAllow: /\nSitemap: https://example.com/sitemap.xml"

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        facts = ctx.site_facts or {}
        status = facts.get("robots_status")
        if status is None:
            return
        if status == 404:
            yield self._site_issue(ctx, {"robots_url": facts.get("robots_url"), "status": 404})


@reg.register
class RobotsBlocksBots(Rule):
    code = "robots.blocks_own_site"
    severity = Severity.CRITICAL
    scope = Scope.SITE
    title = "robots.txt 屏蔽了搜索引擎收录全站"
    description = "这是最严重也最容易犯的错：Disallow: / 会让整站从搜索结果中消失。如果本意是不让某个目录被索引，应该只屏蔽那个目录，而不是全站。"
    fix_hint = "改成 Allow: / 并针对特定目录 Disallow，确认规则上线前先在 Google Search Console 的 robots 测试工具里验证。"
    fix_example = "User-agent: *\nAllow: /\nDisallow: /admin/\nDisallow: /search?"

    def check(self, page: Page, ctx: RuleContext) -> Iterable[Issue]:
        facts = ctx.site_facts or {}
        directives = facts.get("robots_directives") or []
        for ua, rules in directives:
            if ua not in ("*", "googlebot", "baiduspider", "bingbot"):
                continue
            for raw in rules:
                rule = raw.split("#")[0].strip()
                if not rule:
                    continue
                parts = rule.split(":", 1)
                if len(parts) != 2:
                    continue
                directive, value = parts[0].strip().lower(), parts[1].strip()
                if directive == "disallow" and value == "/":
                    yield self._site_issue(
                        ctx,
                        {"user_agent": ua, "directive": f"Disallow: {value}",
                         "robots_url": facts.get("robots_url")},
                    )


# --------------------------------------------------------------------------
# 工具函数
# --------------------------------------------------------------------------


def _is_cjk(text: str) -> bool:
    """判断是否包含中日韩字符——用于切换中英文长度阈值。"""
    return any("一" <= ch <= "鿿" for ch in text)
