"""
黄金样本回归测试。

为什么这是「真做产品」和「写个能跑的脚本」的分水岭：
规则和评分逻辑每改一次，都可能让之前能检出的问题检不出来（回归）。
没有回归测试的 SEO 工具，规则会慢慢烂掉——因为误报比漏报更难发现。

本文件是**合成样本**：用构造的 HTML 覆盖每条规则的触发/不触发路径。
优点是完全确定、无网络依赖、跑得快；缺点是覆盖不到真实站点的脏 HTML。
真实站点快照见 tests/golden_real/（M1 补充，体积大不入库）。

用法：
    PYTHONPATH=.deps python3 -m pytest backend/tests/ -q
"""

from __future__ import annotations

import pytest

from app.audit.engine import run_audit
from app.extract import extract_page
from app.models import Market, Severity


# --------------------------------------------------------------------------
# 合成 HTML 构造器
# --------------------------------------------------------------------------


def html(
    *,
    title: str | None = "示例页面 - 演示站",
    description: str | None = "这是一个用于测试的页面描述，包含足够长度的文本内容。",
    h1: str | list[str] | None = "示例页面",
    canonical: str | None = None,
    robots: str | None = None,
    body: str = "<p>内容</p>",
    images: list[tuple[str, str | None]] | None = None,
    links: list[tuple[str, str]] | None = None,
    jsonld: str | None = None,
    lang: str = "zh-CN",
) -> str:
    """拼一段可控的 HTML，用于精确触发/规避特定规则。"""
    parts = ["<!DOCTYPE html>", '<html lang="{}">'.format(lang), "<head>"]
    parts.append('<meta charset="utf-8">')
    if title is not None:
        parts.append(f"<title>{title}</title>")
    if description is not None:
        parts.append(f'<meta name="description" content="{description}">')
    if robots:
        parts.append(f'<meta name="robots" content="{robots}">')
    if canonical:
        parts.append(f'<link rel="canonical" href="{canonical}">')
    if jsonld:
        parts.append(f'<script type="application/ld+json">{jsonld}</script>')
    parts.append("</head>")

    if h1 is None:
        pass
    elif isinstance(h1, list):
        parts.extend(f"<h1>{h}</h1>" for h in h1)
    else:
        parts.append(f"<h1>{h1}</h1>")

    parts.append(body)
    for src, alt in images or []:
        alt_attr = "" if alt is None else f'alt="{alt}"'
        parts.append(f'<img src="{src}"{alt_attr}>')
    for href, anchor in links or []:
        parts.append(f'<a href="{href}">{anchor}</a>')
    parts.append("</html>")
    return "\n".join(parts)


def audit_one(source: str, url: str = "https://demo.test/page", market=None):
    """跑一次完整审计，返回 code -> 最高 severity 的字典。"""
    pages = [extract_page(url, source)]
    issues, _ = run_audit(pages, "demo.test", market or [Market.BASE])
    out: dict[str, Severity] = {}
    for issue in issues:
        prev = out.get(issue.code)
        if prev is None or issue.severity.rank < prev.rank:
            out[issue.code] = issue.severity
    return out, issues


# --------------------------------------------------------------------------
# 逐条规则：应当触发
# --------------------------------------------------------------------------


def test_title_missing_fires():
    codes, _ = audit_one(html(title=None))
    assert "title.missing" in codes
    assert codes["title.missing"] is Severity.CRITICAL


def test_noindex_fires():
    codes, _ = audit_one(html(robots="noindex, nofollow"))
    assert "noindex.present" in codes


def test_h1_missing_fires():
    codes, _ = audit_one(html(h1=None))
    assert "h1.missing" in codes


def test_h1_multiple_fires():
    codes, _ = audit_one(html(h1=["第一个", "第二个"]))
    assert "h1.multiple" in codes


def test_meta_missing_fires():
    codes, _ = audit_one(html(description=None))
    assert "meta.missing" in codes


def test_canonical_missing_fires():
    codes, _ = audit_one(html(canonical=None))
    assert "canonical.missing" in codes


def test_canonical_missing_skips_homepage():
    """首页不该报 canonical 缺失——否则每个站都有一条无意义告警。"""
    codes, _ = audit_one(html(canonical=None), url="https://demo.test/")
    assert "canonical.missing" not in codes


