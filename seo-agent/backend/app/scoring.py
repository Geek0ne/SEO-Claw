"""
健康分与优先级排序。

重要提醒：权重是初版拍脑袋定的，必须用真实站点数据校准。
校准方法见 docs/scoring-calibration.md（待补）。
"""

from __future__ import annotations

from .models import Issue, Page, Severity
from .util import same_site_scope

# 严重度 → 基础权重（按「影响面」折算后的最终扣分）
SEVERITY_WEIGHT: dict[Severity, float] = {
    Severity.CRITICAL: 30.0,
    Severity.HIGH: 15.0,
    Severity.MEDIUM: 5.0,
    Severity.LOW: 1.0,
    Severity.INFO: 0.0,
}

# 扣分总系数。⚠️ 初值未经真实数据校准，docs/scoring-calibration.md 记录校准方法。
# 含义：一条 critical 类问题若影响了全站 100% 页面，则扣 30 分。
SCORE_SCALE = 1.0

# 六大模块，用于雷达图与分项得分
DIMENSIONS: dict[str, str] = {
    "crawlability": "可抓取与收录",
    "architecture": "信息架构",
    "content": "页面内容质量",
    "performance": "性能与体验",
    "structured_data": "结构化数据",
    "trust": "安全与信任",
}

# code 前缀 -> 维度
_CODE_DIMENSION: dict[str, str] = {
    "noindex": "crawlability",
    "canonical": "crawlability",
    "soft404": "crawlability",
    "title.missing": "crawlability",
    "title.too": "content",
    "title.duplicate": "content",
    "meta.": "content",
    "h1.": "content",
    "img.": "content",
    "schema.": "structured_data",
    "depth.": "architecture",
    "orphan.": "architecture",
    "link.": "architecture",
    "http.mixed": "trust",
}


def dimension_for(code: str) -> str:
    for prefix, dim in _CODE_DIMENSION.items():
        if code.startswith(prefix):
            return dim
    return "content"


def score(
    issues: list[Issue],
    total_pages: int,
    domain: str | None = None,
) -> tuple[float | None, dict[str, object]]:
    """计算 0~100 健康分。没审到任何页面时返回 None，**不给分**。

    按 code 聚合，用「**该问题影响到的页面占比**」作为扣分系数，
    而不是把每条问题单独除以总页数。

    后者会导致分数不随站点规模可比：站点越大，同类问题分母越大、扣分越少，
    一个 10 万页的烂站点可能比 50 页的烂站点分还高。
    聚合后，「20% 的页面缺 canonical」在 50 页和 10 万页站点上扣分相同。

    传入 `domain` 时只给「本站」扣分，兄弟子域的问题单独列出（见下）。
    """
    # ⚠️ 0 页 → 返回 None，不给分。
    #
    # 原来这里直接 `pages = max(total_pages, 1)` 兜底：0 页被当成 1 页算，
    # 一个问题都没有 → 扣分 0 → **健康分 100.0**。实测两处：
    #   lobste.rs 的 robots.txt 是 `User-agent: * / Disallow: /`（全面禁止），
    #     守规矩的结果是 0 页，报告却写「健康分 100.0、零问题」；
    #   w3.org 被限流时种子页 429，frontier 空，同样 0 页拿 100 分。
    # 两种都会让用户以为全站审过了、没问题——**「没审到」和「没问题」是两件事**，
    # 报成 100 分就是把前者说成后者。
    #
    # 与 gymshark 那次同一个病（子域问题算进主站分 → 0.0 分）：把不该算的
    # 算进了分数。这次的反向版本。
    if total_pages <= 0:
        return None, {
            "not_evaluated": True,
            "reason": "no_pages_audited",
            "total_pages": total_pages,
            "issue_count": len(issues),
        }

    pages = max(total_pages, 1)

    # 兄弟子域的问题不进主站健康分。
    #
    # 实测：gymshark.com 抓 25 页，其中 24 页是 us.checkout.gymshark.com，
    # 124 条问题 119 条来自子域，主站被判 0.0 分。结账页带 noindex 是
    # **正确配置**，却被报成 CRITICAL「页面被屏蔽收录」——规则判得对、
    # 用户照做反而更糟（照做的后果是让搜索引擎收录一个结账页）。
    # vitejs.dev 同理：24 条问题全在 ja/v2/registry 子域，剔掉后 94.2 → 100.0。
    in_scope: list[Issue] = []
    out_of_scope: list[Issue] = []
    if domain:
        for it in issues:
            (in_scope if same_site_scope(it.url, domain) else out_of_scope).append(it)
    else:
        in_scope = list(issues)

    # code -> (severity, scope, 受影响 URL 集合)
    grouped: dict[str, tuple[Severity, str, set[str | None]]] = {}
    for issue in in_scope:
        weight = SEVERITY_WEIGHT[issue.severity]
        if weight == 0.0:
            continue
        prev = grouped.get(issue.code)
        if prev is None:
            grouped[issue.code] = (issue.severity, issue.scope.value, {issue.url})
        else:
            prev[2].add(issue.url)

    total_deduction = 0.0
    dim_deduction: dict[str, float] = {d: 0.0 for d in DIMENSIONS}
    severity_counts: dict[str, int] = {s.value: 0 for s in Severity}
    code_breakdown: dict[str, dict[str, object]] = {}

    for code, (severity, scope, urls) in grouped.items():
        severity_counts[severity.value] += 1
        weight = SEVERITY_WEIGHT[severity]

        if scope == "site":
            # 站点级问题（如孤岛页、重复 title）不按单页占比折算，
            # 直接按其涉及页面数在总页面中的占比算
            ratio = min(1.0, max(1, len(urls)) / pages)
        else:
            ratio = min(1.0, len(urls) / pages)

        deduction = weight * ratio * SCORE_SCALE
        dim = dimension_for(code)
        total_deduction += deduction
        dim_deduction[dim] += deduction
        code_breakdown[code] = {
            "severity": severity.value,
            "affected_pages": len(urls),
            "ratio": round(ratio, 4),
            "deduction": round(deduction, 2),
        }

    health = max(0.0, min(100.0, 100.0 - total_deduction))

    dimension_scores = {
        dim: max(0.0, min(100.0, 100.0 - dim_deduction[dim]))
        for dim in DIMENSIONS
    }

    breakdown = {
        "total_deduction": round(total_deduction, 2),
        "severity_counts": severity_counts,
        "dimension_scores": {k: round(v, 1) for k, v in dimension_scores.items()},
        "issue_count": len(in_scope),
        "total_pages": total_pages,
        "per_code": code_breakdown,
    }
    return round(health, 1), breakdown


