"""canonical 常见等价写法的识别与降级。

每条用例都来自 reports/fp_json_v5 里 canonical.conflict 的真实 URL，
不是凭空编的形状。
"""

from __future__ import annotations

import pytest

from app.audit.rules.base import (
    _BENIGN_VARIANT_REASONS,
    _benign_canonical_variant,
)


class TestQueryDropped:
    """canonical 剥掉查询参数 —— 真实站点最常见的一类。"""

    @pytest.mark.parametrize(
        "current,canonical",
        [
            ("https://www.pagerduty.com/?page_id=36859", "https://www.pagerduty.com/"),
            ("https://www.paypal.com/us/home?locale.x=en_US", "https://www.paypal.com/us/home"),
            ("https://www.elastic.co/r/x?plcmt=a&cta=b", "https://www.elastic.co/r/x"),
            (
                "https://bowers.cornell.edu/programs?department=15&sort_bef_combine=title_ASC",
                "https://bowers.cornell.edu/programs",
            ),
            ("https://www.indiehackers.com/sign-in?next=%2Fproducts%2Fnew", "https://www.indiehackers.com/sign-in"),
            ("https://www.fotocasa.es/es/login?skipRedirect=true", "https://www.fotocasa.es/es/login"),
        ],
    )
    def test_query_dropped(self, current, canonical):
        assert _benign_canonical_variant(current, canonical) == "query_dropped"

    def test_query_added_by_canonical_is_also_benign(self):
        """反过来也一样：canonical 带了本页没有的参数，不是权重转移。"""
        assert (
            _benign_canonical_variant("https://ex.com/a", "https://ex.com/a?utm_source=x")
            == "query_dropped"
        )


class TestIndexOrHomeAlias:
    """站点自己的索引别名：/index、/home、/default 指向同一页。"""

    @pytest.mark.parametrize(
        "current,canonical",
        [
            ("https://www.cs.cmu.edu/", "https://www.cs.cmu.edu/index"),
            ("https://www.cs.cmu.edu/partnerships/", "https://www.cs.cmu.edu/partnerships/index"),
            ("https://www.cs.umd.edu/", "https://www.cs.umd.edu/home"),
            ("https://www.purdue.edu/", "https://www.purdue.edu/home/"),
            ("https://www.purdue.edu/", "https://www.purdue.edu/default.html"),
            ("https://www.who.int/europe/home?v=welcome", "https://www.who.int/europe"),
        ],
    )
    def test_alias(self, current, canonical):
        assert _benign_canonical_variant(current, canonical) == "index_or_home_alias"

    def test_middle_segment_index_is_not_an_alias(self):
        """只在**结尾**才算别名。中间的 /index/ 是真路径的一部分。"""
        assert (
            _benign_canonical_variant("https://ex.com/index/about/", "https://ex.com/about/")
            is None
        )

    def test_word_ending_in_index_is_not_an_alias(self):
        """整段匹配：/myindex 不能被当成 /my + index 折叠。

        这是我写这个函数时最可能写错的一处 —— 用 endswith 而不是
        整段判断，会把两页真正不同的内容判成同一页。
        """
        assert _benign_canonical_variant("https://ex.com/myindex", "https://ex.com/my") is None

    def test_index_alias_must_not_swallow_different_paths(self):
        assert (
            _benign_canonical_variant("https://ex.com/blog/index", "https://ex.com/shop/index")
            is None
        )


class TestPdfVariant:
    def test_pdf_variant(self):
        assert (
            _benign_canonical_variant(
                "https://www.nature.com/articles/s41387-026-00465-3",
                "https://www.nature.com/articles/s41387-026-00465-3.pdf",
            )
            == "pdf_variant"
        )

    def test_pdf_of_a_different_article_is_not_benign(self):
        """同名不同号的文章不能被 PDF 变体规则放行。"""
        assert (
            _benign_canonical_variant(
                "https://www.nature.com/articles/s41387-026-00465-3",
                "https://www.nature.com/articles/s41387-026-99999-9.pdf",
            )
            is None
        )

    def test_pdf_with_different_host_is_not_benign(self):
        assert (
            _benign_canonical_variant("https://ex.com/a", "https://cdn.ex.com/a.pdf") is None
        )


class TestLangPrefix:
    @pytest.mark.parametrize(
        "current,canonical",
        [
            (
                "https://www.hetzner.com/de/cloud/general-purpose/",
                "https://www.hetzner.com/cloud/general-purpose/",
            ),
            ("https://www.naaptol.com/ro/print.html", "https://www.naaptol.com/print"),
            ("https://www.naaptol.com/ro/tv.html", "https://www.naaptol.com/tv"),
            ("https://ex.com/zh-CN/docs/guide", "https://ex.com/docs/guide"),
        ],
    )
    def test_lang_prefix(self, current, canonical):
        assert _benign_canonical_variant(current, canonical) == "lang_prefix"

    def test_two_letter_dir_alone_is_not_a_lang_prefix(self):
        """只有一段时不剥语言前缀。

        否则 /de 和 /fr 都会塌成 /，两个不同页面被判成同一页 ——
        这是最危险的一种折叠，它会**漏报真冲突**。
        """
        assert _benign_canonical_variant("https://ex.com/de", "https://ex.com/fr") is None

    def test_lang_prefix_must_not_hide_different_tail(self):
        assert (
            _benign_canonical_variant("https://ex.com/de/cloud/a", "https://ex.com/cloud/b") is None
        )

    def test_looks_like_lang_but_is_longer(self):
        """/products 不是语言前缀（7 字母）。"""
        assert _benign_canonical_variant("https://ex.com/products/a", "https://ex.com/a") is None


class TestRealConflictsStillReported:
    """这些必须继续报 —— 降级不能把真 bug 一起放行。"""

    def test_path_migration_is_still_a_conflict(self):
        """fotocasa 的真实样本：整段路径换了位置，是内容合并。"""
        assert (
            _benign_canonical_variant(
                "https://www.fotocasa.es/es/hipotecas/calculadora-hipotecas/",
                "https://www.fotocasa.es/es/calculadora-hipotecas/",
            )
            is None
        )

    def test_cross_domain_is_still_a_conflict(self):
        assert (
            _benign_canonical_variant("https://ex.com/a", "https://other.com/a") is None
        )

    def test_completely_unrelated_paths(self):
        assert _benign_canonical_variant("https://ex.com/a", "https://ex.com/b") is None


class TestReasonTextsExist:
    def test_every_returned_key_has_an_explanation(self):
        """规则会把 verdict 写进 evidence 给人看。

        漏了说明就会在报告里出现一个光秃秃的 key，用户看不懂。
        """
        assert set(_BENIGN_VARIANT_REASONS) == {
            "query_dropped",
            "index_or_home_alias",
            "pdf_variant",
            "lang_prefix",
        }