def test_canonical_conflict_when_points_elsewhere():
    codes, _ = audit_one(html(canonical="https://demo.test/other"))
    assert "canonical.conflict" in codes


def test_canonical_self_reference_is_not_conflict():
    """canonical 指向自己不算问题，且要忽略 index.html / 末尾斜杠差异。"""
    for canon in (
        "https://demo.test/page",
        "https://demo.test/page/",
        "https://www.demo.test/page",
        "https://demo.test/page/index.html",
    ):
        codes, _ = audit_one(html(canonical=canon))
        assert "canonical.conflict" not in codes, f"canonical={canon} 误报"


def test_canonical_conflict_downgraded_when_target_exists():
    """目标页 200 → 只作提醒，不再报 HIGH。"""
    page = extract_page(
        "https://demo.test/2.7/", html(canonical="https://demo.test/2/index.html")
    )
    issues, _ = run_audit(
        [page],
        "demo.test",
        [Market.BASE],
        site_facts={"canonical_target_status": {"demo.test/2/index.html": 200}},
    )
    conflict = next(i for i in issues if i.code == "canonical.conflict")
    assert conflict.severity is Severity.MEDIUM
    assert conflict.evidence["verdict"] == "possibly_intentional"


def test_canonical_conflict_escalates_when_target_404():
    """目标页 404 → 确定是 bug，升到 CRITICAL。"""
    page = extract_page(
        "https://demo.test/old", html(canonical="https://demo.test/gone")
    )
    issues, _ = run_audit(
        [page],
        "demo.test",
        [Market.BASE],
        site_facts={"canonical_target_status": {"demo.test/gone": 404}},
    )
    conflict = next(i for i in issues if i.code == "canonical.conflict")
    assert conflict.severity is Severity.CRITICAL
    assert conflict.evidence["verdict"] == "likely_bug"


def test_img_alt_missing_and_generic():
    codes, _ = audit_one(
        html(images=[("/a.jpg", None), ("/b.jpg", "image"), ("/c.jpg", "红色登山鞋特写")])
    )
    assert "img.alt.missing" in codes
    assert "img.alt.generic" in codes


def test_img_alt_empty_string_is_not_missing():
    """alt="" 是装饰性图片的正确写法，不该报缺失。"""
    codes, _ = audit_one(html(images=[("/a.jpg", "")]))
    assert "img.alt.missing" not in codes


def test_mixed_content_detected_on_subresource():
    """img/script 子资源走 http:// 才是真的混合内容。"""
    page = extract_page(
        "https://demo.test/",
        html(body='<img src="http://cdn.demo.test/a.jpg">'),
        final_url="https://demo.test/",
    )
    assert page.has_mixed_content is True
    assert any("a.jpg" in s for s in page.mixed_content_samples)


def test_anchor_link_is_not_mixed_content():
    """<a href="http://..."> 是用户主动点击的链接，浏览器不会拦截，不算混合内容。
    曾踩坑：正则匹配全页的 src|href，把超链接也当混合内容，
    在 rust-lang.org 上造成 8 条纯误报。"""
    page = extract_page(
        "https://demo.test/",
        html(body='<a href="http://external.test/forge">Forge</a>'),
        final_url="https://demo.test/",
    )
    assert page.has_mixed_content is False
    issues, _ = run_audit([page], "demo.test", [Market.BASE])
    assert not [i for i in issues if i.code == "http.mixed_content"]


def test_http_page_is_never_mixed_content():
    """HTTP 页面不存在混合内容问题（自身都不加密）。"""
    page = extract_page(
        "http://demo.test/", html(body='<img src="http://cdn.test/a.jpg">')
    )
    assert page.has_mixed_content is False


def test_mixed_content_evidence_names_the_resource():
    """必须指出到底是哪个资源，否则用户无从下手。"""
    page = extract_page(
        "https://demo.test/",
        html(body='<img src="http://cdn.demo.test/logo.png">'),
        final_url="https://demo.test/",
    )
    issues, _ = run_audit([page], "demo.test", [Market.BASE])
    mixed = next(i for i in issues if i.code == "http.mixed_content")
    assert any("logo.png" in s for s in mixed.evidence["offending_resources"])


def test_mixed_content_on_stylesheet_link():
    """rel=stylesheet 会被浏览器加载，算混合内容。"""
    page = extract_page(
        "https://demo.test/",
        html(body='<link rel="stylesheet" href="http://cdn.demo.test/a.css">'),
        final_url="https://demo.test/",
    )
    assert page.has_mixed_content is True


