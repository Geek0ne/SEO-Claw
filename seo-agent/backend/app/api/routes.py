"""HTTP 路由：站点管理 / 扫描触发 / 报告查询三类。

⚠️ 同步爬虫不能直接在协程里跑 —— `run_scan` 内部用 `asyncio.to_thread`
丢到线程池，事件循环才不会被一次几十秒的扫描堵死。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..db import models as m
from .deps import get_uow
from .schemas import (
    IssueOut,
    IssuePage,
    JobOut,
    ReportSummary,
    ScanRequest,
    SiteCreate,
    SiteOut,
)
from .scan_service import run_scan

router = APIRouter(prefix="/api/v1")


@router.get("/health")
def health() -> dict:
    return {"ok": True}


# --------------------------------------------------------------------------
# 站点管理
# --------------------------------------------------------------------------


@router.post("/sites", response_model=SiteOut, status_code=201)
async def create_site(body: SiteCreate, uow=__import__("fastapi").Depends(get_uow)) -> SiteOut:
    existing = await uow.sites.get_by_domain(body.domain)
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"站点已存在：{body.domain}")
    site = await uow.sites.create(body.domain, markets=body.markets)
    return SiteOut(
        id=site.id,
        domain=site.domain,
        markets=list(site.markets or []),
        is_active=site.is_active,
    )


@router.get("/sites", response_model=list[SiteOut])
async def list_sites(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    uow=__import__("fastapi").Depends(get_uow),
) -> list[SiteOut]:
    page = await uow.sites.list(limit=limit, offset=offset)
    return [
        SiteOut(
            id=s.id, domain=s.domain, markets=list(s.markets or []), is_active=s.is_active
        )
        for s in page.items
    ]


async def _require_site(uow, site_id: int) -> m.Site:
    site = await uow.sites.get(site_id)
    if site is None:
        raise HTTPException(status_code=404, detail=f"站点不存在：{site_id}")
    return site


@router.get("/sites/{site_id}", response_model=SiteOut)
async def get_site(site_id: int, uow=__import__("fastapi").Depends(get_uow)) -> SiteOut:
    site = await _require_site(uow, site_id)
    return SiteOut(
        id=site.id, domain=site.domain, markets=list(site.markets or []), is_active=site.is_active
    )


# --------------------------------------------------------------------------
# 扫描
# --------------------------------------------------------------------------


@router.post("/sites/{site_id}/scan", response_model=dict, status_code=201)
async def scan(site_id: int, body: ScanRequest, uow=__import__("fastapi").Depends(get_uow)) -> dict:
    site = await _require_site(uow, site_id)
    url = body.url or f"https://{site.domain}"
    markets = body.markets or list(site.markets or ["base"])
    # ⚠️ 开了增量却没给 checkpoint_dir → prior 为空 → 一个条件请求都不发，
    # 静默退化成全量扫描。CLI 那边有告警，API 这边原本没有：
    # 用户从接口看不出这次「增量」其实是全量，会误以为已经省钱。
    if body.incremental and not body.checkpoint_dir:
        raise HTTPException(
            status_code=400,
            detail="incremental=true 需要同时提供 checkpoint_dir（上一轮快照所在目录）。"
            "没有基准时不会发出任何条件请求，只会退化成一次全量扫描。",
        )
    summary = await run_scan(
        uow.session,
        site_id=site_id,
        url=url,
        markets=markets,
        max_pages=body.max_pages,
        max_depth=body.max_depth,
        per_domain_rps=body.per_domain_rps,
        incremental=body.incremental,
        checkpoint_dir=body.checkpoint_dir,
        respect_robots=body.respect_robots,
        render_js=body.render_js,
    )
    return summary


@router.get("/sites/{site_id}/jobs", response_model=list[JobOut])
async def list_jobs(
    site_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    uow=__import__("fastapi").Depends(get_uow),
) -> list[JobOut]:
    await _require_site(uow, site_id)
    page = await uow.jobs.list_for_site(site_id, limit=limit)
    return [
        JobOut(
            id=j.id,
            site_id=j.site_id,
            status=j.status.value,
            url_count=j.url_count,
            pages_crawled=j.pages_crawled,
            error=j.error,
            started_at=j.started_at,
            finished_at=j.finished_at,
        )
        for j in page.items
    ]


# --------------------------------------------------------------------------
# 报告
# --------------------------------------------------------------------------


@router.get("/sites/{site_id}/issues", response_model=IssuePage)
async def list_issues(
    site_id: int,
    severity: Optional[str] = None,
    code: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    uow=__import__("fastapi").Depends(get_uow),
) -> IssuePage:
    await _require_site(uow, site_id)
    page = await uow.issues.list(
        site_id,
        severity=severity,
        code=code,
        limit=limit,
        offset=offset,
    )
    return IssuePage(
        total=page.total,
        items=[
            IssueOut(
                id=i.id,
                code=i.code,
                severity=i.severity.value,
                scope=i.scope.value,
                url=i.url,
                title=i.title,
                fingerprint=i.fingerprint,
                status=i.status.value,
                occurrences=i.occurrences or 1,
            )
            for i in page.items
        ],
        has_next=offset + len(page.items) < page.total,
    )


@router.get("/sites/{site_id}/report", response_model=ReportSummary)
async def report(site_id: int, uow=__import__("fastapi").Depends(get_uow)) -> ReportSummary:
    """最新一次扫描的汇总。

    ⚠️ 0 页成功时 ``health_score`` 必须是 ``null`` 而不是 0 ——
    「一页没抓到」和「抓到了但全是问题」是两回事，不能都报 0 分。
    """
    site = await _require_site(uow, site_id)
    jobs = await uow.jobs.list_for_site(site_id, limit=1)
    # count_by_severity 一次返回 dict，且只统计 OPEN 状态的问题。
    # 缺失的 severity 必须补 0：前端按 key 取值，缺 key 会渲染成 undefined。
    raw_counts = await uow.issues.count_by_severity(site_id)
    counts: dict[str, int] = {sev.value: raw_counts.get(sev.value, 0) for sev in m.Severity}
    issues_page = await uow.issues.list(site_id, limit=200)
    items = [
        IssueOut(
            id=i.id,
            code=i.code,
            severity=i.severity.value,
            scope=i.scope.value,
            url=i.url,
            title=i.title,
            fingerprint=i.fingerprint,
            status=i.status.value,
            occurrences=i.occurrences or 1,
        )
        for i in issues_page.items
    ]
    pages_crawled = jobs.items[0].pages_crawled if jobs.items else 0
    return ReportSummary(
        domain=site.domain,
        pages_crawled=pages_crawled,
        counts=counts,
        health_score=None if pages_crawled == 0 else _latest_score(jobs),
        issues=items,
    )


def _latest_score(jobs) -> float | None:
    breakdown = None
    if jobs.items:
        breakdown = getattr(jobs.items[0], "score_breakdown", None)
    if isinstance(breakdown, dict):
        v = breakdown.get("health_score")
        if isinstance(v, (int, float)):
            return float(v)
    return None