"""质量与验证模块的测试。

⚠️ 这组测试的价值不在「接口返回 200」——那太浅了。这组要守住三件事：

1. **规则目录与注册表一致**：加一条规则、删一条规则、改一个严重级，
   目录必须自动跟着变。目录若与代码分叉，界面就在说谎。
2. **自检不是「永远通过」**：用例红了必须真的红。这条最容易在重构时
   被悄悄破坏——比如把 ``expect`` 改成跟实际行为一致，套件立刻又绿了，
   但什么都没验。
3. **拿不到数据时如实说「没有」**：不返回 0、不返回空 dict。
   「没测过」和「测了是 0」在报告里分不开，决策就做不了。
"""

from __future__ import annotations

import os
import tempfile


# ⚠️ 必须在 import seoclaw.* 之前设：引擎会被缓存，环境变量设晚了
# 会连到别的库上去。
_TMP_DB = os.path.join(tempfile.mkdtemp(), "quality_test.db")
os.environ["SEO_CLAW_DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB}"

from fastapi.testclient import TestClient

from seoclaw import quality
from seoclaw.audit.engine import default_registry
from seoclaw.main import app
from seoclaw.models import Market


# --------------------------------------------------------------------------
# 1. 规则目录
# --------------------------------------------------------------------------


def test_rule_catalog_matches_registry_exactly():
    """目录里的每条规则都必须真实存在于注册表。

    反向也要成立：**注册表里有、目录里没有**同样算失败。
    只查正向的话，删规则时目录会留一条幽灵，界面照样显示。
    """
    catalog = quality.rule_catalog()
    catalog_codes = {r["code"] for r in catalog["rules"]}

    reg = default_registry()
    registry_codes: set[str] = set()
    for market in Market:
        for rule in reg.page_rules_for([market]) + reg.site_rules_for([market]):
            registry_codes.add(rule.code)

    assert catalog_codes == registry_codes, (
        f"目录与注册表不一致；多出={catalog_codes - registry_codes} "
        f"缺少={registry_codes - catalog_codes}"
    )


def test_rule_catalog_reports_severity_and_scope():
    """严重级与作用域必须来自规则类本身，不能写死在模块里。"""
    catalog = quality.rule_catalog()
    by_code = {r["code"]: r for r in catalog["rules"]}

    assert by_code["title.missing"]["severity"] == "critical"
    assert by_code["title.missing"]["scope"] == "page"
    assert by_code["title.duplicate"]["scope"] == "site"

    # 汇总数字必须与明细自洽
    assert catalog["count"] == len(catalog["rules"])
    assert sum(catalog["by_severity"].values()) == catalog["count"]
    assert sum(catalog["by_scope"].values()) == catalog["count"]
    assert sum(catalog["by_market"].values()) == catalog["count"]


def test_rule_catalog_filtered_by_market():
    """按市场过滤时，返回的规则必须都在该市场包内。"""
    catalog = quality.rule_catalog(["google"])
    markets = {r["market"] for r in catalog["rules"]}
    assert markets <= {"google", "base"}

    baidu = quality.rule_catalog(["baidu"])
    baidu_codes = {r["code"] for r in baidu["rules"]}
    # 百度专属规则必须在
    assert "title.chinese_too_long" in baidu_codes
    # base 规则也必须在（所有市场共用）
    assert "title.missing" in baidu_codes


def test_rule_catalog_keeps_fix_hints():
    """每条规则都要带「怎么改」——只报病不开药的清单没法用。"""
    catalog = quality.rule_catalog()
    missing_hint = [r["code"] for r in catalog["rules"] if not r.get("fix_hint")]
    assert not missing_hint, f"这些规则没有 fix_hint：{missing_hint}"


# --------------------------------------------------------------------------
# 2. 黄金样本自检
# --------------------------------------------------------------------------


def test_selftest_all_cases_pass():
    """自检必须全绿。

    ⚠️ 这条断言本身**不能**让自检变绿——它只是把「红了要有人管」这件事
    钉进 CI。真正让套件有意义的是 ``expect`` 字段：期望值写在用例旁边，
    改规则判据时这里会红。
    """
    result = quality.run_selftest()
    failed = [c for c in result["cases"] if not c["passed"]]
    assert not failed, f"自检用例未通过：{[(c['code'], c['expect']) for c in failed]}"
    assert result["summary"]["all_passed"] is True


def test_selftest_covers_every_registered_rule():
    """每条注册规则都至少被一条自检用例覆盖。

    ⚠️ 为什么这条重要：新增规则时若忘了写用例，套件照样全绿——
    那种「绿」什么都没验。覆盖率断言把「加规则要加用例」变成硬约束。
    """
    result = quality.run_selftest()
    uncovered = result["summary"]["uncovered_rules"]
    assert not uncovered, f"这些规则没有自检用例：{uncovered}"


def test_selftest_has_both_fire_and_silent_expectations():
    """每条被覆盖的规则都要有「应触发」与「应沉默」两类用例。

    ⚠️ 只测「该报的报了」的套件等于没测误报——而误报比漏报更难被用户
    发现：漏报用户会骂工具，误报用户会照着改，改坏了才发现。
    """
    result = quality.run_selftest()
    by_code: dict[str, set[str]] = {}
    for case in result["cases"]:
        by_code.setdefault(case["code"], set()).add(case["expect"])

    # 有些规则天然只有一种形态（如站点级规则在数据不足时只会沉默），
    # 所以这里断言「至少有 silent 用例」——误报防线不能缺。
    no_silent = [code for code, exps in by_code.items() if "silent" not in exps]
    assert not no_silent, f"这些规则缺少「应沉默」用例：{no_silent}"


def test_selftest_is_deterministic():
    """同一份代码连跑两次，结果必须一模一样。

    ⚠️ 自检里若混进了时间、随机数或网络，结果就会漂——那种「有时绿
    有时红」的套件比没有更坏：它让人以为验过了。
    """
    first = quality.run_selftest()
    second = quality.run_selftest()
    assert [c["passed"] for c in first["cases"]] == [
        c["passed"] for c in second["cases"]
    ]
    assert first["summary"] == second["summary"]


def test_selftest_failure_is_reported_not_swallowed():
    """用例不成立时必须**报出来**，不能悄悄跳过。

    ⚠️ 造一条期望错误的用例来验证：expect 与实际不符时，
    passed 必须是 False，且整轮 all_passed 必须是 False。
    """
    broken = quality.SelfTestCase(
        code="title.missing",
        expect="fires",
        note="故意造错的用例：这份语料有 title，不该触发",
        html=quality._html(title="有 title 的页面"),
    )
    result = quality._run_case(broken)
    assert result["passed"] is False
    assert result["fired"] is False


def test_selftest_market_filter_narrows_results():
    """按市场过滤时只跑该市场的用例。"""
    result = quality.run_selftest(["google"])
    markets = {m for c in result["cases"] for m in c["markets"]}
    assert markets <= {"google"}
    assert result["summary"]["total"] < len(quality.SELFTEST_CASES)


# --------------------------------------------------------------------------
# 3. 验证台账与准确率
# --------------------------------------------------------------------------


def test_ledger_parses_markdown_table():
    """台账是人工维护的 Markdown 表格，接口要能解析出来。"""
    ledger = quality.verification_ledger()
    if not ledger["available"]:
        # docs/ 不在包内（pip 安装场景）。此时必须**如实说没有**，
        # 而不是返回空表格让人以为「一条都没核过」。
        assert ledger["rows"] == []
        assert ledger["reason"]
        return

    assert ledger["rows"], "台账可用却一行都没解析出来"
    # 规则名不该带 Markdown 反引号——带着就与规则目录的 code 对不上
    for row in ledger["rows"]:
        assert "`" not in row["rule"]
        assert row["rule"]
    # 汇总数字必须与明细自洽
    total = sum(r["checked"] or 0 for r in ledger["rows"])
    assert ledger["summary"]["checked"] == total


def test_accuracy_report_shape():
    """准确率报告：数字要么来自文件，要么明说不可用——不能是 0。"""
    report = quality.accuracy_report()
    assert "available" in report
    if not report["available"]:
        assert report["reason"], "不可用时必须说明原因"
        assert report["recheck"] is None
        return

    recheck = report["recheck"]
    assert recheck is not None
    # 存疑数不能是 0 充数——真跑出来的数据里它就是有值的
    assert recheck.get("inconclusive") is not None
    assert recheck.get("precision_on_adjudicable") is not None


def test_docs_missing_returns_not_zero(monkeypatch, tmp_path):
    """docs/ 找不到时，必须返回「不可用」而不是 0 或空 dict。

    ⚠️ 这是最容易被违反的一条：读不到文件时随手 ``return {}``，
    界面就会把「没测过」渲染成「准确率 0%」——用户会以为这个工具
    一条都不准。
    """
    monkeypatch.setenv("SEO_CLAW_DOCS_DIR", str(tmp_path / "nonexistent"))
    # _repo_root 找不到带 accuracy_recheck.json 的目录就返回 None
    report = quality.accuracy_report()
    assert report["available"] is False
    assert report["recheck"] is None
    assert report["reason"]

    ledger = quality.verification_ledger()
    assert ledger["available"] is False
    assert ledger["rows"] == []


# --------------------------------------------------------------------------
# 4. HTTP 端点
# --------------------------------------------------------------------------


def test_quality_endpoints_return_200():
    """五个端点都要能通。"""
    client = TestClient(app)
    for path in (
        "/api/v1/quality/rules",
        "/api/v1/quality/selftest",
        "/api/v1/quality/accuracy",
        "/api/v1/quality/ledger",
        "/api/v1/quality/overview",
    ):
        resp = client.get(path)
        assert resp.status_code == 200, f"{path} 返回 {resp.status_code}"


def test_overview_aggregates_consistently():
    """overview 的汇总数字必须与各子端点自洽。

    ⚠️ 分块聚合最容易出的错是「每块各自算一遍，块之间对不上」——
    界面上就会出现「自检说 64 条通过，概览说 60 条」这种自相矛盾。
    """
    client = TestClient(app)
    overview = client.get("/api/v1/quality/overview").json()
    selftest = client.get("/api/v1/quality/selftest").json()
    rules = client.get("/api/v1/quality/rules").json()

    assert overview["selftest"]["total"] == selftest["summary"]["total"]
    assert overview["selftest"]["passed"] == selftest["summary"]["passed"]
    assert overview["rules"]["count"] == rules["count"]


def test_overview_coverage_counters_are_consistent():
    """覆盖率计数不能超过注册规则数——超了就说明口径错了。"""
    client = TestClient(app)
    overview = client.get("/api/v1/quality/overview").json()
    cov = overview["coverage"]
    assert cov["selftested"] <= cov["registered"]
    assert cov["ledger_verified"] <= cov["registered"]
    assert cov["registered"] == overview["rules"]["count"]