def test_mixed_content_ignores_declarative_link_rels():
    """rel=alternate/canonical/me 等只是声明关系，浏览器不加载资源，不是混合内容。
    这是本规则的最后一类残留误报来源。"""
    for rel in ("alternate", "canonical", "me", "license", "author", "search", "next", "prev"):
        page = extract_page(
            "https://demo.test/",
            html(body=f'<link rel="{rel}" href="http://other.test/x">'),
            final_url="https://demo.test/",
        )
        assert page.has_mixed_content is False, f"rel={rel} 被误判为混合内容"


def test_mixed_content_catches_https_hreflang_variant():
    """hreflang 常写成 rel="alternate" hreflang=... + http:// 绝对地址，
    这种也不能算混合内容。"""
    page = extract_page(
        "https://demo.test/",
        html(body='<link rel="alternate" hreflang="zh" href="http://demo.test/zh">'),
        final_url="https://demo.test/",
    )
    assert page.has_mixed_content is False


def test_mixed_content_still_catches_preload():
    """白名单要覆盖 preload/prefetch 这类预加载——它们确实会发起请求。"""
    page = extract_page(
        "https://demo.test/",
        html(body='<link rel="preload" href="http://cdn.demo.test/f.woff2" as="font">'),
        final_url="https://demo.test/",
    )
    assert page.has_mixed_content is True


def test_mixed_content_ignores_relative_and_protocol_relative():
    """相对路径与协议相对路径都不算混合内容。"""
    page = extract_page(
        "https://demo.test/",
        html(body='<img src="/a.jpg"><img src="//cdn.demo.test/b.jpg">'),
        final_url="https://demo.test/",
    )
    assert page.has_mixed_content is False


def test_soft404_fires_on_thin_page():
    pass


# --------------------------------------------------------------------------
# 站名/品牌名不应被判为 title 过短
# --------------------------------------------------------------------------
# 实测 jvns.ca 的 title 就是「Julia Evans」（11 字符）。技术上短了，
# 但站名本身就是完整品牌，报「过短」等于让用户去硬堆关键词，
# 那样反而降低点击率。规则必须看语境，不能只看长度。
_NAME_TITLES = [
    "Julia Evans",   # 站点主人姓名
    "Anthony Fu",
    "Vue",           # 单一品牌词
    "Learn Vue",     # 首字母大写、无功能词的短语
]


@pytest.mark.parametrize("title", _NAME_TITLES)
def test_short_but_looks_like_name_is_not_reported(title):
    codes, _ = audit_one(html(title=title, body="<p>" + "内容" * 200 + "</p>"))
    assert "title.too_short" not in codes, f"{title!r} 被误判为 title 过短"


@pytest.mark.parametrize(
    "title",
    ["Best SEO Tips", "SEO 优化指南", "Vue 快速上手"],
)
def test_genuinely_thin_titles_still_reported(title):
    """别把规则改废：真正缺关键词的短标题仍要报。

    ⚠️ 样本必须 <15 字符，否则根本进不了规则判定，会变成「假绿」。
    """
    assert len(title) < 15, "样本必须短于阈值，否则测不到规则"
    codes, _ = audit_one(html(title=title, body="<p>" + "内容" * 200 + "</p>"))
    assert "title.too_short" in codes, f"{title!r} 应被报出但没有"


def test_h1_multiple_downgraded_to_info():
    """Google 不惩罚多个 H1。降级后必须明确告知「别为此改版面」，
    否则用户会为了消一条 INFO 去动正常的模板。"""
    _, issues = audit_one(
        html(title="示例页面 - 演示站", body="<h1>站名</h1><h1>文章标题</h1><p>x</p>")
    )
    hit = next(i for i in issues if i.code == "h1.multiple")
    assert hit.severity is Severity.INFO
    assert hit.evidence["verdict"] == "likely_intentional"
    assert hit.evidence["duplicated"] is False


def test_h1_multiple_flags_verbatim_duplicates():
    """内容完全相同的 H1 多半是模板重复渲染，这才值得看一眼。"""
    _, issues = audit_one(
        html(title="示例页面 - 演示站", body="<h1>同一个标题</h1><h1>同一个标题</h1><p>x</p>")
    )
    hit = next(i for i in issues if i.code == "h1.multiple")
    assert hit.evidence["duplicated"] is True
    assert hit.evidence["verdict"] == "review_worthwhile"


