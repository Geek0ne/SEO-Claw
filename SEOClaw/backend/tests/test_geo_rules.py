"""GEO / AI 搜索可引用性规则包测试。

PLAN 的 #14 标注了「需先做方法论验证」。这个包的定位由此而来：
**只实现结构上真能查的判断，其余全部记录在模块 docstring 的「不实现」一节**。

所以这里的断言主线不是「规则能触发」，而是三条更重要的：

1. **默认注册表绝不能加载 GEO** —— base 39 条刚在 107 站验到 97.0%
   严格准确率，GEO 的证据强度远不如它，混进去会污染基线。
2. **JS 壳页面必须全部沉默** —— 4 条规则全靠「没看到 X」下结论，
   而静态壳里「没看到」只说明 X 是 JS 注入的。这正是 base 包在
   agoda 上踩过的坑（title.missing / h1.missing 都栽在这）。
3. **绝不声称能预测 AI 引用率** —— 没有公开依据的结论不出现在输出里。
"""

from __future__ import annotations

import pytest

from seoclaw.audit.engine import RuleContext, RuleRegistry, _import_rules, default_registry
from seoclaw.audit.rules.geo import (
    FaqStructureMismatch,
    FlatStructure,
    NoOutboundReferences,
    NoQuestionHeadings,
)
from seoclaw.models import Page

GEO_CODES = {
    "geo.no_question_headings",
    "geo.no_outbound_references",
    "geo.flat_structure",
    "geo.faq_structure_mismatch",
}


@pytest.fixture(scope="module")
def geo_rules() -> dict:
    reg = RuleRegistry()
    reg.load_module_rules(_import_rules("geo"))
    return {r.code: r for r in reg._page_rules}


def _ctx() -> RuleContext:
    return RuleContext(domain="demo.test")


def _page(**kw) -> Page:
    """默认造一个「不该触发任何 GEO 规则」的干净页面。"""
    base = dict(
        url="https://demo.test/a",
        text="正文内容。" * 200,  # 600 字，够长
        word_count=600,
        is_html=True,
        status_code=200,
        headings=[(2, "我们是谁"), (2, "服务范围"), (2, "常见流程")],
        external_link_count=3,
    )
    base.update(kw)
    return Page(**base)


def _codes(issues) -> set[str]:
    return {i.code for i in issues}


# --------------------------------------------------------------------------
# 基线保护：GEO 默认不加载
# --------------------------------------------------------------------------


def test_geo_not_loaded_by_default():
    """⚠️ GEO 绝不能混进默认扫描。

    base 的 39 条刚在 107 个真实站点上验到 97.0% 严格准确率。
    GEO 这类「AI 搜索友好度」结论的证据强度远不如它，
    混进去会让好规则一起被拖下水。
    """
    reg = default_registry()
    all_codes = {r.code for r in reg._page_rules + reg._site_rules}
    assert all_codes & GEO_CODES == set(), f"默认注册表混入了 GEO：{all_codes & GEO_CODES}"
    assert len(all_codes) == 39, "基线规则数变了，说明有人动了 base 包"


def test_geo_loads_only_when_explicitly_requested():
    reg = RuleRegistry()
    reg.load_module_rules(_import_rules("geo"))
    assert {r.code for r in reg._page_rules} == GEO_CODES


# --------------------------------------------------------------------------
# JS 壳守卫：这是整个包最关键的一道防线
# --------------------------------------------------------------------------


def test_all_four_rules_silent_on_js_shell():
    """⚠️ 4 条规则全靠「没看到 X」下结论，静态壳里「没看到」推不出「没有」。

    真实教训：base 包的 title.missing / h1.missing 都在 agoda.com 上这样
    误报过 —— 那站 title 和 h1 都是 JS 注入的，静态 HTML 里确实找不到。
    GEO 这 4 条是同一类逻辑，必须共用同一道守卫。
    """
    shell = _page(
        likely_js_rendered=True,
        text="",  # JS 站静态正文极少
        word_count=5,
        headings=[],
        external_link_count=0,
        title="",
    )
    rules = [
        NoQuestionHeadings(), NoOutboundReferences(),
        FlatStructure(), FaqStructureMismatch(),
    ]
    for rule in rules:
        fired = list(rule.check(shell, _ctx()))
        assert fired == [], f"{rule.code} 在 JS 壳页面上误报了：{fired}"


