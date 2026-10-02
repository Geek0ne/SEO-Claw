"""HTML 报告渲染测试。

渲染层最容易出的错不是「样式丑」，而是**撒谎**：
把「没审到任何页面」画成 0 分或满分、把 1 页的抽样说成全站结论。
这些看起来都像正常报告，用户没有任何线索能发现报告是假的。
所以这里的断言大部分是「不该出现的字样必须不出现」。
"""

from __future__ import annotations

import re

from app.audit.engine import run_audit
from app.extract import extract_page
from app.models import Market, SiteReport, Severity
from app.report_html import render_html
from app.scoring import score


def _page(url: str, *, good: bool = False) -> str:
    if good:
        return (
            '<html lang="en"><head><title>A Perfectly Reasonable Page Title Here</title>'
            '<meta name="description" content="A description long enough to pass the check.">'
            '<link rel="canonical" href="/p">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"></head>'
            "<body><h1>Heading</h1><p>Real body content that is long enough.</p></body></html>"
        )
    # 无 lang / 无 description / 无 viewport / 无 h1 / 空锚文本 —— 一条 HTML 踩多条规则
    return (
        "<html><head><title>x</title></head><body><p>hi</p>"
        '<a href="/a"></a><a href="/b"></a><a href="/c"></a></body></html>'
    )


def _report(pages, issues=None):
    if issues is None:
        issues, _ = run_audit(pages, "demo.test", [Market.BASE, Market.GOOGLE], {})
    ok_pages = [p for p in pages if p.status_code == 200 and not p.error]
    h, b = score(issues, len(ok_pages) or 1, domain="demo.test")
    return SiteReport(
        domain="demo.test",
        markets=[Market.BASE, Market.GOOGLE],
        pages_crawled=len(ok_pages),
        pages_discovered=len(pages) + 30,
        health_score=h,
        score_breakdown=b,
        issues=issues,
    ), issues


def _body(html: str) -> str:
    """剥掉 <style>，只看真实渲染内容。

    ⚠️ 必须剥：'score-num' 这样的串在 CSS 里有 `.score-num{...}` 规则，
    直接在全文里搜会永远命中，断言就成了永远为真的废测试。
    我第一版就犯了这个错——以为 0 页报告里有分数块，其实是匹配到 CSS。
    """
    return html.split("</style>", 1)[1] if "</style>" in html else html


# --------------------------------------------------------------------------
# 单文件 / 无外链
# --------------------------------------------------------------------------


def test_is_self_contained_no_external_requests():
    """报告要能存三年后打开，所以不能引 CDN。

    任何 http(s):// 的 <link>/<script>/@import 都会让离线打开时样式全丢，
    而那种情况下用户看到的是一份**没有任何样式的白底黑字**——
    比 Markdown 更糟，因为排版信息被丢掉了却看不出来。
    """
    pages = [extract_page(f"https://demo.test/{i}", _page(f"https://demo.test/{i}")) for i in range(5)]
    rep, _ = _report(pages)
    out = render_html(rep, pages)

    assert "<link" not in out, "不该有 <link>（会引外链样式）"
    assert "<script" not in out, "不该有 <script>"
    assert "@import" not in out
    assert "<iframe" not in out
    assert "@font-face" not in out

    # ⚠️ 只查**会发起请求的资源标签**（link/script/iframe/img 的 src）。
    # `<a href="https://...">` 是证据链接，必须允许——它是报告的价值所在。
    # 我第一版写的是 `(?:src|href)="(https?://…)"` 全局匹配，
    # 结果把每个证据 URL 都当成外链，这个断言变成永远失败。
    # 离线打开报告时，浏览器只在这些标签上真正发请求。
    for m in re.finditer(
        r'<(?:link|script|iframe|img|object|embed)\b[^>]*'
        r'(?:src|href)="(https?://[^"]+)"',
        out,
    ):
        raise AssertionError(f"发现会发起请求的外链：{m.group(1)}")


def test_html_is_wellformed_closing_tags():
    pages = [extract_page(f"https://demo.test/{i}", _page(f"https://demo.test/{i}")) for i in range(4)]
    rep, _ = _report(pages)
    out = render_html(rep, pages)
    assert out.strip().startswith("<!doctype html>")
    assert out.rstrip().endswith("</html>")
    assert out.count("<html") == 1 and out.count("</html>") == 1
    for tag in ("html", "head", "body", "style"):
        assert out.count(f"<{tag}") >= 1 and out.count(f"</{tag}>") == 1, f"<{tag}> 不配对"


# --------------------------------------------------------------------------
# 0 页场景：最关键的一组
# --------------------------------------------------------------------------


def test_zero_pages_renders_unevaluated_not_zero_score():
    """⚠️ 0 页必须渲染成「未评估」，绝不能是 0 分或满分。

    0 分意味着「审了，结果很差」；未评估意味着「这次什么也没检查到」。
    用户把未评估当成 0 分，就会以为自己站点很烂并去做无意义的修复——
    而实际上什么都没检查。
    """
    rep = SiteReport(domain="blocked.test", pages_crawled=0, pages_discovered=40, issues=[])
    out = render_html(rep, [])
    body = _body(out)

    assert "未评估" in body
    assert 'class="score-num' not in body, "0 页不该画分数块"
    assert "/ 100" not in body, "0 页不该出现百分制刻度"
    assert "没有审到任何页面" in body
    # 必须明确说出「未评估 ≠ 没问题」
    assert "不等于" in body and "没问题" in body