def test_h1_single_not_reported():
    # 注意：html() 默认会插一个 h1，body 里再放一个就成了两个——这是测试自身的坑
    codes, _ = audit_one(
        html(title="示例页面 - 演示站", h1="唯一标题", body="<p>x</p>")
    )
    assert "h1.multiple" not in codes
    codes, _ = audit_one(html(body="<p>404</p>"))
    assert "soft404" in codes


def test_soft404_true_positive_is_high():
    """真·空页面（无出链、无入链）应报 HIGH。"""
    page = extract_page("https://demo.test/empty", html(body="<p>404</p>"))
    issues, _ = run_audit([page], "demo.test", [Market.BASE])
    soft = next(i for i in issues if i.code == "soft404")
    assert soft.evidence["verdict"] == "likely_true_soft404"
    assert soft.severity is Severity.HIGH


def test_soft404_index_page_downgraded_to_info():
    """索引页/目录页天生内容少——不能报 HIGH。这是实测踩过的误报：
    docs.python.org 的 genindex.html（28 字）和 using/index.html（210 字）
    都是正常索引页。"""
    # URL 形态像索引页
    page = extract_page(
        "https://demo.test/genindex.html", html(body="<p>Index</p>")
    )
    issues, _ = run_audit([page], "demo.test", [Market.BASE])
    soft = next(i for i in issues if i.code == "soft404")
    assert soft.evidence["verdict"] == "likely_index_or_hub"
    assert soft.severity is Severity.INFO


def test_soft404_downgraded_when_many_outbound_links():
    """出链很多 → 是目录/枢纽页，不是空页面。"""
    links = [(f"https://demo.test/p{i}", f"页面{i}") for i in range(15)]
    page = extract_page(
        "https://demo.test/listing", html(body="<p>列表</p>", links=links)
    )
    issues, _ = run_audit([page], "demo.test", [Market.BASE])
    soft = next(i for i in issues if i.code == "soft404")
    assert soft.evidence["internal_outbound_links"] >= 10
    assert soft.evidence["verdict"] == "likely_index_or_hub"
    assert soft.severity is Severity.INFO


# --------------------------------------------------------------------------
# 链接提取：实测踩过的两个坑
# --------------------------------------------------------------------------


def test_anchor_text_falls_back_to_img_alt():
    """<a><img alt="Python logo"></a> 的锚文本在 img[alt] 里，
    只取 itertext() 会误报「锚文本为空」（实测在 docs.python.org 上
    造成 28 条假阳性）。"""
    page = extract_page(
        "https://demo.test/",
        html(body='<a href="/home"><img src="/logo.svg" alt="Python logo"></a>'),
    )
    assert page.links, "链接应被提取"
    assert page.links[0].anchor == "Python logo"


def test_anchor_text_falls_back_to_title_when_text_is_symbol():
    """可见文字是纯符号时，应回退到有语义的属性。"""
    page = extract_page(
        "https://demo.test/",
        html(body='<a href="/next" title="下一页">›</a>'),
    )
    assert page.links[0].anchor == "下一页"


def test_anchor_text_falls_back_to_aria_label():
    """aria-label 优先级高于纯符号可见文字。"""
    page = extract_page(
        "https://demo.test/",
        html(body='<a href="/next" aria-label="下一页">›</a>'),
    )
    assert page.links[0].anchor == "下一页"


def test_empty_href_is_not_a_link():
    """<a href=""></a> 指向当前页，不是真链接，不能当内链收。"""
    page = extract_page(
        "https://demo.test/", html(body='<a href=""> </a><a href="#top">↑</a>')
    )
    assert page.links == [], f"不应提取到链接，实际：{page.links}"


def test_link_noanchor_needs_at_least_two():
    """单个空锚往往是无害的 UI 元素，阈值定为 >=2。"""
    single = extract_page(
        "https://demo.test/a", html(body='<a href="/x"> </a>')
    )
    issues, _ = run_audit([single], "demo.test", [Market.BASE])
    assert not [i for i in issues if i.code == "link.noanchor"]

    many = extract_page(
        "https://demo.test/b",
        html(body='<a href="/x"> </a><a href="/y"> </a>'),
    )
    issues2, _ = run_audit([many], "demo.test", [Market.BASE])
    assert [i for i in issues2 if i.code == "link.noanchor"]


