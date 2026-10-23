"""质量与验证端点：把后端的验证能力暴露给 Web 界面。

⚠️ 为什么单独一个模块而不是塞进 ``routes.py``：``routes.py`` 已经 1500 行，
全是站点相关的业务路由。这组端点的性质完全不同——**只读、不碰数据库、
不涉及租户归属**，是「关于这个工具本身」的元信息。混在一起会让
``routes.py`` 继续膨胀，也让这组端点的安全边界（只读）变得不显眼。

安全边界：**全部只读**。不写库、不发外部请求（自检跑的是本地构造的
HTML，不联网）。所以不依赖 ``get_uow``，也不需要站点归属校验。
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Query

from .. import quality

router = APIRouter(prefix="/api/v1/quality")


@router.get("/rules")
def list_rules(
    markets: Optional[str] = Query(
        default=None,
        description="逗号分隔的市场包（base,google,baidu,cnh_eco,geo）。不给则返回全部。",
    ),
) -> dict[str, Any]:
    """规则目录：从注册表实况导出。

    ⚠️ 数据源是 ``default_registry()``，不是硬编码清单。规则加了、删了、
    改了严重级，这里自动跟着变——另写一份清单必然与代码分叉。
    """
    wanted = [m.strip() for m in markets.split(",") if m.strip()] if markets else None
    return quality.rule_catalog(wanted)


@router.get("/selftest")
def selftest(
    markets: Optional[str] = Query(
        default=None,
        description="逗号分隔的市场包。不给则跑全部自检用例。",
    ),
) -> dict[str, Any]:
    """黄金样本自检：真跑一遍规则引擎，逐条核对期望。

    这是「后端测试验证功能在前端体现」的核心：**不是展示一份静态数字，
    而是当场把规则引擎跑一遍**，让用户看到每条规则的判据在真实语料上
    成立或不成立。用例没过就红，不粉饰。
    """
    wanted = [m.strip() for m in markets.split(",") if m.strip()] if markets else None
    return quality.run_selftest(wanted)


@router.get("/accuracy")
def accuracy() -> dict[str, Any]:
    """准确率校准报告（读 ``docs/accuracy_*.json``）。

    ⚠️ 拿不到文件时返回 ``available: false`` 并说明原因，**不返回 0**——
    「没测过」和「测了是 0」是两回事，报告里分不开就没法决策。
    """
    return quality.accuracy_report()


@router.get("/ledger")
def ledger() -> dict[str, Any]:
    """回源核对台账（解析 ``docs/verification-ledger.md`` 的表格）。"""
    return quality.verification_ledger()


@router.get("/overview")
def overview() -> dict[str, Any]:
    """一页看完「这个工具自己有多可靠」。

    把规则目录、自检、准确率、台账四块**聚合**成一个响应：界面首屏不必
    发四个请求，也不必自己拼装跨块的一致性（自检覆盖了哪些规则、
    台账核过哪些规则，是可以互相印证的）。
    """
    catalog = quality.rule_catalog()
    st = quality.run_selftest()
    acc = quality.accuracy_report()
    led = quality.verification_ledger()

    selftested = {c["code"] for c in st["cases"]}
    ledger_rules = {r["rule"] for r in led.get("rows", [])}
    # 台账里的规则名可能带后缀（「title.missing（另一批）」），取前缀对齐
    ledger_codes = {r.split("（")[0].split("(")[0].strip() for r in ledger_rules}
    catalog_codes = {r["code"] for r in catalog["rules"]}

    return {
        "rules": {
            "count": catalog["count"],
            "by_market": catalog["by_market"],
            "by_severity": catalog["by_severity"],
            "by_scope": catalog["by_scope"],
        },
        "selftest": st["summary"],
        "accuracy": acc,
        "ledger": led,
        "coverage": {
            "registered": len(catalog_codes),
            "selftested": len(selftested & catalog_codes),
            "ledger_verified": len(ledger_codes & catalog_codes),
            "not_selftested": sorted(catalog_codes - selftested),
            "not_ledger_verified": sorted(catalog_codes - ledger_codes),
        },
    }
