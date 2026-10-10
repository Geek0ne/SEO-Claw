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

from ..db import models as m


def issue_payload(i: m.Issue) -> dict[str, Any]:
    """Issue → dict（出参的中间形态）。

    ⚠️ dict 而不是 Pydantic 模型：MCP 那边要能直接 JSON 序列化，
    而模型层不该为了一个 transport 反向依赖 API 层的 schema。
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
    }


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
    return {
        "domain": site.domain,
        "pages_crawled": pages_crawled,
        "counts": counts,
        "health_score": None if pages_crawled == 0 else latest_score(jobs),
        "issues": [issue_payload(i) for i in issues_page.items],
    }
