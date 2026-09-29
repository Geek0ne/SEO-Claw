"""
i18n 与社交分享规则测试（hreflang / og:*）。

背景：这些规则是「数据层补齐之后」才写得出来的。
两个并行的规则子任务都独立放弃了 hreflang，理由相同——
Page 没有 hreflang 字段、extract 不采集，写出来就是永不触发的死规则。
先补数据层（models.py + extract.py），再写规则（google/i18n.py），最后才有这些用例。
顺序反了，规则就是摆设。
"""

from __future__ import annotations

from app.audit.engine import run_audit
from app.extract import extract_page
from app.models import Market, Severity


def html(head_extra: str = "", *, lang: str = "en", body: str = "<p>content</p>") -> str:
    return f'<html lang="{lang}"><head>{head_extra}</head><body>{body}</body></html>'


def audit(source: str, url: str = "https://demo.test/p", site_facts=None):
    page = extract_page(url, source, final_url=url)
    issues, _ = run_audit([page], "demo.test", [Market.BASE, Market.GOOGLE], site_facts)
    return issues


def codes(issues, code: str) -> list:
    return [i for i in issues if i.code == code]


# --------------------------------------------------------------------------
# 提取层：数据源本身
# --------------------------------------------------------------------------


def test_extracts_hreflang_pairs():
    page = extract_page(
        "https://demo.test/en",
        html(
            '<link rel="alternate" hreflang="zh-CN" href="/zh">'
            '<link rel="alternate" hreflang="x-default" href="/">',
            lang="en",
        ),
    )
    assert dict(page.hreflang)["zh-CN"] == "https://demo.test/zh"
    assert ("x-default", "https://demo.test/") in page.hreflang


def test_hreflang_relative_resolved_to_absolute():
    """相对 href 必须解析成绝对地址，否则回访时拼不出正确 URL。"""
    page = extract_page(
        "https://demo.test/en",
        html('<link rel="alternate" hreflang="fr" href="/fr">', lang="en"),
    )
    assert page.hreflang[0][1].startswith("https://")


def test_extracts_og_fields():
    page = extract_page(
        "https://demo.test/p",
        html(
            '<meta property="og:title" content="T">'
            '<meta property="og:description" content="D">'
            '<meta property="og:image" content="/cover.png">'
            '<meta name="twitter:card" content="summary">',
        ),
    )
    assert page.og_title == "T"
    assert page.og_description == "D"
    assert page.og_image == "https://demo.test/cover.png"
    assert page.twitter_card == "summary"


def test_no_hreflang_when_absent():
    page = extract_page("https://demo.test/p", html())
    assert page.hreflang == []


# --------------------------------------------------------------------------
# hreflang 自引用
# --------------------------------------------------------------------------


def test_self_reference_present_is_fine():
    issues = audit(
        html(
            '<link rel="alternate" hreflang="en" href="https://demo.test/p">'
            '<link rel="alternate" hreflang="zh-CN" href="https://demo.test/zh">',
            lang="en",
        )
    )
    assert not codes(issues, "hreflang.self_reference_missing")


def test_self_reference_missing_fires():
    """声明了 hreflang 却没有指向自己且语言匹配的条目。"""
    issues = audit(
        html('<link rel="alternate" hreflang="zh-CN" href="https://demo.test/zh">', lang="en")
    )
    hit = codes(issues, "hreflang.self_reference_missing")
    assert hit, "缺自引用未检出"
    assert hit[0].evidence["verdict"] == "missing_self_reference"


def test_xdefault_counts_as_self_reference():
    """x-default 指向本页也算自引用——这是合法的常见写法。"""
    issues = audit(
        html('<link rel="alternate" hreflang="x-default" href="https://demo.test/p">', lang="en")
    )
    assert not codes(issues, "hreflang.self_reference_missing")


def test_no_hreflang_means_no_self_reference_warning():
    """单语站没 hreflang 完全正常，不能报。"""
    assert not codes(audit(html()), "hreflang.self_reference_missing")


# --------------------------------------------------------------------------
# x-default
# --------------------------------------------------------------------------


def test_x_default_missing_fires_for_multilingual():
    issues = audit(
        html(
            '<link rel="alternate" hreflang="en" href="https://demo.test/p">'
            '<link rel="alternate" hreflang="zh-CN" href="https://demo.test/zh">',
            lang="en",
        )
    )
    assert codes(issues, "hreflang.x_default_missing")


def test_x_default_not_required_for_monolingual():
    """只有一个语言版本时不需要 x-default——否则每个单语站都会多一条噪音。"""
    issues = audit(
        html('<link rel="alternate" hreflang="en" href="https://demo.test/p">', lang="en")
    )
    assert not codes(issues, "hreflang.x_default_missing")


# --------------------------------------------------------------------------
# lang 一致性
# --------------------------------------------------------------------------


def test_lang_not_in_hreflang_fires():
    issues = audit(
        html('<link rel="alternate" hreflang="ja" href="https://demo.test/ja">', lang="en")
    )
    assert codes(issues, "hreflang.inconsistent_with_lang")


def test_lang_consistent_is_silent():
    issues = audit(
        html('<link rel="alternate" hreflang="en" href="https://demo.test/p">', lang="en")
    )
    assert not codes(issues, "hreflang.inconsistent_with_lang")


def test_region_variant_still_counts_as_same_language():
    """lang="en-US" 与 hreflang="en" 属于同一语言，不该报。"""
    issues = audit(
        html('<link rel="alternate" hreflang="en" href="https://demo.test/p">', lang="en-US")
    )
    assert not codes(issues, "hreflang.inconsistent_with_lang")


# --------------------------------------------------------------------------
# hreflang 目标可疑
# --------------------------------------------------------------------------


def test_hreflang_pointing_to_pdf_is_high():
    issues = audit(
        html('<link rel="alternate" hreflang="en" href="https://demo.test/manual.pdf">', lang="en")
    )
    hit = codes(issues, "hreflang.suspicious_target")
    assert hit
    assert hit[0].severity is Severity.HIGH


def test_hreflang_pointing_to_page_is_fine():
    issues = audit(
        html('<link rel="alternate" hreflang="en" href="https://demo.test/guide.html">', lang="en")
    )
    assert not codes(issues, "hreflang.suspicious_target")


# --------------------------------------------------------------------------
# og 标签
# --------------------------------------------------------------------------


def test_og_missing_fires_low():
    """og 缺失只影响分享卡片，不影响排名——必须 LOW。报高危是夸大。"""
    hit = codes(audit(html()), "og.basic_missing")
    assert hit
    assert hit[0].severity is Severity.LOW


def test_og_complete_is_silent():
    issues = audit(
        html(
            '<meta property="og:title" content="T">'
            '<meta property="og:description" content="D">'
            '<meta property="og:image" content="https://demo.test/c.png">'
        )
    )
    assert not codes(issues, "og.basic_missing")


def test_og_broken_image_needs_probe_data():
    """没做回访就不能断言图片坏了——「没检查过」不等于「有问题」。"""
    issues = audit(html('<meta property="og:image" content="https://demo.test/gone.png">'))
    assert not codes(issues, "og.image_broken")


def test_og_broken_image_fires_when_probe_failed():
    issues = audit(
        html('<meta property="og:image" content="https://demo.test/gone.png">'),
        site_facts={"og_image_status": {"demo.test/gone.png": 404}},
    )
    hit = codes(issues, "og.image_broken")
    assert hit
    assert hit[0].evidence["status"] == 404
