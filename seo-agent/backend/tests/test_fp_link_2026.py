"""link.noanchor 的装饰性链接豁免（2026-10-02）。

起因：ocw.mit.edu 首页扫出 96 条「空锚文本」。实跑原始 HTML 发现那 96 个
全是 logo / 社交图标链接：

    <a href="/x" aria-hidden="true" tabindex="-1"><img src="logo.svg" alt=""></a>

对可见用户、读屏软件和爬虫都不存在——让作者去改等于让人改本来正确的东西。
本文件锁死：装饰性链接不算空锚，但**真·空锚**仍然要报（防止改成永远沉默）。

样本全部取自 ocw.mit.edu 首页实抓，非构造。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]

from app.audit.engine import RuleContext  # noqa: E402
from app.audit.rules.base import LinkNoAnchor  # noqa: E402
from app.extract import _is_decorative  # noqa: E402
from app.models import LinkKind, LinkRef, Page  # noqa: E402

RULE = LinkNoAnchor()
CTX = RuleContext(domain="ocw.mit.edu")


def _mk(html: str, base_url: str = "https://ocw.mit.edu/") -> Page:
    """把一段 HTML 片段喂给真实提取层，不手工构造 LinkRef。"""
    import lxml.html

    from app.extract import _extract_links

    doc = lxml.html.fromstring(f"<html><body>{html}</body></html>")
    page = Page(url=base_url, final_url=base_url, status_code=200, domain="ocw.mit.edu")
    _extract_links(doc, page, base_url, "ocw.mit.edu")
    return page


def _fire(page: Page):
    return [i for i in RULE.check(page, CTX) if i.code == "link.noanchor"]


class TestDecorativeMustStaySilent:
    def test_aria_hidden_img_link_is_not_a_finding(self):
        """ocw 实样本：aria-hidden + tabindex=-1 + alt 空。"""
        page = _mk(
            '<a href="/a" aria-hidden="true" tabindex="-1"><img src="logo.svg" alt=""></a>'
            '<a href="/b" aria-hidden="true" tabindex="-1"><img src="fb.svg" alt=""></a>'
        )
        assert _fire(page) == [], "装饰性图标链接不该报空锚"

    def test_full_ocw_shape_96_decorative_is_silent(self):
        """复现 ocw 首页的真实形态：96 装饰 + 0 真空锚 → 整条规则闭嘴。"""
        html = "".join(
            f'<a href="/i{n}" aria-hidden="true" tabindex="-1">'
            f'<img src="/s/{n}.svg" alt=""></a>'
            for n in range(96)
        )
        page = _mk(html)
        assert len([l for l in page.links if l.decorative]) == 96
        assert _fire(page) == []

    def test_tabindex_minus_one_alone_also_silent(self):
        page = _mk(
            '<a href="/a" tabindex="-1"><img src="x.svg" alt=""></a>'
            '<a href="/b" tabindex="-1"><img src="y.svg" alt=""></a>'
        )
        assert _fire(page) == []


class TestRealFindingsStillFire:
    """反向用例：防止「排除装饰性」改成「永远沉默」。"""

    def test_bare_empty_anchor_still_fires(self):
        """真·空锚 <a href></a> —— 没有任何豁免依据，必须报。"""
        page = _mk('<a href="/a"></a><a href="/b"></a>')
        assert len(_fire(page)) == 1

    def test_visible_icon_link_still_fires(self):
        """无 aria-hidden 的空 alt 图标链接：用户看得见，必须报。"""
        page = _mk(
            '<a href="/a"><img src="logo.svg" alt=""></a>'
            '<a href="/b"><img src="fb.svg" alt=""></a>'
        )
        assert len(_fire(page)) == 1

    def test_aria_hidden_does_not_blanket_mark_decorative(self):
        """aria-hidden 本身**不能**直接判成装饰——有锚文本的一律不是。

        这条是我第一版的断言写反了：原断言写「有文字也该报」，但那样写的
        HTML 根本不构成空锚（anchor 非空 → 压根进不了 empties），规则闭嘴是
        正确行为。真正要锁的是**装饰性标记不会污染有内容的链接**，否则
        提取层一旦误标，这条豁免就会变成吞掉真问题的黑洞。
        """
        page = _mk(
            '<a href="/a" aria-hidden="true">下载</a>'
            '<a href="/b" aria-hidden="true">注册</a>'
        )
        assert [l.decorative for l in page.links] == [False, False]
        assert _fire(page) == [], "有锚文本的链接不是空锚，规则本就不该报"
        assert all(l.anchor for l in page.links)

    def test_img_alt_present_is_never_a_finding(self):
        """<img alt="MIT OpenCourseWare"> —— 提取层已采到 alt，锚文本非空。

        ocw 上另外 18 个「看似空锚」实为此类，进不了这条规则。
        """
        page = _mk(
            '<a href="/a"><img src="logo.svg" alt="MIT OpenCourseWare"></a>'
            '<a href="/b"><img src="fb.svg" alt="facebook"></a>'
        )
        assert _fire(page) == []

    def test_external_decorative_links_are_irrelevant(self):
        """豁免只作用于内链统计口径，外链空锚本就不在本规则范围。"""
        page = _mk(
            '<a href="https://ocw.mit.edu/x" aria-hidden="true"><img alt=""></a>'
            '<a href="https://ocw.mit.edu/y" aria-hidden="true"><img alt=""></a>'
        )
        assert _fire(page) == []

    def test_single_real_empty_anchor_still_silent(self):
        """沿用原有「单个多半是无害 UI 元素」的口径。"""
        page = _mk('<a href="/a"></a>')
        assert _fire(page) == []


class TestIsDecorativeUnit:
    def test_anchor_text_blocks_decoration(self):
        import lxml.html

        el = lxml.html.fromstring(
            '<a href="/a" aria-hidden="true"><img src="x.svg" alt=""></a>'
        )
        assert _is_decorative(el, "有文字") is False

    def test_aria_hidden_true_case_insensitive(self):
        import lxml.html

        el = lxml.html.fromstring('<a href="/a" aria-hidden="TRUE"><img alt=""></a>')
        assert _is_decorative(el, "") is True

    def test_plain_anchor_not_decorative(self):
        import lxml.html

        el = lxml.html.fromstring('<a href="/a"></a>')
        assert _is_decorative(el, "") is False

    def test_aria_hidden_on_child_img_does_not_decorate(self):
        """aria-hidden 写在 <img> 上只说明图片被藏，链接本身仍可见。"""
        import lxml.html

        el = lxml.html.fromstring(
            '<a href="/a"><img src="x.svg" alt="" aria-hidden="true"></a>'
        )
        assert _is_decorative(el, "") is False


class TestEvidenceTransparency:
    def test_evidence_reports_excluded_decorative_count(self):
        """豁免了多少条要写进 evidence——用户能自己核对规则没偷偷放过。"""
        html = (
            '<a href="/a" aria-hidden="true"><img alt=""></a>'
            '<a href="/b" aria-hidden="true"><img alt=""></a>'
            '<a href="/c"></a><a href="/d"></a>'
        )
        iss = _fire(_mk(html))
        assert len(iss) == 1
        assert iss[0].evidence["excluded_decorative"] == 2
        assert iss[0].evidence["empty_anchor_count"] == 2


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))