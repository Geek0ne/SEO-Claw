"""2026-10-01 真实扫描回源核对：base 包 4 条规则的误报回归。

背景：107 站扫描后逐条回访 URL、比对真实内容，base 包被判 4 条真误报。
本文件的每条用例都来自**实跑**（curl / extract_page）拿到的真实证据，
不是凭空编的形状。核对结论有两条和预期不同，见下面两个类的 docstring。

反向用例是这份测试的重点：防止修误报时把规则改成永远沉默。
"""

from __future__ import annotations

import pytest

from app.audit.engine import run_audit
from app.extract import extract_page
from app.models import Market, Severity


# --------------------------------------------------------------------------
# fixture 构造器
# --------------------------------------------------------------------------


def audit_one(source: str, url: str = "https://demo.test/page", status_code: int = 200):
    pages = [extract_page(url, source, status_code=status_code, final_url=url)]
    issues, _ = run_audit(pages, url.split("/")[2], [Market.BASE])
    return {i.code for i in issues}, issues


def _codes(source: str, url: str, status_code: int = 200) -> set[str]:
    codes, _ = audit_one(source, url, status_code)
    return codes


def static_html(
    *,
    title: str | None = "一个长度足够的正常页面标题用于测试",
    h1: str | None = "页面主标题",
    lang: str = "zh-CN",
    body: str = "<p>正文内容。</p>",
) -> str:
    """一段服务端渲染的普通静态页面——likely_js_rendered 必为 False。"""
    parts = [
        "<!DOCTYPE html>",
        f'<html lang="{lang}">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="description" content="这是一个用于测试的页面描述，长度足够。">',
    ]
    if title is not None:
        parts.append(f"<title>{title}</title>")
    parts.append("</head>")
    if h1 is not None:
        parts.append(f"<h1>{h1}</h1>")
    parts.append(body)
    parts.append("</html>")
    return "\n".join(parts)


def js_shell_html(*, title: str | None = None) -> str:
    """复刻 agoda 的形态：体积很大、静态里几乎没有文字、几乎没有出链。

    这三个条件同时成立才可能被判成 likely_js_rendered（见
    extract._looks_js_rendered_shell）：单独「大体积」不成立，
    shopify 662KB 有 6859 字正文，是正常页面。
    """
    padding = "/* app bundle */" + "x" * 900 + "\n"
    bundles = padding * 70  # ≈ 64KB，稳定超过 _JS_RENDERED_MIN_BYTES
    return (
        "<!DOCTYPE html>"
        '<html lang="zh-Hans"><head><meta charset="utf-8">'
        + (f"<title>{title}</title>" if title else "")
        + "</head><body>"
        '<div id="agoda-spa" v-cloak></div>'
        '<div data-reactroot></div>'
        "<script>" + bundles + "</script>"
        "</body></html>"
    )


def assert_flag(source: str, url: str, expected: bool) -> None:
    """先确认 fixture 真的造出了预期的页面性质，否则用例是空转的。"""
    page = extract_page(url, source, status_code=200, final_url=url)
    assert page.likely_js_rendered is expected, (
        f"fixture 造出的 likely_js_rendered={page.likely_js_rendered}，"
        f"预期 {expected}"
    )


# --------------------------------------------------------------------------
# title.too_short
# --------------------------------------------------------------------------


class TestTitleTooShortFunctionalPages:
    """实跑证据：这三条的 title 短是**正确**的，不该按「浪费黄金位」评估。

    实测（curl + extract_page）：
      https://www.gov.sg/            title='Home | gov.sg'  13 字，站点根路径
      https://www.indiehackers.com/login 302 → /sign-in
                                    title='Sign in'        7 字
    「网站无障碍声明」是中文无障碍声明页；我按 bellroy 找它的真实 URL
    是 /customer-care/web-accessibility-statement，该页 title 实为
    'Web Accessibility Statement'（27 字），**本来就不触发**这条规则。
    即「无障碍声明页的短 title 不该参与黄金位评估」这个判断成立，
    但它不是一个 bellroy 的实测误报样本——见汇报。
    """

    def test_gov_sg_homepage_is_silent(self):
        """首页 title 就该简洁：'Home | gov.sg' 不该被要求凑够 15 字。"""
        url = "https://www.gov.sg/"
        assert "title.too_short" not in _codes(static_html(title="Home | gov.sg"), url)

    def test_indiehackers_login_is_silent(self):
        """登录页实测 302 到 /sign-in，'Sign in' 是登录页的规范写法。"""
        url = "https://www.indiehackers.com/sign-in"
        assert "title.too_short" not in _codes(static_html(title="Sign in"), url)

    def test_accessibility_statement_page_is_silent(self):
        url = "https://demo.test/accessibility"
        assert "title.too_short" not in _codes(
            static_html(title="网站无障碍声明"), url
        )

    @pytest.mark.parametrize(
        "url",
        [
            "https://demo.test/login",
            "https://demo.test/signin",
            "https://demo.test/sign-in",
            "https://demo.test/auth",
            "https://demo.test/privacy-policy",
            "https://demo.test/terms-of-use",
            "https://demo.test/cookie-policy",
        ],
    )
    def test_other_functional_urls_are_silent(self, url):
        assert "title.too_short" not in _codes(static_html(title="Sign in"), url)


