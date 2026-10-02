"""关键词扩展与聚类测试。

这两层的产出是**给用户做决策用的**，所以测试重点不是「能跑」，
而是「不许把没把握的东西说得像有把握」：

- volume 缺失必须是 None，不是 0（0 会让用户放弃一个其实有量的词）
- 形态变体没有语料证据，必须低分且证据为空（`多少钱优化` 这种读着别扭的
  组合绝不能混进高置信候选里）
- 聚类必须给出「合并依据」，让用户能核对，而不是只丢一个相似度数字
- 聚类结果必须与输入顺序无关（并查集的意义就在这）
"""

from __future__ import annotations

import pytest

from app.keywords import (
    cluster,
    cosine,
    expand,
    ngram_candidates,
    shared_ngrams,
    tokenize,
)


def _pages():
    """3 页 SEO 语料 + 2 页无关语料。

    无关语料是**故意的**：没有它的话，全站都在出现的泛词
    （「产品」「服务」）会凭共现次数冲到候选表最前面。
    """
    return [
        ("https://s.test/a", "seo优化怎么做 seo优化技巧 seo优化指南"),
        ("https://s.test/b", "seo优化怎么做 wordpress建站 seo优化技巧"),
        ("https://s.test/c", "seo优化技巧 内容运营 seo优化"),
        ("https://s.test/d", "产品服务 产品说明 服务中心"),
        ("https://s.test/e", "产品中心 服务条款 产品评测"),
    ]


# --------------------------------------------------------------------------
# tokenize
# --------------------------------------------------------------------------


def test_tokenize_lowercases_latin():
    """SEO 和 seo 必须是同一个词 —— 不归一会让同一个词在库里出现两次。"""
    assert "seo" in tokenize("SEO 优化")


def test_tokenize_drops_stopwords_but_keeps_searchable_words():
    toks = tokenize("我们的产品价格是多少")
    assert "的" not in toks and "了" not in toks
    # 停用词表绝不能吃掉这些 —— 它们正是用户会搜的实词
    for keep in ("价格", "产品"):
        assert keep in toks, f"停用词表误伤了 {keep}"


def test_tokenize_drops_digits_and_single_letters():
    assert tokenize("2026 a seo") == ["seo"]


def test_tokenize_empty_is_safe():
    assert tokenize("") == []
    assert tokenize(None) == []


# --------------------------------------------------------------------------
# expand — 共现
# --------------------------------------------------------------------------


def test_cooccurrence_finds_real_neighbours():
    cands = expand(["seo优化"], _pages(), min_pages=2)
    terms = {c.term for c in cands}
    assert "技巧" in terms, f"「技巧」在 3 个页面与种子共现，应被发现：{terms}"


def test_candidates_carry_evidence_urls():
    """⚠️ 证据是这一层的核心价值 —— 用户要能点开核对。"""
    cands = expand(["seo优化"], _pages(), min_pages=2)
    top = [c for c in cands if c.term == "技巧"]
    assert top, "应产出「技巧」"
    assert top[0].evidence_urls, "候选必须带可点击的证据 URL"
    assert all(u.startswith("https://") for u in top[0].evidence_urls)


def test_min_pages_gate_rejects_single_page_words():
    """只在一个页面出现的词，多半是那页的专有名词，不是站点级机会。"""
    pages = [
        ("https://s.test/a", "seo优化 zzz罕见词"),
        ("https://s.test/b", "seo优化 别的内容"),
    ]
    cands = expand(["seo优化"], pages, min_pages=2)
    assert "zzzz罕见词" not in {c.term for c in cands}


def test_generic_words_do_not_outrank_specific_ones():
    """⚠️ PMI 而非裸计数：裸计数会把「全站都在」的泛词排到最前。

    「产品」在语料里出现多次，但它是泛词 —— 拿它当关键词机会
    是把用户引向一个没有商业价值的方向。
    """
    pages = _pages()
    cands = expand(["seo优化"], pages, min_pages=2)
    order = [c.term for c in cands if c.source == "cooccurrence"]
    if "产品" in order and "技巧" in order:
        assert order.index("技巧") < order.index("产品"), (
            f"具体词应排在泛词前，实际顺序：{order}"
        )


def test_volume_is_none_not_zero():
    """⚠️ 0 表示「搜索量真的是 0」，会让用户放弃一个其实有量的词。"""
    cands = expand(["seo优化"], _pages(), min_pages=2)
    assert all(c.volume is None for c in cands), "没有付费数据源就不许编 volume"


# --------------------------------------------------------------------------
# expand — 形态变体
# --------------------------------------------------------------------------


def test_morphology_variants_are_low_confidence_and_evidence_free():
    """形态变体靠「改个说法往往同义」，没有语料支撑。

    所以必须固定低分 + 证据为空 —— 像 `多少钱优化` 这种读着别扭的组合，
    一旦混进高置信候选，用户会照着做，发现不好用就会不再信任整个功能。
    """
    cands = expand(["seo优化"], _pages(), min_pages=2)
    morph = [c for c in cands if c.source == "morphology"]
    for c in morph:
        assert c.score <= 0.5, f"{c.term} 无语料支撑，不该高过共现候选"
        assert c.evidence_urls == [], f"{c.term} 没有语料证据，不该带 URL"


