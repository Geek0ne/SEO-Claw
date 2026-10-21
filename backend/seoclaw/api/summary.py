"""报告汇总的**唯一**装配点。

⚠️ 为什么把它从 routes.py 里抽出来：原来那段构造只写在
``GET /sites/{id}/report`` 里。现在要同时给 MCP Server 用 —— 若 MCP 那边
另写一份，两处口径必然分叉，而**分叉之后没人知道该信哪个**。这正是我
今天在别处反复记下的教训，这里自己先照做。

MCP Server 把工具交给模型自主调用，所以它拿到的报告必须和网页上的
那份**逐字段一致**；不一致的话，模型给出的建议会和用户看到的对不上，
而用户没理由知道该信哪个。
"""

from __future__ import annotations

from typing import Any

from .. import models as domain
from ..db import models as m
from ..scoring import top_actions


def issue_payload(i: m.Issue) -> dict[str, Any]:
    """Issue → dict（出参的中间形态）。

    ⚠️ dict 而不是 Pydantic 模型：MCP 那边要能直接 JSON 序列化，
    而模型层不该为了一个 transport 反向依赖 API 层的 schema。

    fix_hint / fix_example / impact 是「可执行改法」的三件套：网页
    「最该先做的事」和问题清单都靠它们给用户可照着改的建议，
    缺了就退化成一张只报病不开药的清单。
    """
    return {
        "id": i.id,
        "code": i.code,
        "severity": i.severity.value,
        "scope": i.scope.value,
        "url": i.url,
        "title": i.title,
        "fingerprint": i.fingerprint,
        "status": i.status.value,
        "occurrences": i.occurrences or 1,
        "description": i.description,
        "impact": i.impact,
        "fix_hint": i.fix_hint,
        "fix_example": i.fix_example,
    }


def _to_domain_issue(row: m.Issue) -> domain.Issue:
    """DB 行 → 领域模型（只为复用 scoring.top_actions 的排序）。

    ⚠️ 必须转成**领域**枚举再进排序：SEVERITY_WEIGHT 的键是
    models.Severity，拿 db.models.Severity 去查是另一个枚举类，
    直接 KeyError——两个枚举值同名不同类。
    """
    return domain.Issue(
        code=row.code,
        severity=domain.Severity(row.severity.value),
        scope=domain.Scope(row.scope.value),
        url=row.url,
        title=row.title,
        description=row.description,
        fix_hint=row.fix_hint,
        fix_example=row.fix_example,
    )


def latest_score(jobs) -> float | None:
    """最近一次扫描的健康分。

    ⚠️ 读 ``job.health_score`` 这条真列；老库没跑迁移时用 getattr 兜底成
    None，而不是抛 AttributeError 把接口打挂。

    0 页成功必须是 ``None`` 而不是 0 —— 「一页没抓到」和「抓到了但全是
    问题」是两回事，都报 0 分就分不出该重爬还是该改。
    """
    if not jobs.items:
        return None
    v = getattr(jobs.items[0], "health_score", None)
    return float(v) if isinstance(v, (int, float)) else None


async def build_summary(uow, site_id: int) -> dict[str, Any]:
    """装配报告汇总。routes 与 MCP 共用这一份。"""
    site = await uow.sites.get(site_id)
    if site is None:
        raise LookupError(f"站点不存在：{site_id}")

    jobs = await uow.jobs.list_for_site(site_id, limit=1)
    raw_counts = await uow.issues.count_by_severity(site_id)
    # 缺失的 severity 必须补 0：调用方按 key 取值，缺 key 会渲染成 undefined
    counts = {sev.value: raw_counts.get(sev.value, 0) for sev in m.Severity}
    issues_page = await uow.issues.list(site_id, limit=200)
    pages_crawled = jobs.items[0].pages_crawled if jobs.items else 0

    # ---- Top 5 优先做：与 CLI/HTML 报告同一个 scoring.top_actions ----
    # ⚠️ 以前网页自己按严重级排序取前 5，而报告按「严重度 × 影响面」排——
    # 同一次扫描两处「先做」对不上，用户没理由知道该信哪个（MCP 那边
    # 同样拿不到）。排序只在 scoring 里实现一份，出口只做序列化。
    # 输入就用上面那份问题清单（≤200 条）：Top 5 从「用户看到的清单」里
    # 排，不在背后看一份用户看不到的数据。
    rows = list(issues_page.items)
    reach: dict[str, int] = {}
    for row in rows:
        reach[row.code] = reach.get(row.code, 0) + 1
    top = []
    for issue in top_actions(
        [_to_domain_issue(r) for r in rows], max(pages_crawled, 1), limit=5
    ):
        # 行数据按 (code, url) 找回对应 DB 行的 id/状态，再补影响页数。
        src = next(
            (r for r in rows if r.code == issue.code and r.url == issue.url), None
        )
        entry: dict[str, Any] = (
            issue_payload(src)
            if src is not None
            else {
                "code": issue.code,
                "severity": issue.severity.value,
                "scope": issue.scope.value,
                "url": issue.url,
                "title": issue.title,
                "description": issue.description,
                "fix_hint": issue.fix_hint,
                "fix_example": issue.fix_example,
            }
        )
        entry["affected_pages"] = reach.get(issue.code, 1)
        top.append(entry)

    return {
        "domain": site.domain,
        "pages_crawled": pages_crawled,
        "counts": counts,
        "health_score": None if pages_crawled == 0 else latest_score(jobs),
        "top_actions": top,
        "issues": [issue_payload(i) for i in rows],
    }