class TestTitleTooShortReverse:
    """反向用例：不能被改成永远沉默。"""

    @pytest.mark.parametrize(
        "title",
        ["Buy shoes", "Best shoes", "Cheap shoes", "Shoes for men"],
    )
    def test_short_title_on_content_page_still_fires(self, title):
        """内容页的短 title 是真问题——它确实没覆盖用户会搜的词。

        ⚠️ 这里刻意不取 "Shoes" / "Waterproof Hiking Shoes" 这类纯首字母大写的
        短语：它们会先被 _looks_like_proper_name 豁免掉（站名/品牌名豁免是
        早就在的行为，不是我这次加的）。要测「内容页短 title 仍要报」，
        得用含小写功能词的、确实像标题而不是像品牌名的短句。
        """
        url = "https://demo.test/products/waterproof-shoes"
        assert "title.too_short" in _codes(static_html(title=title), url)

    def test_title_of_15_chars_or_more_is_out_of_scope(self):
        """≥15 字符本就不是 too_short 的范围（与功能性页面无关）。"""
        url = "https://demo.test/products/x"
        assert "title.too_short" not in _codes(
            static_html(title="waterproof shoes"), url
        )

    def test_short_title_on_content_page_is_not_silenced_by_login_exemption(self):
        """登录页豁免按 URL 判定，不能溢出到内容页。

        同一句 'Sign in'：出现在 /sign-in 上闭嘴（正确），
        出现在 /blog/post 上仍要报（豁免没溢出）。
        """
        assert "title.too_short" not in _codes(
            static_html(title="Sign in"), "https://demo.test/sign-in"
        )
        assert "title.too_short" in _codes(
            static_html(title="Sign in"), "https://demo.test/blog/post"
        )

    def test_placeholder_title_on_homepage_still_fires(self):
        """首页豁免**不覆盖默认占位符**。

        'Home'/'Index'/'Document' 既没品牌也没关键词，是没改完的模板默认值，
        是真问题。功能性页面的豁免不能顺手放过它。
        """
        for placeholder in ("Home", "Index", "Document", "Untitled"):
            assert "title.too_short" in _codes(
                static_html(title=placeholder), "https://demo.test/"
            ), f"首页占位符 {placeholder!r} 应该报"

    def test_placeholder_title_on_login_page_still_fires(self):
        assert "title.too_short" in _codes(
            static_html(title="Document"), "https://demo.test/login"
        )

    def test_long_enough_title_never_fires(self):
        codes = _codes(
            static_html(title="防水登山鞋 男款防滑耐磨 户外徒步装备"), "https://demo.test/"
        )
        assert "title.too_short" not in codes


# --------------------------------------------------------------------------
# title.missing
# --------------------------------------------------------------------------


class TestTitleMissingJsRendered:
    """实跑证据：agoda 的静态 HTML 里**根本没有 <title> 标签**。

    curl -sL https://www.agoda.com/ → 1,106,008 字节，
    `grep -c -i '<title'` → **0**。extract_page 实测 title=None、
    likely_js_rendered=True、h1_count=0。它不是没写 title，是 JS 注入的。

    「静态里没找到」推不出「页面没有 title」——和 noindex.present、
    Soft404 是同一个错误。修法是引入提取层实测出来的 likely_js_rendered，
    不是放宽阈值。
    """

    def test_agoda_shaped_page_without_title_is_silent(self):
        url = "https://www.agoda.com/"
        src = js_shell_html()
        assert_flag(src, url, True)
        assert "title.missing" not in _codes(src, url)

    def test_js_rendered_page_with_title_still_no_issue(self):
        url = "https://demo.test/"
        src = js_shell_html(title="Agoda")
        assert_flag(src, url, True)
        assert "title.missing" not in _codes(src, url)


class TestTitleMissingReverse:
    """反向用例：真缺 title 的静态页面必须照报 CRITICAL。"""

    def test_static_page_without_title_still_fires(self):
        url = "https://demo.test/plain"
        src = static_html(title=None)
        assert_flag(src, url, False)
        codes, issues = audit_one(src, url)
        assert "title.missing" in codes
        sev = {i.code: i.severity for i in issues}
        assert sev["title.missing"] is Severity.CRITICAL

    def test_small_static_page_without_title_still_fires(self):
        """体积小的普通静态页缺 title，必须照报。

        ⚠️ 反向用例，防止把修法写成「体积小于某个值就闭嘴」或
        「看到 v-cloak / id=root 就闭嘴」——那是放宽阈值，不是修根因。

        实测：带 id="root" + v-if 的小页面确实会被提取层判成
        likely_js_rendered=True（_JS_MOUNT_RE / _JS_FRAMEWORK_RE 命中），
        那是**正确**的信号，不在本用例讨论范围。此处只验证
        「无框架痕迹的普通静态页」不被放过。
        """
        url = "https://demo.test/small"
        src = static_html(title=None)
        assert_flag(src, url, False)
        assert "title.missing" in _codes(src, url)

    def test_non_200_status_never_fires(self):
        url = "https://demo.test/gone"
        src = static_html(title=None)
        assert "title.missing" not in _codes(src, url, status_code=404)