def test_schema_missing_fires():
    codes, _ = audit_one(html(jsonld=None))
    assert "schema.missing" in codes


def test_schema_present_no_issue():
    codes, _ = audit_one(
        html(jsonld='{"@context":"https://schema.org","@type":"Article","headline":"x"}')
    )
    assert "schema.missing" not in codes


def test_title_too_long_uses_cjk_limit():
    """中文站按 30 字判，英文站按 60 字符判——不能混用。"""
    zh_codes, _ = audit_one(html(title="标" * 35), url="https://demo.test/a")
    assert "title.too_long" in zh_codes

    en_codes, _ = audit_one(
        html(title="A" * 35, lang="en"), url="https://demo.test/b"
    )
    assert "title.too_long" not in en_codes

    en_codes2, _ = audit_one(
        html(title="A" * 70, lang="en"), url="https://demo.test/c"
    )
    assert "title.too_long" in en_codes2


# --------------------------------------------------------------------------
# 逐条规则：应当「不」触发（防误报）
# --------------------------------------------------------------------------


def test_perfect_page_has_zero_issues():
    """一个各项都合规的页面，不该产生任何问题。"""
    source = html(
        title="防水登山鞋 男款防滑耐磨 - 演示品牌",
        description="专业防水登山鞋，防滑耐磨，7 天无理由退换。限时优惠立减 200 元。",
        h1="防水登山鞋",
        canonical="https://demo.test/ok",
        images=[("/a.jpg", "黑色防水登山鞋侧视图")],
        jsonld='{"@context":"https://schema.org","@type":"Product","name":"防水登山鞋"}',
        body="<p>" + "登山鞋选购指南，覆盖防水等级、鞋底材质与适用场景。" * 40 + "</p>",
    )
    codes, issues = audit_one(source, url="https://demo.test/ok")
    unexpected = {c for c in codes if c not in ("soft404",)}
    assert not unexpected, f"完美页面不应有问题，实际报出：{unexpected}"


def test_no_false_positive_on_404_status():
    """返回 404 的页面不该报 title 缺失——它本来就不该被收录。"""
    page = extract_page("https://demo.test/gone", html(title=None), status_code=404)
    issues, _ = run_audit([page], "demo.test", [Market.BASE])
    assert [i for i in issues if i.code == "title.missing"] == []


def test_non_html_page_not_audited():
    page = extract_page(
        "https://demo.test/a.pdf", "", content_type="application/pdf"
    )
    assert page.is_html is False
    issues, _ = run_audit([page], "demo.test", [Market.BASE])
    assert issues == []


def test_malformed_html_does_not_crash():
    """脏 HTML 不能让整页解析崩溃。"""
    broken = "<html><head><title>坏页</title><body><div><p>未闭合"
    page = extract_page("https://demo.test/broken", broken)
    assert page.title == "坏页"


# --------------------------------------------------------------------------
# 站点级规则
# --------------------------------------------------------------------------


def test_title_duplicate_detected():
    a = extract_page("https://demo.test/1", html(title="相同标题"))
    b = extract_page("https://demo.test/2", html(title="相同标题"))
    issues, _ = run_audit([a, b], "demo.test", [Market.BASE])
    dup = [i for i in issues if i.code == "title.duplicate"]
    assert dup, "重复 title 未被检出"
    assert dup[0].evidence["url_count"] == 2


# --------------------------------------------------------------------------
# 数据充分性门槛：区分「证据缺失」与「正面证据」
# --------------------------------------------------------------------------


def test_orphan_stays_silent_when_coverage_too_low():
    """只抓到 2 页 / 发现 7000 页时，不能报孤岛页。

    这是真实踩过的误报：单页测试跑出来的报告里，那个唯一的页面
    被报成「没有任何内链指向的孤岛页」。抓不全时，「没发现入链」
    只说明没抓到。
    """
    pages = [
        extract_page("https://demo.test/a", html(title="A")),
        extract_page("https://demo.test/b", html(title="B")),
    ]
    issues, _ = run_audit(
        pages,
        "demo.test",
        [Market.BASE],
        site_facts={"discovered_count": 7000},
    )
    assert not [i for i in issues if i.code == "orphan.page"]


