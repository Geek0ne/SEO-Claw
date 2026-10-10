"""
百度 / 中文生态规则测试。

覆盖 6 条新增规则，每条都有「应触发」和「不应触发」两个方向。
两个额外测试专门锁住产品硬要求：**中英文长度阈值必须分开**。

运行：
    cd backend && PYTHONPATH=../.deps:. python3 -m pytest tests/ -q
"""

from __future__ import annotations

from seoclaw.audit.engine import run_audit
from seoclaw.extract import extract_page
from seoclaw.models import LinkKind, LinkRef, Market, Severity

BAIDU = [Market.BASE, Market.BAIDU]
CNH = [Market.BASE, Market.CNH_ECO]


# --------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------


def html(
    *,
    title: str | None = "示例页面 - 演示站",
    description: str | None = "这是一个用于测试的页面描述，包含足够长度的文本内容。",
    h1: str | None = "示例页面",
    viewport: str | None = "width=device-width, initial-scale=1",
    lang: str = "zh-CN",
    body: str = "<p>内容</p>",
    links: list[tuple[str, str]] | None = None,
) -> str:
    parts = ["<!DOCTYPE html>", f'<html lang="{lang}">', "<head>", '<meta charset="utf-8">']
    if title is not None:
        parts.append(f"<title>{title}</title>")
    if description is not None:
        parts.append(f'<meta name="description" content="{description}">')
    if viewport is not None:
        parts.append(f'<meta name="viewport" content="{viewport}">')
    parts.append("</head>")
    if h1:
        parts.append(f"<h1>{h1}</h1>")
    parts.append(body)
    for href, anchor in links or []:
        parts.append(f'<a href="{href}">{anchor}</a>')
    parts.append("</html>")
    return "\n".join(parts)


def audit_page(source: str, url: str = "https://demo.cn/page", market=None):
    pages = [extract_page(url, source)]
    issues, _ = run_audit(pages, "demo.cn", market or BAIDU)
    return issues


def codes(issues) -> set[str]:
    return {i.code for i in issues}


def find(issues, code):
    return next(i for i in issues if i.code == code)


def make_site(n: int = 30, *, body: str | None = None, footer: str = "") -> list:
    """造一个 n 页的站点，用于触发 has_enough_data()。"""
    body = body or "<p>" + "登山鞋选购指南，覆盖防水等级与适用场景。" * 40 + "</p>"
    pages = []
    for i in range(n):
        pages.append(
            extract_page(
                f"https://demo.cn/p{i}",
                html(body=body + footer, links=[(f"https://demo.cn/p{i+1}", "下一页")]),
            )
        )
    # 首页链向所有页：制造内链，避免干扰其它站点级规则
    pages[0].links = [
        LinkRef(href=f"https://demo.cn/p{i}", anchor=f"页面{i}", kind=LinkKind.INTERNAL)
        for i in range(n)
    ]
    pages[0].internal_link_count = n
    return pages


# --------------------------------------------------------------------------
# 1. robots.baiduspider_not_allowed
# --------------------------------------------------------------------------


ROBOTS_BLOCK_ALL = {
    "robots_status": 200,
    "robots_directives": [("baiduspider", ["Disallow: /"])],
}
# 只放行 /p1（模拟「只有产品页可抓」的手滑配置）
ROBOTS_BLOCK_PART = {
    "robots_status": 200,
    "robots_directives": [("baiduspider", ["Disallow: /", "Allow: /p1"])],
}
ROBOTS_ALLOW = {
    "robots_status": 200,
    "robots_directives": [("baiduspider", ["Allow: /", "Disallow: /admin/"])],
}


def _site_audit(market, site_facts, n=30, domain="demo.cn", footer: str = ""):
    pages = make_site(n, footer=footer)
    issues, _ = run_audit(pages, domain, market, site_facts=site_facts)
    return issues


def test_baiduspider_blocked_fires_high_for_chinese_site():
    """中文站 + 全站屏蔽 Baiduspider → HIGH，且证据带上比例。"""
    issues = _site_audit(BAIDU, ROBOTS_BLOCK_ALL)
    issue = find(issues, "robots.baiduspider_not_allowed")
    assert issue.severity is Severity.HIGH
    assert issue.evidence["whole_site_blocked"] is True
    assert issue.evidence["blocked_ratio"] == 1.0
    assert issue.evidence["matched_group"] == "ua_specific"
    assert issue.evidence["robots_status"] == 200


def test_baiduspider_partial_block_is_medium():
    """只屏蔽部分路径 → 降级为 MEDIUM（可能是屏蔽参数页时的手滑）。"""
    issues = _site_audit(BAIDU, ROBOTS_BLOCK_PART)
    issue = find(issues, "robots.baiduspider_not_allowed")
    assert issue.severity is Severity.MEDIUM
    assert issue.evidence["whole_site_blocked"] is False


def test_baiduspider_allowed_does_not_fire():
    issues = _site_audit(BAIDU, ROBOTS_ALLOW)
    assert "robots.baiduspider_not_allowed" not in codes(issues)


