"""
报告渲染层测试。

为什么单独测渲染：踩过「规则判定正确但报告里看不到」的坑——
verdict 字段排在证据第 7 位，被「只显示前 3 个字段」的逻辑截没了。
判定再准，用户看不到就等于没做。这类问题测试必须覆盖。
"""

from __future__ import annotations

from app.models import Issue, Severity
from app.report import _ordered_evidence, _render_evidence, _render_issue_line

_EVIDENCE = {
    "word_count": 28,
    "text_preview": "Index",
    "status_code": 200,
    "internal_outbound_links": 42,
    "inbound_links": 3,
    "url_looks_like_index": True,
    "verdict": "likely_index_or_hub",
    "verdict_explain": "出链多、URL 形似索引页，大概率是正常的目录/列表页",
}


def _issue(**kw) -> Issue:
    base = {
        "code": "soft404",
        "severity": Severity.INFO,
        "url": "https://x.test/a",
        "title": "疑似软 404",
        "evidence": dict(_EVIDENCE),
    }
    base.update(kw)
    return Issue(**base)


def test_verdict_is_ordered_first():
    """判定结论必须排在证据字段最前面。"""
    assert list(_ordered_evidence(_EVIDENCE))[0] == "verdict"


def test_verdict_visible_in_issue_line():
    """明细行里必须能看到 verdict（曾被截断掉的正是这里）。"""
    out = "\n".join(_render_issue_line(_issue(), 3))
    assert "verdict" in out
    assert "likely_index_or_hub" in out
    # verdict 必须在 word_count 之前出现
    assert out.index("verdict") < out.index("word_count")


def test_verdict_visible_in_evidence_block():
    out = "\n".join(_render_evidence(_issue(), 3))
    assert "likely_index_or_hub" in out
    assert "大概率是正常的目录/列表页" in out


def test_verdict_highlighted_not_in_code_ticks():
    """判定结论应加粗突出，而非像普通字段那样用等宽字体。"""
    out = "\n".join(_render_issue_line(_issue(), 3))
    assert "**verdict**" in out
    assert "`verdict`" not in out


def test_ordered_evidence_keeps_all_keys():
    """重排不能丢字段。"""
    out = _ordered_evidence(_EVIDENCE)
    assert set(out) == set(_EVIDENCE)


def test_ordered_evidence_passes_unknown_keys_through():
    """未列入优先级的字段按原序追加在后面。"""
    out = _ordered_evidence({"custom": 1, "verdict": "x", "another": 2})
    assert list(out) == ["verdict", "custom", "another"]


def test_site_scope_issue_shows_sample_urls():
    issue = _issue(
        scope="site",
        url=None,
        evidence={"sample_urls": ["https://x.test/1", "https://x.test/2"]},
    )
    out = "\n".join(_render_issue_line(issue, 3))
    assert "https://x.test/1" in out
    assert "https://x.test/2" in out


# --------------------------------------------------------------------------
# 根因聚合：噪音比漏报更伤
# --------------------------------------------------------------------------


def _issues_same_code(n: int, code: str = "title.too_short", sev=None):
    from app.models import Issue

    return [
        Issue(
            code=code,
            severity=sev or Severity.MEDIUM,
            url=f"https://x.test/p{i}",
            title="title 过短",
        )
        for i in range(n)
    ]


def test_same_code_issues_collapse_to_one_group():
    """10 条同 code 问题必须合并成 1 组，而不是刷屏 10 行。"""
    from app.report import aggregate_by_root_cause

    grouped = aggregate_by_root_cause(_issues_same_code(10))
    groups = grouped[Severity.MEDIUM]
    assert len(groups) == 1
    assert groups[0].affected_count == 10
    assert len(groups[0].urls) == 10


def test_aggregation_preserves_total_affected_count():
    """合并不能丢信息：总影响数必须守恒。"""
    from app.report import aggregate_by_root_cause

    issues = _issues_same_code(6) + _issues_same_code(3, code="schema.missing")
    grouped = aggregate_by_root_cause(issues)
    total = sum(g.affected_count for gs in grouped.values() for g in gs)
    assert total == 9


def test_aggregation_groups_by_severity_separately():
    from app.models import Issue
    from app.report import aggregate_by_root_cause

    issues = [
        Issue(code="x.y", severity=Severity.HIGH, url="https://x.test/a"),
        Issue(code="x.y", severity=Severity.LOW, url="https://x.test/b"),
    ]
    grouped = aggregate_by_root_cause(issues)
    assert grouped[Severity.HIGH][0].affected_count == 1
    assert grouped[Severity.LOW][0].affected_count == 1


def test_aggregated_line_shows_affected_count_not_single_url():
    from app.report import aggregate_by_root_cause

    grouped = aggregate_by_root_cause(_issues_same_code(10))
    agg = grouped[Severity.MEDIUM][0]
    out = "\n".join(_render_issue_line(agg.representative, 3, agg=agg))
    assert "影响 10 个页面" in out


def test_root_cause_hint_surfaced_for_title_problem():
    """title.duplicate / title.too_short 指向同一根因时要提示，
    否则用户会去「把 title 加长」这种表面动作上打转。"""
    from app.report import aggregate_by_root_cause

    grouped = aggregate_by_root_cause(_issues_same_code(10))
    agg = grouped[Severity.MEDIUM][0]
    out = "\n".join(_render_issue_line(agg.representative, 3, agg=agg))
    assert "根因推测" in out
    assert "共用同一套 title" in out


def test_no_root_cause_hint_for_unrelated_code():
    from app.models import Issue
    from app.report import aggregate_by_root_cause

    issues = [Issue(code="soft404", severity=Severity.MEDIUM, url=f"https://x.test/{i}") for i in range(3)]
    grouped = aggregate_by_root_cause(issues)
    agg = grouped[Severity.MEDIUM][0]
    out = "\n".join(_render_issue_line(agg.representative, 3, agg=agg))
    assert "根因推测" not in out


def test_aggregation_is_stable_across_input_order():
    """同 code 问题的输出顺序不能因为扫描顺序不同而抖动。"""
    from app.report import aggregate_by_root_cause

    a = _issues_same_code(5)
    b = list(reversed(a))
    g1 = aggregate_by_root_cause(a)[Severity.MEDIUM][0]
    g2 = aggregate_by_root_cause(b)[Severity.MEDIUM][0]
    assert g1.urls == g2.urls


def test_long_evidence_value_is_truncated_not_dropped():
    issue = _issue(evidence={"verdict": "x", "text_preview": "A" * 500})
    out = "\n".join(_render_issue_line(issue, 3))
    assert "..." in out
    assert "text_preview" in out
