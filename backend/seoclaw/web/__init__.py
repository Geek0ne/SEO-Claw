"""Web 端：一步式体检（输网址 → 出报告）。

## 为什么不直接用 `/api/v1/sites/{id}/scan`

那个端点是**同步等**的：`await run_scan(...)` 会等到爬完（100 页约 40 秒）。
浏览器里发这种请求，用户盯着转圈等一分钟，然后大概率以为卡死了。

所以这里另起一套「立即返回 + 轮询」的流程：

    POST /api/v1/web/quick-scan   → {job_id, site_id}（秒回）
    GET  /api/v1/web/jobs/{id}    → 进度 / 终态

## 为什么用 BackgroundTasks 而不是 Celery

一次体检就是「爬一个站」，几十秒，没有跨机调度、没有重试队列。
上Celery 意味着先部署 Redis + 一个 worker 进程——为了几十秒的任务，
运维成本远超收益。等真要做「每天定时扫 500 个站」时再换，
届时接口形状不用变，只是把 `_spawn` 换成投递队列。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..db.repository import ScanTaskRepository, as_utc
from ..db.session import get_session_factory
from .. import tasks as task_queue
from .guard import (
    BlockedTarget,
    check_denied,
    client_ip,
    public_limiter,
    resolve_and_check,
)

router = APIRouter(prefix="/api/v1/web")

log = logging.getLogger(__name__)

# ⚠️ 任务状态已落库（scan_tasks 表 + seoclaw/tasks.py 的 worker）。
# 这里曾是进程内存的 _TASKS / _INFLIGHT / _NEXT_ID 三件套，三个硬伤：
# 重启全丢、多 worker 互相看不见、被杀进程留下永远 running 的僵局。
# 历史教训里最值钱的一条：上上版有人写过一个「队列上限」但没有队列——
# 用户体感是「我等 5 分钟轮到我」，而实际上没人给他排队。现在是真的队列，
# 这个承诺才配写进界面。
_MAX_CONCURRENT = task_queue.MAX_CONCURRENT
_MAX_PENDING = task_queue.MAX_PENDING



class QuickScanRequest(BaseModel):
    """一次体检的入参。

    ⚠️ 这几个开关不能只做在界面上：界面上摆一个「渲染 JS」的勾选框、
    后端不接，用户勾了发现跟没勾一样——那比没有这个框更糟。
    这里声明了就一路传到 ``run_scan``，前后端对得上。
    """

    url: str = Field(min_length=4, max_length=500)
    max_pages: int = Field(default=30, ge=1, le=500)
    market: str = Field(default="base")  # base/google/baidu/cnh_eco/geo（geo 为实验包）
    max_depth: int = Field(default=6, ge=1, le=12)
    # 前端单页很便宜（靠后端内存态），给得比 CLI 更宽松。
    respect_robots: bool = True
    render_js: bool = False


class QuickScanAccepted(BaseModel):
    job_id: int
    site_id: int
    domain: str


class JobStatus(BaseModel):
    status: str
    elapsed: float = 0.0
    error: Optional[str] = None
    report: Optional[dict[str, Any]] = None


def _normalize_url(raw: str) -> str:
    """补全协议。用户多半直接输 `example.com`。"""
    url = raw.strip()
    if not url:
        raise HTTPException(400, "请输入网址")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    if not parsed.netloc or "." not in parsed.netloc:
        raise HTTPException(400, f"看不出这是个网址：{raw}")
    return url


@router.post("/quick-scan", response_model=QuickScanAccepted, status_code=202)
async def quick_scan(body: QuickScanRequest, request: Request) -> QuickScanAccepted:
    """登记一次体检并**立即返回**，不等待爬取完成。"""
    from ..persist import get_or_create_site

    # ⚠️ 限流必须在**任何**昂贵动作之前。本地跑无所谓，公网上这是
    # 唯一的防线：不限流的话别人 for 循环就能把服务器 IP 当爬虫使，
    # 被目标站按 IP 拉黑后整台机器的对外访问都废了。
    ip = client_ip(request)
    allowed, retry_after = public_limiter.allow(ip)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"提交太频繁了，{retry_after:.0f} 秒后再试。"
            "每个 IP 每分钟最多 12 次。",
            headers={"Retry-After": str(max(1, int(retry_after)))},
        )

    url = _normalize_url(body.url)

    # 市场包白名单：geo 是实验包，点名才加载（run_scan 内部会拆包）。
    # 不认识的值直接拒——否则它会原样进 site.markets，变成一条谁都
    # 读不懂的数据。
    if body.market not in ("base", "google", "baidu", "cnh_eco", "geo"):
        raise HTTPException(400, f"未知的规则包：{body.market}")

    # ⚠️ SSRF 校验必须在落库之前。Web 端的本质是「用户给个网址，
    # 我们去访问它」——放到公网上等于把出网能力交给陌生人。
    # 少了这一步，`http://169.254.169.254/latest/meta-data/iam/...`
    # 会把该容器的 IAM 凭据原文吐出来。
    try:
        url = resolve_and_check(url)
    except BlockedTarget as exc:
        raise HTTPException(status_code=400, detail=f"不能扫这个目标：{exc}") from None

    # ⚠️ 黑名单在 SSRF 之后：先确认这是不是一个能安全访问的目标，
    # 再确认「这个目标允不允许被扫」。反过来就是拿黑名单当探测工具了。
    try:
        check_denied(urlparse(url).hostname or "")
    except BlockedTarget as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None

    domain = urlparse(url).netloc

    # ⚠️ 队列闸必须在**建站落库之前**。否则被拒的请求已经在库里留了
    # 一个孤儿 site——攻击者可以靠「提交即被拒」白刷一堆垃圾站点。
    async with get_session_factory()() as session:
        repo = ScanTaskRepository(session)
        if await repo.count_pending() >= _MAX_PENDING:
            # 队列满拒收是容量信号，必须留痕：长期观测才知道该不该扩 worker。
            log.warning("quick-scan 队列满被拒 ip=%s pending>=%s", ip, _MAX_PENDING)
            raise HTTPException(
                status_code=503,
                detail=f"队列里已有 {_MAX_PENDING} 个任务在排（同时只跑 "
                f"{_MAX_CONCURRENT} 个）。排队承诺必须兑现——与其收下排到"
                "天黑的活儿，不如明说现在忙。",
                headers={"Retry-After": "120"},
            )

        # ⚠️ `async with session:` **不等于提交**——它只负责关闭连接。
        # 我第一版写成这样，站点压根没落库，后台建任务时立刻
        # `FOREIGN KEY constraint failed`。这跟 API 层 deps.py 里
        # 老老实实 `await session.commit()` 是同一件事的两面。
        site_id = await get_or_create_site(session, url, markets=[body.market])
        task_row = await repo.enqueue(
            site_id=site_id,
            url=url,
            markets=[body.market],
            max_pages=body.max_pages,
            max_depth=body.max_depth,
            respect_robots=body.respect_robots,
            render_js=body.render_js,
        )
        await session.commit()

    # 同进程的 worker 被唤醒立刻开跑；跨进程的靠慢轮询兜底（tasks.py）。
    task_queue.wake()
    log.info("quick-scan 提交 task_id=%s site_id=%s url=%s", task_row.id, site_id, url)
    return QuickScanAccepted(job_id=task_row.id, site_id=site_id, domain=domain)


@router.get("/jobs/{job_id}", response_model=JobStatus)
async def job_state(job_id: int) -> JobStatus:
    async with get_session_factory()() as session:
        row = await ScanTaskRepository(session).get(job_id)
    if row is None:
        # 404 而不是「还在跑」：查不到就是真没有。任务落库后重启不再丢，
        # 这里的 404 是诚实的「没这个任务」，而不是「内存被清了」。
        raise HTTPException(404, "任务不存在")
    status = row.status.value
    if status == "pending":
        # 对前端仍报 running：界面只认「转圈 / done / failed」三态，
        # 「排队中」也该转圈。拆成独立状态留给阶段 2b 的前端改造。
        status = "running"
    # ⚠️ SQLite 返回 naive datetime，必须过 as_utc 再做减法，
    # 否则 aware − naive 直接 TypeError。
    start = as_utc(row.started_at)
    end = as_utc(row.finished_at) or datetime.now(timezone.utc)
    # 还没开跑（排队中/刚被捞回）报 0，不拿 created_at 算——那会把
    # 「排队等了多久」当成「跑了多久」，重排队的任务尤其离谱（实测报过
    # 2 亿秒）。
    elapsed = round(max(0.0, (end - start).total_seconds()), 1) if start else 0.0
    return JobStatus(
        status=status,
        elapsed=elapsed,
        error=row.error,
        report=row.result,
    )


__all__ = ["router", "QuickScanRequest", "QuickScanAccepted", "JobStatus"]