def test_morphology_never_outranks_cooccurrence():
    cands = expand(["seo优化"], _pages(), min_pages=2)
    co = [c for c in cands if c.source == "cooccurrence"]
    morph = [c for c in cands if c.source == "morphology"]
    if co and morph:
        assert min(c.score for c in co) >= max(c.score for c in morph)


def test_empty_corpus_returns_nothing():
    assert expand(["seo优化"], [], min_pages=2) == []


# --------------------------------------------------------------------------
# ngram
# --------------------------------------------------------------------------


def test_ngram_requires_cross_page_occurrence():
    """⚠️ 单页高频词组（导航条「首页 关于我们」）全靠这条挡住。"""
    pages = [("https://s.test/a", "seo优化怎么做"), ("https://s.test/b", "内容运营")]
    grams = ngram_candidates(pages, n=2, min_pages=2, min_df_ratio=0.1)
    assert not [g for g in grams if "怎么做" in g.term]


def test_ngram_finds_shared_phrase():
    pages = [
        ("https://s.test/a", "seo优化技巧"),
        ("https://s.test/b", "seo优化技巧"),
    ]
    grams = ngram_candidates(pages, n=2, min_pages=2, min_df_ratio=0.5)
    assert [g.term for g in grams], "跨页共现的短语应被挖出"


# --------------------------------------------------------------------------
# cluster
# --------------------------------------------------------------------------


def test_similar_terms_cluster_together():
    cs, _ = cluster(["seo优化", "SEO优化技巧", "wordpress建站"], threshold=0.35)
    sizes = sorted(len(c.terms) for c in cs)
    assert sizes[-1] >= 2, f"近义词应聚成一簇，实际：{[c.terms for c in cs]}"
    assert ["wordpress建站"] in [c.terms for c in cs], "无关词不该被拉进去"


def test_cluster_is_case_insensitive():
    cs, _ = cluster(["SEO优化", "seo优化技巧"], threshold=0.35)
    assert len(cs) == 1, "大小写不同不该阻止聚类"


def test_every_merge_carries_checkable_evidence():
    """⚠️ 只给「相似度 0.87」的话用户无从核对；必须给出共享了哪些 n-gram。"""
    _, ev = cluster(["seo优化", "seo优化技巧"], threshold=0.35)
    assert ev, "合并必须留下依据"
    for e in ev:
        assert e.shared_ngrams, f"{e.a}~{e.b} 合并却没有共享片段，无法核对"
        assert 0.0 <= e.similarity <= 1.0


def test_cluster_result_is_order_independent():
    """⚠️ 单趟遍历合并有顺序依赖：A~B 合了、B~C 没合，A 和 C 就永远合不到。

    所以用并查集。这条测试就是钉死那个 bug 不许回来。
    """
    terms = ["seo优化", "seo优化技巧", "seo优化指南", "seo优化怎么做"]
    a, _ = cluster(terms, threshold=0.30)
    b, _ = cluster(list(reversed(terms)), threshold=0.30)
    assert sorted(sorted(c.terms) for c in a) == sorted(sorted(c.terms) for c in b), (
        "聚类结果不应随输入顺序变化"
    )


def test_no_evidence_when_nothing_merges():
    terms = ["aaa", "bbb", "ccc"]
    _, ev = cluster(terms, threshold=0.99)
    assert ev == [], "不该合并时也不该编造依据"


def test_oversized_cluster_gets_split():
    """超大簇几乎一定是阈值太低 —— 宁可拆开，也不要给「全都在一簇」。"""
    many = [f"seo优化技巧{i}" for i in range(30)]
    cs, _ = cluster(many, threshold=0.01, max_cluster_size=5)
    assert all(len(c.terms) <= 5 for c in cs), "超限簇必须拆开"


def test_representative_is_the_most_complete_term():
    cs, _ = cluster(["seo优化技巧", "seo优化"], threshold=0.30)
    group = next(c for c in cs if len(c.terms) > 1)
    assert group.representative == max(group.terms, key=len)


def test_empty_input_is_safe():
    assert cluster([]) == ([], [])
    assert cluster(["", "  "]) == ([], [])


# --------------------------------------------------------------------------
# 语义聚类接口位
# --------------------------------------------------------------------------


def test_embed_fn_slot_raises_clearly():
    """⚠️ 必须**明确报错**，不能静默退回词形聚类。

    静默退回 = 用户以为拿到了语义聚类，实际是词形的，
    而结果他无从分辨 —— 这跟「把没做当做了」是同一类错。
    """
    with pytest.raises(NotImplementedError) as e:
        cluster(["a", "b"], embed_fn=lambda terms: [[0.0, 1.0]])
    msg = str(e.value)
    assert "API key" in msg and "embed_fn" in msg


def test_cosine_and_shared_ngrams_are_exposed():
    """这两个函数被测试直接使用 —— 锁住公开接口，防止重构时静默改名。"""
    assert cosine({}, {}) == 0.0
    assert shared_ngrams({"a": 1.0}, {}) == []