def test_baiduspider_rule_silent_without_robots_data():
    """没有 robots 数据时不能下结论——robots 不存在（404）等于放行。"""
    issues = _site_audit(BAIDU, {"robots_status": 404, "robots_directives": []})
    assert "robots.baiduspider_not_allowed" not in codes(issues)
    issues2 = _site_audit(BAIDU, {})
    assert "robots.baiduspider_not_allowed" not in codes(issues2)


def test_baiduspider_block_downgraded_for_non_chinese_site():
    """⚠️ 有「有意为之」解释的场景：非中文站屏蔽百度 → 只给 INFO + verdict。"""
    pages = make_site(30, body="<p>" + "Best waterproof hiking boots for every trail." * 40 + "</p>")
    for p in pages:
        p.lang = "en"
    issues, _ = run_audit(
        pages, "demo.cn", BAIDU, site_facts={**ROBOTS_BLOCK_ALL, "discovered_count": 30}
    )
    issue = find(issues, "robots.baiduspider_not_allowed")
    assert issue.severity is Severity.INFO
    assert issue.evidence["verdict"] == "possibly_intentional"


def test_baiduspider_wildcard_group_applies_to_baiduspider():
    """站点只写了 `*` 组，语义上同样作用于 Baiduspider。"""
    issues = _site_audit(
        BAIDU,
        {
            "robots_status": 200,
            "robots_directives": [("*", ["Disallow: /"])],
            "discovered_count": 30,
        },
    )
    issue = find(issues, "robots.baiduspider_not_allowed")
    assert issue.evidence["matched_group"] == "wildcard"


# --------------------------------------------------------------------------
# 2. title.chinese_too_long —— 中英文阈值必须分开
# --------------------------------------------------------------------------


def test_chinese_title_too_long_fires_over_30():
    issues = audit_page(
        html(title="防水登山鞋男款防滑耐磨透气户外运动鞋大码专卖新款上架特惠包邮正品")
    )
    issue = find(issues, "title.chinese_too_long")
    assert issue.severity is Severity.MEDIUM
    assert issue.evidence["limit_zh"] == 30
    assert issue.evidence["length"] > 30
    assert issue.evidence["truncated_tail"]


def test_chinese_title_exactly_30_does_not_fire():
    issues = audit_page(html(title="防" * 30))
    assert "title.chinese_too_long" not in codes(issues)


def test_english_title_35_chars_does_not_use_chinese_limit():
    """★ 硬要求：35 个字符的英文标题不该被中文 30 字阈值判为超长。
    英文站按 60 字符算，35 字符完全合规。"""
    issues = audit_page(html(title="A" * 35, lang="en"), url="https://demo.cn/en")
    assert "title.chinese_too_long" not in codes(issues)
    assert "title.too_long" not in codes(issues)


def test_english_title_70_chars_only_triggers_english_rule():
    """英文 70 字符：只有 base 包的英文规则报，本包的中文规则保持沉默。"""
    issues = audit_page(html(title="A" * 70, lang="en"), url="https://demo.cn/en")
    assert "title.too_long" in codes(issues)
    assert "title.chinese_too_long" not in codes(issues)


def test_mixed_language_title_uses_chinese_limit():
    """标题只要含一个汉字，就按中文 30 字阈值判。"""
    issues = audit_page(html(title="防水登山鞋 " + "B" * 40), url="https://demo.cn/mix")
    assert "title.chinese_too_long" in codes(issues)


# --------------------------------------------------------------------------
# 3. meta.chinese_semantic_incomplete
# --------------------------------------------------------------------------


def test_keyword_stuffing_fires():
    issues = audit_page(
        html(
            title="登山鞋登山鞋登山鞋 男款透气登山鞋防水登山鞋",
            description="防水登山鞋专业防水登山鞋户外防水登山鞋推荐",
        )
    )
    issue = find(issues, "meta.chinese_semantic_incomplete")
    assert issue.severity is Severity.INFO
    assert issue.evidence["verdict"] == "likely_keyword_stuffing"
    assert issue.evidence["title_repeated_terms"]


def test_normal_chinese_title_does_not_fire():
    issues = audit_page(
        html(
            title="防水登山鞋 男款防滑耐磨 - 登山者",
            description="专业防水登山鞋，防滑耐磨，7 天无理由退换。",
        )
    )
    assert "meta.chinese_semantic_incomplete" not in codes(issues)


def test_keyword_stuffing_stays_silent_when_coverage_is_low():
    """正向证据类规则不受覆盖率影响：单页也能判定（因为重复是正面证据）。"""
    issues = audit_page(html(title="登山鞋登山鞋登山鞋透气登山鞋防水登山鞋"))
    assert "meta.chinese_semantic_incomplete" in codes(issues)


def test_english_repetition_does_not_fire():
    issues = audit_page(html(title="hiking boots hiking boots hiking boots", lang="en"))
    assert "meta.chinese_semantic_incomplete" not in codes(issues)


# --------------------------------------------------------------------------
# 4. icp.filing_missing
# --------------------------------------------------------------------------