# --------------------------------------------------------------------------
# h1.missing
# --------------------------------------------------------------------------


class TestH1MissingNotARealFalsePositive:
    """⚠️ **核对结论：arxiv.org / bellroy.com 这两条不是误报。**

    实跑证据（直接 grep 原始 HTML，不经解析层）：
      https://arxiv.org/   `<h1` 命中 **0** 次，`<h2` 命中 9 次，
                          body id="front"，38,051 字节，
                          likely_js_rendered=**False**（服务端渲染）
      https://bellroy.com/ `<h1` 命中 **0** 次，505,471 字节，
                          likely_js_rendered=**False**
    两个页面**真的没有 h1**，不是提取层漏采。规则判对了，是我的核对器
    判错了。按纪律不为凑数改规则：h1.missing 对静态页面保持原样。

    唯一有据可改的是 JS 渲染页：agoda 实测 h1_count=0 且
    likely_js_rendered=True，同一个「我看不见 ≠ 它不存在」问题。
    """

    def test_arxiv_shaped_page_still_fires(self):
        """服务端渲染、真的没有 h1 的页面必须照报。"""
        url = "https://arxiv.org/"
        src = static_html(title="arXiv.org e-Print archive", h1=None)
        assert_flag(src, url, False)
        codes, issues = audit_one(src, url)
        assert "h1.missing" in codes
        sev = {i.code: i.severity for i in issues}
        assert sev["h1.missing"] is Severity.HIGH

    def test_bellroy_shaped_page_still_fires(self):
        url = "https://bellroy.com/"
        src = static_html(
            title="Bellroy | Considered Carry Goods", h1=None
        )
        assert_flag(src, url, False)
        assert "h1.missing" in _codes(src, url)

    def test_page_with_h1_does_not_fire(self):
        url = "https://demo.test/"
        assert "h1.missing" not in _codes(static_html(h1="有标题"), url)


class TestH1MissingJsRendered:
    """JS 渲染页：静态里看不到 h1，不能断言「页面没有 h1」。"""

    def test_js_rendered_page_without_h1_is_silent(self):
        url = "https://www.agoda.com/"
        src = js_shell_html()
        assert_flag(src, url, True)
        assert "h1.missing" not in _codes(src, url)

    def test_non_200_status_never_fires(self):
        url = "https://demo.test/gone"
        src = static_html(h1=None)
        assert "h1.missing" not in _codes(src, url, status_code=404)


# --------------------------------------------------------------------------
# link.noanchor
# --------------------------------------------------------------------------


class TestLinkNoAnchorStillFires:
    """⚠️ **核对结论：ocw.mit.edu 那 96 条**需要跨文件改**才能真修，
    本轮没有动这条规则，也没有越界改提取层。**

    实跑证据（curl https://ocw.mit.edu/ + lxml 解析 887 个 <a>）：
      文本为空的 <a> 共 114 个，其中
        - 114 个内部包着 <img>
        -  96 个带 aria-hidden="true" 且 tabindex="-1"（故意对用户和
          辅助技术隐藏的装饰/懒加载链接）
        -  96 个的 <img alt=""> 为空
        - 纯文本为空（不含 img/svg）的：**0 个**
    也就是说这批「空锚文本」不是 `<a href></a>` 那种真·无锚文本，
    而是被 aria-hidden + tabindex="-1 藏起来的图片链接。报它等于让用户
    去改本来正确的装饰性标记。

    提取层的 `_anchor_text` 本身没问题——它已经依次回退
    img[alt] → aria-label → title → data-title，并对嵌套子元素的
    aria-label 做过修复。问题在于这里 alt/aria-label **本来就没有值**，
    而「这个链接是否对用户可见」这条事实没有被记录到 LinkRef 上
    （LinkRef 只有 href/anchor/kind/nofollow/target_status）。

    真修需要：LinkRef 增加 visible/decorative 字段（models.py）+ 
    提取层回填（extract.py）。两个文件都不在我的独占范围内，
    按纪律如实上报，不越界改。

    本文件因此只锁住「真·空锚文本仍要报」这个反向用例。
    """

    def test_genuine_empty_anchors_still_fire(self):
        """`<a href="/x"></a>` 形式的真·空锚文本照报。"""
        src = (
            static_html()
            + '<a href="/a"></a><a href="/b"></a>'
        )
        codes, issues = audit_one(src, "https://demo.test/")
        assert "link.noanchor" in codes

    def test_single_empty_anchor_does_not_fire(self):
        """单条空锚仍按原逻辑放过（可能是无害 UI 元素）。"""
        src = static_html() + '<a href="/only-one"></a>'
        assert "link.noanchor" not in _codes(src, "https://demo.test/")

    def test_anchor_with_text_does_not_fire(self):
        src = static_html() + '<a href="/a">有锚文本</a><a href="/b">也有</a>'
        assert "link.noanchor" not in _codes(src, "https://demo.test/")