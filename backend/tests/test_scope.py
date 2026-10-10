"""审计范围（主站 vs 兄弟子域）的回归测试。

为什么这些测试值钱
------------------
子域混入是实测抓出来的真问题，不是假想：gymshark.com 抓 25 页，
其中 24 页是 us.checkout.gymshark.com，124 条问题有 119 条来自子域，
主站被判 0.0 分。结账页带 noindex 是**正确配置**，却被报成 CRITICAL
「页面被屏蔽收录」——规则判得对、用户照做反而更糟。

这类 bug 没有任何报错：分数照常产出，报告照常渲染，只是结论完全错。
所以必须用测试钉死口径。
"""

from __future__ import annotations

from seoclaw.models import Issue, Severity
from seoclaw.scoring import score
from seoclaw.util import same_site_scope


def _issue(url: str, code: str = "title.missing", sev: Severity = Severity.HIGH) -> Issue:
    return Issue(code=code, severity=sev, url=url, title="测试问题")


# --------------------------------------------------------------------------
# same_site_scope：口径本身
# --------------------------------------------------------------------------


def test_same_host_is_in_scope():
    assert same_site_scope("https://gymshark.com/a", "gymshark.com")


def test_www_variant_is_in_scope():
    """www 与裸域是同一个站，用户敲进去的两种写法不该被当成两个站。"""
    assert same_site_scope("https://www.gymshark.com/a", "gymshark.com")
    assert same_site_scope("https://gymshark.com/a", "www.gymshark.com")


def test_sibling_subdomain_is_out_of_scope():
    """实测元凶：同属可注册域，但是另一个站。"""
    assert not same_site_scope("https://us.checkout.gymshark.com/", "gymshark.com")


def test_regional_subdomain_is_out_of_scope():
    assert not same_site_scope("https://ja.vite.dev/guide", "vitejs.dev")
    assert not same_site_scope("https://v2.vite.dev/", "vitejs.dev")


def test_unrelated_domain_is_out_of_scope():
    assert not same_site_scope("https://example.com/", "gymshark.com")


def test_none_url_is_out_of_scope():
    """站点级问题可能没有 url；不能因此崩，也不能算进主站。"""
    assert not same_site_scope(None, "gymshark.com")


def test_case_and_port_insensitive():
    assert same_site_scope("https://GYMshark.com:443/a", "gymshark.com")


# --------------------------------------------------------------------------
# score(domain=...)：范围过滤真的生效
# --------------------------------------------------------------------------


def test_sibling_subdomain_issues_do_not_reduce_main_site_score():
    """实测形状：24 条子域 noindex + 25 条子域缺 title，把主站扣成 0.0。"""
    issues = [_issue(f"https://us.checkout.gymshark.com/p{i}") for i in range(24)]
    health, bd = score(issues, 25, "gymshark.com")

    assert health == 100.0, "主站不该为兄弟子域的问题扣分"
    assert bd["issue_count"] == 0
    assert bd["total_deduction"] == 0.0


def test_main_site_issues_still_deduct():
    """不能矫枉过正：主站自己的问题照扣。"""
    issues = [_issue(f"https://gymshark.com/p{i}") for i in range(5)]
    health, bd = score(issues, 10, "gymshark.com")

    assert health < 100.0
    assert bd["issue_count"] == 5
    assert bd["per_code"]["title.missing"]["affected_pages"] == 5


def test_mixed_scope_only_main_site_counts():
    """混合样本：主站 1 条 + 子域 24 条，应只算主站那 1 条。"""
    issues = [_issue("https://gymshark.com/only")]
    issues += [_issue(f"https://us.checkout.gymshark.com/p{i}") for i in range(24)]
    health, bd = score(issues, 25, "gymshark.com")

    assert bd["issue_count"] == 1
    # HIGH 权重 15，占比 1/25
    assert bd["total_deduction"] == round(15 * (1 / 25), 2)


def test_without_domain_keeps_old_behaviour():
    """domain=None 时不过滤，向后兼容：老调用方不该被这次改动打断。"""
    issues = [_issue("https://us.checkout.gymshark.com/p1")]
    health, bd = score(issues, 1)

    assert bd["issue_count"] == 1
    assert health == 85.0  # 100 - 15(HIGH)


def test_scope_issue_reproduces_real_gymshark_shape():
    """把实测数字原样钉住：修复前 0.0，修复后应回到合理区间。"""
    issues: list[Issue] = []
    # 主站 1 页，5 条问题
    for code, sev in (
        ("noindex.present", Severity.CRITICAL),
        ("title.missing", Severity.HIGH),
        ("h1.missing", Severity.HIGH),
        ("meta.missing", Severity.HIGH),
        ("soft404", Severity.HIGH),
    ):
        issues.append(_issue("https://gymshark.com/", code, sev))
    # 子域 24 页，每页同样 5 条
    for i in range(24):
        for code, sev in (
            ("noindex.present", Severity.CRITICAL),
            ("title.missing", Severity.HIGH),
            ("h1.missing", Severity.HIGH),
            ("meta.missing", Severity.HIGH),
            ("soft404", Severity.HIGH),
        ):
            issues.append(_issue(f"https://us.checkout.gymshark.com/p{i}", code, sev))

    # 分母按主站实抓页数 1 算（cli.py 的 in_scope_pages 口径）
    health, bd = score(issues, 1, "gymshark.com")

    # 1 页全中：CRITICAL 30 + 4×HIGH 15 = 扣 90 → 10.0 分。
    # 这里我一开始写的是 0.0，是**期望值算错**（以为四条 HIGH 也能扣满 30），
    # 不是代码算错。改测试而不是改断言去迁就实现。
    assert health == 10.0
    assert bd["issue_count"] == 5, "子域 120 条一条都不该进主站分母"
    assert bd["per_code"]["noindex.present"]["deduction"] == 30.0
    assert bd["per_code"]["title.missing"]["deduction"] == 15.0

    # 但子域那份数据不该消失：总数必须如实反映
    assert len(issues) == 125