def prioritize(issues: list[Issue], total_pages: int) -> list[Issue]:
    """给问题排序：**影响值降序**，最该修的排最前。

    影响值 = 严重度权重 × 受影响面占比。
    这样用户看到的第一条一定是「修了收益最大」的那条，
    而不是「最严重但只影响一个页面」的那条。

    ⚠️ 实现注意：排序键必须取负数。Python 默认升序，
    直接返回正值会把影响最小的排到最前面（这个 bug 真的发生过）。
    """
    pages = max(total_pages, 1)

    # 先按 code 聚合，算出每个 code 的整体影响面
    reach_by_code: dict[str, float] = {}
    scope_by_code: dict[str, str] = {}
    seen: set[tuple[str, str | None]] = set()
    for issue in issues:
        key = (issue.code, issue.url)
        if key in seen:
            continue
        seen.add(key)
        reach_by_code[issue.code] = reach_by_code.get(issue.code, 0.0) + 1
        scope_by_code.setdefault(issue.code, issue.scope.value)

    def impact(issue: Issue) -> float:
        weight = SEVERITY_WEIGHT[issue.severity]
        affected = reach_by_code.get(issue.code, 1)
        ratio = min(1.0, max(1, affected) / pages)
        if scope_by_code.get(issue.code) == "site":
            # 站点级问题影响面天然更广，给一个放大系数
            ratio = min(1.0, ratio * 3.0)
        return weight * ratio

    # 降序 → 取负；同时把 URL 排序改成稳定的字典序，避免同分时顺序抖动
    return sorted(
        issues,
        key=lambda i: (-impact(i), i.severity.rank, i.code, i.url or ""),
    )


def top_actions(issues: list[Issue], total_pages: int, limit: int = 5) -> list[Issue]:
    """提炼「最该先做的 N 件事」。

    渐进披露原则：先给 3~5 条，其余折叠。不这么做的话用户会直接被
    上百个问题劝退——这是同类工具最常见的失败原因。
    """
    ordered = prioritize(issues, total_pages)
    # 同一 code 只出现一次，避免 200 个重复 title 占据整个列表
    seen: set[str] = set()
    out: list[Issue] = []
    for issue in ordered:
        if issue.code in seen:
            continue
        seen.add(issue.code)
        out.append(issue)
        if len(out) >= limit:
            break
    return out