def test_icp_missing_fires_as_info_with_has_enough_data():
    issues = _site_audit(BAIDU, {"discovered_count": 30})
    issue = find(issues, "icp.filing_missing")
    assert issue.severity is Severity.INFO
    assert issue.evidence["beian_links_found"] == 0
    assert issue.evidence["pages_checked"] == 30
    assert issue.evidence["mainland_signal"]["tld_cn"] is True


def test_icp_rule_silent_when_coverage_too_low():
    """★ 覆盖不足时「没看到备案」只是没抓到，必须沉默。"""
    pages = [extract_page("https://demo.cn/", html())]
    issues, _ = run_audit(
        pages, "demo.cn", BAIDU, site_facts={"discovered_count": 900}
    )
    assert "icp.filing_missing" not in codes(issues)


def test_icp_present_in_footer_link_does_not_fire():
    footer = '<a href="https://beian.miit.gov.cn/">京ICP备12345678号-1</a>'
    issues = _site_audit(BAIDU, {"discovered_count": 30}, footer=footer)
    assert "icp.filing_missing" not in codes(issues)


def test_icp_rule_silent_for_non_mainland_domain():
    """非 .cn 且英文站 → 不提示备案。"""
    pages = make_site(30, body="<p>" + "Best hiking boots reviewed by our team. " * 40 + "</p>")
    for p in pages:
        p.lang = "en"
    issues, _ = run_audit(
        pages, "example.com", BAIDU, site_facts={"discovered_count": 30}
    )
    assert "icp.filing_missing" not in codes(issues)


# --------------------------------------------------------------------------
# 5. mobile.landing_page_missing
# --------------------------------------------------------------------------


def test_viewport_missing_fires_high():
    issues = audit_page(html(viewport=None))
    issue = find(issues, "mobile.landing_page_missing")
    assert issue.severity is Severity.HIGH
    assert issue.evidence["viewport_found"] is False
    assert issue.evidence["verdict"] == "likely_missing"


def test_viewport_present_does_not_fire():
    issues = audit_page(html(viewport="width=device-width, initial-scale=1.0"))
    assert "mobile.landing_page_missing" not in codes(issues)


def test_viewport_missing_downgraded_when_mobile_subdomain_exists():
    """⚠️ 有意为之：另有独立移动站 → 降级为 MEDIUM + verdict。"""
    issues = audit_page(
        html(viewport=None, links=[("https://m.demo.cn/", "手机版")])
    )
    issue = find(issues, "mobile.landing_page_missing")
    assert issue.severity is Severity.MEDIUM
    assert issue.evidence["verdict"] == "possibly_separate_mobile_site"
    assert issue.evidence["mobile_domain_links"]


def test_baidu_rules_not_run_on_other_markets():
    """市场隔离：不启用 BAIDU 时，本包规则一条都不该出现。"""
    issues = audit_page(
        html(viewport=None, title="防水登山鞋" * 10), url="https://demo.cn/x", market=[Market.BASE]
    )
    assert "mobile.landing_page_missing" not in codes(issues)
    assert "title.chinese_too_long" not in codes(issues)


# --------------------------------------------------------------------------
# 6. cnh_eco: wechat.sogou_not_indexable
# --------------------------------------------------------------------------


def test_wechat_rule_fires_for_chinese_site_without_wechat_links():
    issues = _site_audit(CNH, {"discovered_count": 30})
    issue = find(issues, "wechat.sogou_not_indexable")
    assert issue.severity is Severity.INFO
    assert issue.evidence["verdict"] == "no_wechat_channel_detected"
    assert issue.evidence["wechat_links_found"] == 0
    assert "搜一搜" in issue.description or "微信" in issue.description


def test_wechat_rule_silent_when_site_links_to_wechat():
    footer = '<a href="https://mp.weixin.qq.com/s/abc">关注公众号</a>'
    issues = _site_audit(CNH, {"discovered_count": 30}, footer=footer)
    assert "wechat.sogou_not_indexable" not in codes(issues)


def test_wechat_rule_silent_when_coverage_too_low():
    pages = [extract_page("https://demo.cn/", html())]
    issues, _ = run_audit(pages, "demo.cn", CNH, site_facts={"discovered_count": 900})
    assert "wechat.sogou_not_indexable" not in codes(issues)


def test_wechat_rule_silent_for_non_chinese_site():
    pages = make_site(30, body="<p>" + "Best waterproof hiking boots for every trail. " * 40 + "</p>")
    for p in pages:
        p.lang = "en"
    issues, _ = run_audit(
        pages, "example.com", CNH, site_facts={"discovered_count": 30}
    )
    assert "wechat.sogou_not_indexable" not in codes(issues)


def test_wechat_rule_not_registered_for_baidu_market():
    """中文生态规则只在 CNH_ECO 市场运行。"""
    issues = _site_audit(BAIDU, {"discovered_count": 30})
    assert "wechat.sogou_not_indexable" not in codes(issues)


def test_nap_rule_not_implemented():
    """NAP 一致性经评估后**放弃**：页脚被抽取器剥离，做出来必然是误报。
    这条测试把「不做」也钉住，避免以后有人误以为漏实现了。"""
    issues = _site_audit(CNH, {"discovered_count": 30})
    assert "nap.entity_inconsistent" not in codes(issues)