def test_zero_pages_says_why():
    """0 页要说明常见原因，否则用户不知道该查 robots 还是网络。"""
    rep = SiteReport(domain="blocked.test", pages_crawled=0, pages_discovered=40, issues=[])
    body = _body(render_html(rep, []))
    for kw in ("robots", "限流", "JS", "网络"):
        assert kw in body, f"0 页提示里应提到 {kw}"


# --------------------------------------------------------------------------
# 小样本警告
# --------------------------------------------------------------------------


def test_small_sample_warns():
    """页数少时扣分系数太粗，分数不能当精确值读。"""
    pages = [extract_page("https://demo.test/1", _page("https://demo.test/1"))]
    rep, _ = _report(pages)
    body = _body(render_html(rep, pages))
    assert "样本量" in body and "不要当全站结论" in body


def test_large_sample_no_small_sample_warning():
    pages = [
        extract_page(f"https://demo.test/{i}", _page(f"https://demo.test/{i}"))
        for i in range(25)
    ]
    rep, _ = _report(pages)
    body = _body(render_html(rep, pages))
    assert "不要当全站结论" not in body, "25 页不该再报样本量警告"


# --------------------------------------------------------------------------
# 内容正确性
# --------------------------------------------------------------------------


def test_shows_real_score_and_dimension_table():
    pages = [extract_page(f"https://demo.test/{i}", _page(f"https://demo.test/{i}")) for i in range(30)]
    rep, _ = _report(pages)
    body = _body(render_html(rep, pages))
    assert 'class="score-num' in body and "/ 100" in body
    assert "维度" in body and "可抓取与收录" in body


def test_issue_count_matches_report():
    """报告里说的条数必须等于引擎真实产出的条数。

    渲染层自己数一遍自己的分组、再算一个总数，两边对不上就是渲染层在编数字。
    """
    pages = [extract_page(f"https://demo.test/{i}", _page(f"https://demo.test/{i}")) for i in range(6)]
    rep, issues = _report(pages)
    body = _body(render_html(rep, pages))
    assert issues, "样本应命中若干规则"
    assert "全部问题明细" in body
    for code in {i.code for i in issues}:
        assert code in body, f"code {code} 应出现在报告里"


def test_grouping_reports_affected_page_count():
    """同一 code 影响多页时要写清是「几处」，不能只出现一次就没了。"""
    pages = [extract_page(f"https://demo.test/{i}", _page(f"https://demo.test/{i}")) for i in range(6)]
    rep, issues = _report(pages)
    body = _body(render_html(rep, pages))
    assert "处" in body and "页面" in body, "应说明影响了几处页面"


def test_top_actions_section_present():
    pages = [extract_page(f"https://demo.test/{i}", _page(f"https://demo.test/{i}")) for i in range(6)]
    rep, issues = _report(pages)
    body = _body(render_html(rep, pages))
    assert "最该先做的 5 件事" in body


def test_clean_site_says_scoped_not_perfect():
    """没命中规则时不能写「你的站没问题」——只抽查了几页而已。"""
    pages = [
        extract_page(f"https://demo.test/{i}", _page(f"https://demo.test/{i}", good=True))
        for i in range(25)
    ]
    rep, issues = _report(pages)
    body = _body(render_html(rep, pages))
    if not issues:
        assert "不" in body and "没有发现问题" in body
        assert "全站没问题" not in body, "不能宣称全站没问题"


# --------------------------------------------------------------------------
# 转义
# --------------------------------------------------------------------------


def test_escapes_html_injected_via_title():
    """⚠️ title/description 来自被扫站点的 HTML，而报告是要被转发出去的。

    不转义，报告就成 XSS 载体。

    我第一版这个用例的前提就不成立：拿一个 title 里塞 <script> 的页面去跑，
    但那页命中的是 h1.missing / meta.missing 等规则，**title 压根没进任何结论**，
    于是「转义了」和「没渲染」两种情况都能通过断言 —— 假阳性。
    现在直接构造一条 title 带恶意标签的 Issue，验证的是渲染层本身。
    """
    from app.models import Issue, Scope

    evil = Issue(
        code="title.too_long",
        severity=Severity.MEDIUM,
        market=Market.BASE,
        scope=Scope.PAGE,
        url="https://evil.test/<img src=x onerror=alert(1)>",
        title="<script>alert(1)</script>",
        description="</div><script>alert(2)</script>",
        fix_hint="<b>加粗</b> & 转义",
    )
    pages = [extract_page("https://evil.test/", _page("https://evil.test/"))]
    rep, _ = _report(pages, [evil])
    body = _body(render_html(rep, pages))

    assert "<script>alert(1)</script>" not in body, "title 里的 script 未转义"
    assert "<script>alert(2)</script>" not in body, "description 里的 script 未转义"
    assert "onerror=alert(1)" not in body or "&lt;img" in body, "url 未转义"
    assert "&lt;script&gt;" in body, "应转义成可见文本，而不是凭空消失"
    assert "&amp;" in body or "&lt;b&gt;" in body, "fix_hint 里的标签也应转义"


def test_escapes_html_injected_via_url():
    """URL 也来自外部，evidence 里的 URL 同样要转义。"""
    pages = [extract_page("https://demo.test/y", _page("https://demo.test/y"))]
    rep, issues = _report(pages)
    for i in issues:
        if i.url:
            assert '"><script' not in i.url
    out = render_html(rep, pages)
    assert "<a href=\"\"><script" not in out