def test_js_shell_guard_is_bounded_by_the_flag_itself():
    """⚠️ 守卫的作用域由 ``likely_js_rendered`` 自身定义封顶，不是我拍的。

    提取层判定该标记时要求 ``full_text_length < 300``（``extract.py``
    的 ``_JS_RENDERED_MAX_TEXT``），所以「JS 壳 + 600 字正文」这个组合
    **在真实数据里不存在** —— 我第一版测试就是这么写的，跑出来才发现
    自己造了一个不可能的样本，然后据此去改规则。

    守卫真正会压住的，是正文确实很少的壳页：
    ``word_count`` 是词数、``full_text_length`` 是字符数，两者不等价，
    所以 200~299 字符的中文页确实可能同时命中两者 —— 那种情况必须沉默。
    """
    # faq 规则门槛最低（200 词），正好落在标记可能成立的区间
    shell = _page(
        word_count=210,
        text="壳" * 280,  # 280 字符 < 300 → likely_js_rendered 可能为真
        title="常见问题",
        headings=[(2, "常见问题")],
        external_link_count=0,
        likely_js_rendered=True,
    )
    assert _codes(FaqStructureMismatch().check(shell, _ctx())) == set(), (
        "JS 壳页即使自称 FAQ 也必须沉默——问句可能由 JS 注入"
    )
    # 同一条规则、同样的页面，仅去掉标记就该报：证明守卫是标记驱动的
    not_shell = shell.model_copy(update={"likely_js_rendered": False})
    assert _codes(FaqStructureMismatch().check(not_shell, _ctx())) == {
        "geo.faq_structure_mismatch"
    }


# --------------------------------------------------------------------------
# geo.no_question_headings
# --------------------------------------------------------------------------


def test_question_headings_fires(geo_rules):
    """有 3 个小标题但没一个问句 → 报。"""
    page = _page(headings=[(2, "我们是谁"), (2, "服务范围"), (2, "常见流程")])
    issues = list(geo_rules["geo.no_question_headings"].check(page, _ctx()))
    assert _codes(issues) == {"geo.no_question_headings"}
    ev = issues[0].evidence
    assert ev["subheading_count"] == 3
    assert "不是" in ev["verdict_explain"] or "结构观察" in ev["verdict_explain"]


def test_question_headings_silent_when_any_is_a_question(geo_rules):
    page = _page(headings=[(2, "我们是谁"), (2, "怎么收费？"), (2, "常见流程")])
    assert _codes(geo_rules["geo.no_question_headings"].check(page, _ctx())) == set()


def test_question_headings_silent_when_no_subheadings(geo_rules):
    """没有小标题是 flat_structure 的职责，不重复报。"""
    page = _page(headings=[(1, "关于我们")])
    assert _codes(geo_rules["geo.no_question_headings"].check(page, _ctx())) == set()


def test_question_headings_silent_on_short_page(geo_rules):
    """短落地页不需要 FAQ 结构。"""
    page = _page(word_count=50, text="短。", headings=[(2, "简介")])
    assert _codes(geo_rules["geo.no_question_headings"].check(page, _ctx())) == set()


def test_question_headings_recognizes_cn_and_en(geo_rules):
    for h2 in ("怎么收费", "为什么选择我们", "How much does it cost", "What is included"):
        page = _page(headings=[(1, "x"), (2, h2), (2, "y")])
        assert _codes(geo_rules["geo.no_question_headings"].check(page, _ctx())) == set(), (
            f"「{h2}」应被认成问句式小标题"
        )


# --------------------------------------------------------------------------
# geo.flat_structure
# --------------------------------------------------------------------------


def test_flat_structure_fires(geo_rules):
    """800+ 字正文但小标题 ≤1 个 → 报。"""
    page = _page(word_count=900, headings=[(1, "长文"), (2, "一段话")])
    assert _codes(geo_rules["geo.flat_structure"].check(page, _ctx())) == {"geo.flat_structure"}


def test_flat_structure_silent_with_enough_headings(geo_rules):
    page = _page(word_count=900, headings=[(2, "a"), (2, "b"), (2, "c")])
    assert _codes(geo_rules["geo.flat_structure"].check(page, _ctx())) == set()


def test_flat_structure_silent_below_800(geo_rules):
    """799 字不该报 —— 阈值 800 是刻意的，不该随手放宽。"""
    page = _page(word_count=799, headings=[(1, "x")])
    assert _codes(geo_rules["geo.flat_structure"].check(page, _ctx())) == set()


