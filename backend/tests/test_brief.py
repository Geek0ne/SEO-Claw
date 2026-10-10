"""内容 Brief 生成测试。

Brief 是给用户**照着做**的，所以这里的断言主线是「不许把不知道的事写成知道」：

- 竞品正文本工具没抓 → 绝不能出现「Top10 平均正文 N 字」这类结论
- 搜索量没有数据源 → 绝不能填数字
- 每条差异化机会 → 必须附证据，没有证据就不该出现
- 数据不足时字段保持 None/空 + 写明「拿不到」，不用默认值填坑
"""

from __future__ import annotations

from seoclaw.brief import (
    PageSignal,
    SerpEntry,
    analyze_serp_titles,
    build_title_candidates,
    generate_brief,
    kw_in_page,
    own_length_baseline,
)
from seoclaw.db.models import Intent, Market


def _serp():
    """5 条 SERP，覆盖三种修饰类型。"""
    return [
        SerpEntry(1, "https://a.com/1", "seo优化怎么做 - A站", snippet="从零开始"),
        SerpEntry(2, "https://b.com/2", "seo优化怎么做?完整教程", snippet="分步骤"),
        SerpEntry(3, "https://c.com/3", "SEO优化价格与收费标准", snippet="明码标价"),
        SerpEntry(4, "https://d.com/4", "seo优化怎么做 2024", snippet="实操"),
        SerpEntry(5, "https://e.com/5", "seo优化哪家好 对比", snippet="五家对比"),
    ]


def _own():
    return [
        PageSignal("https://mine.com/", "首页", ["首页"], 120),
        PageSignal("https://mine.com/seo", "SEO优化怎么做", ["SEO优化怎么做"], 2600),
        PageSignal("https://mine.com/blog", "博客", ["博客"], 1800),
    ]


# --------------------------------------------------------------------------
# ⚠️ 诚实边界：本工具只抓了竞品标题/摘要，没抓正文
# --------------------------------------------------------------------------


def test_never_claims_competitor_body_length():
    """⚠️ 本工具没存竞品正文，任何「竞品平均字数」都是编的。

    serp_snapshots 存的是 url/title/snippet/features，没有正文。
    报一个「Top10 平均 1800 字」会让用户去追一个我验证不了的数字。
    """
    b = generate_brief(
        "seo优化", target_url="https://mine.com/new",
        serp_entries=_serp(), own_pages=_own(),
    )
    d = b.as_dict()
    blob = str(d)
    assert "competitor_body" not in blob
    # not_available 必须明说这一项
    joined = " ".join(d["not_available"])
    assert "竞品正文" in joined


def test_length_baseline_declares_own_pages_source():
    """字数基线必须标明来源是自家页面，不能让人误以为是竞品数据。"""
    b = generate_brief(
        "seo优化", target_url="https://mine.com/new",
        serp_entries=_serp(), own_pages=_own(),
    )
    base = b.own_length_baseline
    assert base["available"] is True
    assert base["source"] == "own_pages"
    assert "竞品" in base["note"]


def test_no_length_baseline_when_pages_have_no_text():
    """自家页面也没有正文长度时，必须说 unavailable 而不是给个假中位数。"""
    base = own_length_baseline([PageSignal("https://x/", "t")])
    assert base["available"] is False
    assert "median" not in base
    assert base["reason"]


def test_not_available_lists_everything_we_cannot_know():
    b = generate_brief("seo优化", target_url="https://mine.com/new")
    joined = " ".join(b.not_available)
    for kw in ("搜索量", "排名", "正文"):
        assert kw in joined, f"「拿不到」清单里应写明 {kw}"


# --------------------------------------------------------------------------
# SERP 标题层分析
# --------------------------------------------------------------------------


def test_serp_analysis_is_title_level_only():
    """⚠️ 标题层统计必须自我标注，否则会被当成「分析了竞品页面」。"""
    out = analyze_serp_titles(_serp())
    assert out["available"] is True
    assert out["titles_analyzed"] == 5
    assert "标题" in out["note"]
    assert "标题" in out["note"]


def test_serp_analysis_unavailable_when_no_titles():
    out = analyze_serp_titles([SerpEntry(1, "https://a.com/1")])
    assert out["available"] is False
    assert out["reason"]


def test_modifier_counts_are_evidence_backed():
    out = analyze_serp_titles(_serp())
    for tag, info in out["modifiers"].items():
        assert info["count"] >= 1, f"{tag} 没有任何标题支撑却出现在统计里"
        assert 0 < info["ratio"] <= 1


# --------------------------------------------------------------------------
# 机会：每条都要有证据
# --------------------------------------------------------------------------


def test_every_opportunity_carries_evidence():
    """⚠️ 没有证据的「机会」就是让用户去瞎改页面。"""
    b = generate_brief(
        "seo优化", target_url="https://mine.com/new2",
        intent=Intent.INFORMATIONAL, serp_entries=_serp(), own_pages=_own(),
    )
    assert b.opportunities, "这份样本应能产出机会"
    for o in b.opportunities:
        assert o.get("evidence"), f"{o['kind']} 没有证据"
        assert o.get("caveat"), f"{o['kind']} 没有写清局限"