def test_orphan_fires_when_coverage_sufficient():
    """覆盖充分时，无入链页面才被报为孤岛页。"""
    pages = [
        extract_page(f"https://demo.test/p{i}", html(title=f"标题{i}"))
        for i in range(30)
    ]
    # 让 p0 互相链接，其余 29 个无入链
    pages[0].links = [
        type(pages[0].links[0])(href="https://demo.test/p0", anchor="a", kind="internal")
    ] if pages[0].links else []

    issues, _ = run_audit(
        pages,
        "demo.test",
        [Market.BASE],
        site_facts={"discovered_count": 30},
    )
    orphans = [i for i in issues if i.code == "orphan.page"]
    assert orphans, "覆盖充分时应能检出孤岛页"


def test_orphan_stays_silent_when_hit_page_limit():
    """撞到 max_pages 上限 = 没抓完，即使页面数够也不下结论。"""
    pages = [
        extract_page(f"https://demo.test/p{i}", html(title=f"标题{i}"))
        for i in range(40)
    ]
    issues, _ = run_audit(
        pages,
        "demo.test",
        [Market.BASE],
        site_facts={"discovered_count": 40, "hit_page_limit": True},
    )
    assert not [i for i in issues if i.code == "orphan.page"]


def test_title_duplicate_does_not_need_coverage():
    """正面证据类规则不受覆盖率影响——这是与孤岛页的关键区别。"""
    pages = [
        extract_page("https://demo.test/1", html(title="重复标题")),
        extract_page("https://demo.test/2", html(title="重复标题")),
    ]
    issues, _ = run_audit(
        pages, "demo.test", [Market.BASE], site_facts={"discovered_count": 9999}
    )
    assert [i for i in issues if i.code == "title.duplicate"]


def test_sitemap_missing_fires():
    issues, _ = run_audit(
        [extract_page("https://demo.test/", html())],
        "demo.test",
        [Market.BASE],
        site_facts={"sitemap_found": False},
    )
    assert [i for i in issues if i.code == "sitemap.missing"]


def test_sitemap_rule_stays_silent_when_not_probed():
    """爬虫没探测 sitemap 时不应误报——没有信息不等于有问题。"""
    issues, _ = run_audit(
        [extract_page("https://demo.test/", html())], "demo.test", [Market.BASE]
    )
    assert not [i for i in issues if i.code == "sitemap.missing"]


def test_robots_blocks_own_site_detected():
    issues, _ = run_audit(
        [extract_page("https://demo.test/", html())],
        "demo.test",
        [Market.BASE],
        site_facts={
            "robots_status": 200,
            "robots_directives": [("*", ["Disallow: /"])],
        },
    )
    blocked = [i for i in issues if i.code == "robots.blocks_own_site"]
    assert blocked
    assert blocked[0].severity is Severity.CRITICAL


def test_robots_allowing_everything_is_fine():
    issues, _ = run_audit(
        [extract_page("https://demo.test/", html())],
        "demo.test",
        [Market.BASE],
        site_facts={
            "robots_status": 200,
            "robots_directives": [("*", ["Allow: /", "Disallow: /admin"])],
        },
    )
    assert not [i for i in issues if i.code == "robots.blocks_own_site"]


# --------------------------------------------------------------------------
# 引擎健壮性
# --------------------------------------------------------------------------


def test_rule_error_does_not_abort_scan():
    """单条规则抛异常时，其它规则仍要继续跑完。"""
    from app.audit import engine as eng

    class Boom(eng.Rule):
        code = "test.boom"
        title = "故意崩溃的规则"

        def check(self, page, ctx):
            raise ValueError("故意的")

    reg = eng.default_registry()
    reg._page_rules.append(Boom())
    try:
        pages = [extract_page("https://demo.test/", html(title=None))]
        issues, _ = eng.run_audit(pages, "demo.test", [Market.BASE])
        codes = {i.code for i in issues}
        assert "rule.error.test.boom" in codes
        assert "title.missing" in codes  # 崩溃规则没影响其它规则
    finally:
        reg._page_rules.pop()


def test_issue_dedup_keeps_most_severe():
    from app.audit.engine import dedupe
    from app.models import Issue

    issues = [
        Issue(code="x.y", severity=Severity.LOW, url="u"),
        Issue(code="x.y", severity=Severity.CRITICAL, url="u"),
        Issue(code="x.y", severity=Severity.MEDIUM, url="u"),
    ]
    assert len(dedupe(issues)) == 1
    assert dedupe(issues)[0].severity is Severity.CRITICAL