def test_flat_structure_h1_does_not_count(geo_rules):
    """h1 是主标题，不算「切分」。只有 h1 不等于有结构。"""
    page = _page(word_count=900, headings=[(1, "只有 h1"), (1, "又一个 h1")])
    assert _codes(geo_rules["geo.flat_structure"].check(page, _ctx())) == {"geo.flat_structure"}


# --------------------------------------------------------------------------
# geo.no_outbound_references
# --------------------------------------------------------------------------


def test_no_outbound_fires(geo_rules):
    page = _page(external_link_count=0)
    assert _codes(geo_rules["geo.no_outbound_references"].check(page, _ctx())) == {
        "geo.no_outbound_references"
    }


def test_no_outbound_silent_when_links_exist(geo_rules):
    assert _codes(geo_rules["geo.no_outbound_references"].check(_page(), _ctx())) == set()


def test_no_outbound_does_not_claim_ranking_impact(geo_rules):
    """⚠️ 这条是内容可信度问题，不是排名问题，evidence 必须说清。"""
    page = _page(external_link_count=0)
    issue = list(geo_rules["geo.no_outbound_references"].check(page, _ctx()))[0]
    assert "不加分不减分" in issue.evidence["caveat"]


# --------------------------------------------------------------------------
# geo.faq_structure_mismatch：这是唯一一条「可能有意为之」的规则
# --------------------------------------------------------------------------


def test_faq_mismatch_fires(geo_rules):
    """自称 FAQ 却零问句 → 报。"""
    page = _page(
        word_count=400,
        title="常见问题",
        headings=[(2, "常见问题")],
        text="正文没有任何问号。" * 30,
    )
    issues = list(geo_rules["geo.faq_structure_mismatch"].check(page, _ctx()))
    assert _codes(issues) == {"geo.faq_structure_mismatch"}
    assert issues[0].evidence["body_question_marks"] == 0


def test_faq_mismatch_silent_when_questions_exist(geo_rules):
    """真问答结构 → 不报。"""
    page = _page(
        word_count=400,
        title="常见问题",
        headings=[(2, "怎么收费？"), (2, "多久交付？")],
        text="有问号了？有的。" * 30,
    )
    assert _codes(geo_rules["geo.faq_structure_mismatch"].check(page, _ctx())) == set()


def test_faq_mismatch_silent_on_normal_page(geo_rules):
    """没自称 FAQ 就跟这事无关。"""
    page = _page(word_count=400, title="关于我们", headings=[(2, "简介")])
    assert _codes(geo_rules["geo.faq_structure_mismatch"].check(page, _ctx())) == set()


def test_faq_mismatch_evidence_mentions_js_caveat(geo_rules):
    """⚠️ FAQ 常由 JS 注入，evidence 必须提醒用户先确认源码。"""
    page = _page(
        word_count=400, title="常见问题",
        headings=[(2, "常见问题")], text="没有问号。" * 40,
    )
    issue = list(geo_rules["geo.faq_structure_mismatch"].check(page, _ctx()))[0]
    assert "JS" in issue.evidence["caveat"]


# --------------------------------------------------------------------------
# ⚠️ 绝不声称能预测 AI 引用率
# --------------------------------------------------------------------------


def test_no_rule_claims_to_predict_ai_citations(geo_rules):
    """这个包最大的诱惑是写成「你的 AI 可引用性得分是多少」。

    没有公开依据能算那个分。任何一条规则只要暗示自己能预测引用结果，
    就是把猜测包装成结论 —— 用户会照着改，改完没有任何数据能证明有没有用。
    """
    forbidden = ("可引用性得分", "引用率", "会被引用", "ai 排名", "ai 排名分数")
    for code, rule in geo_rules.items():
        blob = f"{rule.title}{rule.description}{rule.fix_hint}{rule.fix_example or ''}"
        for kw in forbidden:
            assert kw not in blob.lower(), f"{code} 暗示自己能预测引用结果（命中「{kw}」）"


def test_every_issue_carries_a_caveat(geo_rules):
    """每条结论都要写明局限。"""
    page = _page(external_link_count=0, headings=[(2, "我们是谁")])
    issue = list(geo_rules["geo.no_outbound_references"].check(page, _ctx()))[0]
    assert issue.evidence.get("caveat")


def test_rules_have_fix_hints(geo_rules):
    for code, rule in geo_rules.items():
        assert rule.fix_hint.strip(), f"{code} 没写怎么修"