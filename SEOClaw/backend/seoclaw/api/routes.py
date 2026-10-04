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
    IssueBulkStatusIn,
    IssueOut,
    IssuePage,
    IssueStatusIn,
    JobOut,
    ReportSummary,
    ScanRequest,
    ScorePoint,
    ScoreTrend,
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


def _issue_out(i: m.Issue) -> IssueOut:
    """Issue → 出参。

    ⚠️ 抽出来是因为这段构造在 list_issues / update_issue_status 两处各写了一遍。
    以后给 IssueOut 加字段，漏改一处就会出现「列表里没有、详情里有」。
    """
    return IssueOut(
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


@router.patch("/sites/{site_id}/issues/{issue_id}", response_model=IssueOut)
async def update_issue_status(
    site_id: int,
    issue_id: int,
    body: IssueStatusIn,
    uow=__import__("fastapi").Depends(get_uow),
) -> IssueOut:
    """把一条问题标成「已修 / 已知悉 / 忽略」。

    没有这条，这个产品就只是个只读报告：扫出一百条，用户改完了
    系统却永远显示那一百条还在——扫完就没有闭环了。

    ⚠️ **必须校验归属**：站点是租户边界。不校验的话
    ``PATCH /sites/1/issues/9999`` 会把 2 号站点的问题改掉，
    而调用方拿到的是 200 —— 越界写入比 404 难查得多。
    """
    await _require_site(uow, site_id)
    issue = await uow.issues.get(issue_id)
    if issue is None or issue.site_id != site_id:
        # 归属不对也说 404：说「那条存在但不属于你」等于泄露了别的站点
        # 有什么问题，而用户压根没有查询别人的资格。
        raise HTTPException(status_code=404, detail=f"问题不存在：{issue_id}")
    # ⚠️ 必须转成枚举再赋值。Literal 校验出来的是 str，而列的类型是
    # IssueStatus：塞 str 不会立刻报错，只在出参时炸
    # `AttributeError: 'str' object has no attribute 'value'`。
    # 这类「写入不报错、读取才炸」的错最难查，必须在写入口就转好。
    issue.status = m.IssueStatus(body.status)
    await uow.session.flush()
    return _issue_out(issue)


@router.patch("/sites/{site_id}/issues", response_model=dict)
async def bulk_update_issue_status(
    site_id: int,
    body: IssueBulkStatusIn,
    uow=__import__("fastapi").Depends(get_uow),
) -> dict:
    """按根因批量改状态（「这一类我都处理了」）。

    ⚠️ 刻意**不提供全选兜底**：一次把全站几百条标成「已修」极易点错，
    而这个操作没有 undo —— 状态只能一条条改回来。批量必须指明根因。
    """
    await _require_site(uow, site_id)
    n = await uow.issues.resolve_by_fingerprint(site_id, body.fingerprint, body.status)
    return {"updated": n}


@router.get("/sites/{site_id}/trend", response_model=ScoreTrend)
async def trend(site_id: int, uow=__import__("fastapi").Depends(get_uow)) -> ScoreTrend:
    """分数随时间的变化 —— 趋势线数据。

    ⚠️ 两个坑，都在这行代码里体现：

    1. **只取算得出分数的那几次。** 0 页成功时 health_score 是 null，
       那是「什么都没看到」而不是「0 分」。把它画进趋势线，会让一条
       明明没抓到的扫描看起来像暴跌 —— **用一个抓取失败冒充一次质量下滑，
       是比不画更糟的谎**。所以 ``score is None`` 的直接跳过。

    2. **按时间升序返回。** DB 默认是 ``id DESC``（新的在前），直接吐给前端
       连线会画成一条反着的线，而这种错在图上看不出来，只会看起来「不对」，
       极难自查。所以这里显式 reverse。
    """
    site = await _require_site(uow, site_id)
    page = await uow.jobs.list_for_site(site_id, limit=100)
    points: list[ScorePoint] = []
    for job in reversed(page.items):  # 最老的在前
        if getattr(job, "health_score", None) is None:
            continue
        points.append(
            ScorePoint(
                job_id=job.id,
                score=job.health_score,
                pages_crawled=job.pages_crawled,
                status=job.status.value,
                finished_at=job.finished_at,
            )
        )
    return ScoreTrend(site_id=site_id, domain=site.domain, points=points)


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
        _issue_out(i) for i in issues_page.items
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
    """取最近一次扫描的健康分。

    ⚠️ 以前这里读 ``job.score_breakdown`` 字典，而 crawl_jobs **压根没有
    这一列**（已由 0002_job_scores 补上，但老数据还是 null）→ 属性读不到
    → 返回 None → 接口 health_score 恒为 null → 前端按「一页都没抓到」
    渲染。**分数算了、接口也返回了，却从没存下来。**

    现在读 ``job.health_score`` 这条真列。老库没跑过迁移时它不存在，
    故用 getattr 兜底成 None，而不是直接抛 AttributeError 把接口打挂。
    """
    if not jobs.items:
        return None
    v = getattr(jobs.items[0], "health_score", None)
    return float(v) if isinstance(v, (int, float)) else None