def test_underused_modifier_only_when_top10_skips_it():
    """Top10 普遍在用的维度不算「机会」——那是基本要求，不是差异点。"""
    # 全是教程型标题 → 教程型不应被列为 underused
    entries = [
        SerpEntry(i, f"https://x{i}.com", f"seo优化教程 {i}") for i in range(1, 6)
    ]
    b = generate_brief(
        "seo优化", target_url="https://mine.com/n3", serp_entries=entries
    )
    kinds = [o for o in b.opportunities if o["kind"] == "underused_modifier"]
    titles = " ".join(o["title"] for o in kinds)
    assert "教程型" not in titles, "Top10 全在用教程型，不该说这是机会"


def test_opportunities_empty_without_serp_data():
    """没有 SERP 快照时不该编机会。"""
    b = generate_brief("seo优化", target_url="https://mine.com/n4")
    assert [o for o in b.opportunities if o["kind"] != "already_ranked"] == []


# --------------------------------------------------------------------------
# 页型与意图
# --------------------------------------------------------------------------


def test_page_type_from_intent():
    """页型是硬知识，四种意图都要有对应形态。"""
    for intent in (Intent.INFORMATIONAL, Intent.COMMERCIAL,
                   Intent.TRANSACTIONAL, Intent.NAVIGATIONAL):
        b = generate_brief("k", target_url="https://mine.com/p", intent=intent)
        assert b.page_type and "未分类" not in b.page_type


def test_page_type_says_unclassified_when_no_intent():
    """没判定意图就说没判定，不能默认一个。"""
    b = generate_brief("k", target_url="https://mine.com/p")
    assert "未分类" in b.page_type


# --------------------------------------------------------------------------
# 已在竞争这个词 → 是优化不是新建
# --------------------------------------------------------------------------


def test_existing_page_flagged_as_already_ranked():
    """⚠️ 同站多页竞争同一词会互相稀释权重，必须先说「优化已有页面」。"""
    b = generate_brief(
        "seo优化", target_url="https://mine.com/seo3",
        serp_entries=_serp(), own_pages=_own(),
    )
    first = b.opportunities[0]
    assert first["kind"] == "already_ranked"
    assert "https://mine.com/seo" in first["evidence"]["urls"]
    assert "稀释" in first["caveat"]


def test_kw_in_page_is_conservative():
    """只在正文提一次不算「在竞争」——太松会把一堆页面都算进来。"""
    # 标题/H1 完全不含，只有这个字段存在
    p = PageSignal("https://mine.com/x", "关于我们", ["关于我们"], 800)
    assert kw_in_page("seo优化", p) is False
    p2 = PageSignal("https://mine.com/y", "SEO优化怎么做", ["SEO优化怎么做"], 900)
    assert kw_in_page("seo优化", p2) is True


# --------------------------------------------------------------------------
# 标题候选
# --------------------------------------------------------------------------


def test_title_candidates_lead_with_page_type_intent():
    """商业/交易意图下，标题形态必须跟着意图走。"""
    commercial = build_title_candidates("选购", Intent.COMMERCIAL, "shop.com")
    transactional = build_title_candidates("购买", Intent.TRANSACTIONAL, "shop.com")
    assert "对比" in commercial[0]
    assert "价格" in transactional[0]


def test_title_candidates_always_include_keyword():
    for intent in Intent:
        for c in build_title_candidates("核心词", intent, "site.com"):
            assert "核心词" in c


def test_no_title_candidate_invents_search_volume():
    """候选标题不许出现「搜索量 XX 万」这种编造。"""
    for c in build_title_candidates("词", Intent.INFORMATIONAL, "s.com"):
        assert "万搜索" not in c and "月搜" not in c


# --------------------------------------------------------------------------
# 空输入
# --------------------------------------------------------------------------


def test_brief_with_no_data_is_still_valid():
    """⚠️ 什么都没查到时也要能出 brief，只是各项为空 + 说明拿不到。

    这是「不给结论」和「假装有结论」的分界。
    """
    b = generate_brief("关键词", target_url="https://mine.com/empty")
    d = b.as_dict()
    assert d["keyword"] == "关键词"
    assert d["serp_common"]["available"] is False
    assert d["own_length_baseline"]["available"] is False
    assert len(d["not_available"]) >= 3
    assert d["title_candidates"], "即使没数据也该给标题方向"


def test_brief_json_serializable():
    """要能直接进 JSON 列（content_briefs.brief）。"""
    import json

    b = generate_brief(
        "seo优化", target_url="https://mine.com/j",
        market=Market.GOOGLE, intent=Intent.INFORMATIONAL,
        serp_entries=_serp(), own_pages=_own(),
    )
    payload = json.dumps(b.as_dict(), ensure_ascii=False)
    assert json.loads(payload)["keyword"] == "seo优化"