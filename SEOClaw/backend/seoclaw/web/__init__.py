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

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..db import repository as repo
from ..db.session import get_session_factory
from .guard import (
    BlockedTarget,
    check_denied,
    client_ip,
    public_limiter,
    resolve_and_check,
)

router = APIRouter(prefix="/api/v1/web")

# ⚠️ 进程内存态。重启服务进度就没了（后台任务本身也一起没了，
# 这是BackgroundTasks 的固有性质）。所以前端拿到 job_id 后如果查不到，
# 必须显示「任务已失效，请重试」而不是无限转圈——
# 一个永远转圈的进度条比报错糟糕得多。
_TASKS: dict[int, dict[str, Any]] = {}
# asyncio.Task 对象 → job_id。done_callback 只给Task，得靠它反查是哪个体检。
_JOB_OF_TASK: dict[int, int] = {}

# 内存任务号自增。与 crawl_jobs.id 完全无关，别混用。
_NEXT_ID = [0]


def _next_id() -> int:
    _NEXT_ID[0] += 1
    return _NEXT_ID[0]
_MAX_TASKS = 500  # 内存上限：超过就丢最老的，防止长期运行被撑爆

# --------------------------------------------------------------------------
# 并发闸
# --------------------------------------------------------------------------
# ⚠️ 限流挡的是「一个人狂刷」，挡不住「一群人各刷一次」。
# 10 个不同 IP 各提交一次 = 10 个爬虫同时跑：内存被吃掉十倍，
# 而更要命的是**服务器 IP 被 10 个目标站同时扫**——被按 IP 拉黑之后，
# 整台机器的对外访问都废了，不只这个服务。
#
# 为什么是 2：一次体检 100MB 峰值内存（实测 15 页），2 并发留足余量；
# 再多对 512MB 的免费实例就是自杀。
#: 同时在跑的上限。⚠️ 这里**没有队列**——`create_task` 是提交即开跑，
#: 所以要么现在跑，要么当场拒。上一版我写了个「队列上限」纯属虚构：
#: 用户的体感是「我等 5 分钟轮到我」，而实际上没人给他排队。
#: 与其给一个兑现不了的承诺，不如直接说「现在忙，一分钟后再来」。
_MAX_CONCURRENT = 2

#: 当前在跑的数量。用**单个整数**而不是 Semaphore：
# 这里要的只是「计数 + 超阈值就拒」，不需要真的阻塞等待；
# 而 asyncio.Semaphore 在多 event loop 下会跨 loop 出问题
# （测试里 TestClient 每个用例一个新 loop，正是这么炸的）。
_INFLIGHT = [0]


def _remember(job_id: int, payload: dict[str, Any]) -> None:
    if len(_TASKS) >= _MAX_TASKS:
        for old in sorted(_TASKS)[: len(_TASKS) - _MAX_TASKS + 1]:
            _TASKS.pop(old, None)
    _TASKS[job_id] = payload


class QuickScanRequest(BaseModel):
    """一次体检的入参。

    ⚠️ 这几个开关不能只做在界面上：界面上摆一个「渲染 JS」的勾选框、
    后端不接，用户勾了发现跟没勾一样——那比没有这个框更糟。
    这里声明了就一路传到 ``run_scan``，前后端对得上。
    """

    url: str = Field(min_length=4, max_length=500)
    max_pages: int = Field(default=30, ge=1, le=500)
    market: str = Field(default="base")
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

    # ⚠️ 并发闸必须在**建站落库之前**。否则被拒的请求已经在库里留了
    # 一个孤儿 site——攻击者可以靠「提交即被拒」白刷一堆垃圾站点。
    if _INFLIGHT[0] >= _MAX_CONCURRENT:
        raise HTTPException(
            status_code=503,
            detail=f"现在有 {_INFLIGHT[0]} 个体检正在跑（一台机器同时只能跑 "
            f"{_MAX_CONCURRENT} 个）。过一两分钟再来试。",
            headers={"Retry-After": "60"},
        )
    _INFLIGHT[0] += 1

    # ⚠️ `async with session:` **不等于提交**——它只负责关闭连接。
    # 我第一版写成这样，站点压根没落库，后台建任务时立刻
    # `FOREIGN KEY constraint failed`。这跟 API 层 deps.py 里
    # 老老实实 `await session.commit()` 是同一件事的两面。
    async with get_session_factory()() as session:
        site_id = await get_or_create_site(session, url, markets=[body.market])
        await session.commit()

    # 内存任务号，**不占crawl_jobs 的 id**。
    # ⚠️ 我第一版在这里 create_crawl_job 了一次，可 run_scan 内部还会再建一次
    # —— 一次体检留下两条任务记录，jobs 列表会看到重复的 PENDING。
    # 真正的 crawl_jobs 由 run_scan 负责建，这里的号只用于前端轮询。
    job_id = _next_id()

    _remember(job_id, {
        "status": "running",
        "started": time.monotonic(),
        "domain": domain,
        "url": url,
        "error": None,
    })

    # ⚠️ create_task 的异常**默认没人接**。我第一版就写成裸的 create_task，
    # 结果一个 ModuleNotFoundError 把任务永远卡在 running —— 而我在文件
    # 顶部刚写过「静默留在 running 会变成永远转圈的进度条」，自己先犯了。
    # done_callback 是唯一的兜底：任何没进 _run 内部 try 的异常
    # （包括 import 失败）都会走到这里，变成前端看得见的 failed。
    task = asyncio.create_task(
        _run(
            job_id, site_id, url, body.max_pages, body.market,
            max_depth=body.max_depth,
            respect_robots=body.respect_robots,
            render_js=body.render_js,
        )
    )
    _JOB_OF_TASK[id(task)] = job_id
    task.add_done_callback(_on_task_done)
    return QuickScanAccepted(job_id=job_id, site_id=site_id, domain=domain)


async def _run(
    job_id: int,
    site_id: int,
    url: str,
    max_pages: int,
    market: str,
    *,
    max_depth: int = 6,
    respect_robots: bool = True,
    render_js: bool = False,
) -> None:
    """后台跑一次体检，把进度与终态写进 ``_TASKS``。

    ⚠️ 自己开 session：请求早已返回、它那个 session 已被关闭，
    复用会直接抛「session is closed」。
    """
    from ..api.scan_service import run_scan

    try:
        async with get_session_factory()() as session:
            summary = await run_scan(
                session,
                site_id=site_id,
                url=url,
                markets=[market],
                max_pages=max_pages,
                max_depth=max_depth,
                respect_robots=respect_robots,
                render_js=render_js,
            )
            # ⚠️ run_scan 自己不提交（它的调用方 API 层靠 deps 的 finally 提交）。
            # 这里没有 deps，必须自己 commit，否则页面拿到的是空报告——
            # 数据还在会话里躺着，随连接关闭一起没了。
            await session.commit()
            _remember(job_id, {
                **(_TASKS.get(job_id, {})),
                "status": "done",
                "report": summary,
                "error": None,
            })
    except Exception as exc:  # noqa: BLE001
        # 任务失败必须让前端看得见。静默留在 running 会变成永远转圈的进度条。
        _remember(job_id, {
            **_TASKS.get(job_id, {}),
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        })



def _on_task_done(task: "asyncio.Task") -> None:
    """任务整体的兜底异常处理。

    :func:`_run` 内部已经try 了业务异常，但**它自己 import 失败**时
    那一行就会在 try 之前炸掉 —— 那种异常没人接，任务永远停在 running。
    这里统一收口。

    并发计数的释放也放这里，而不是 ``_run`` 的 finally——因为
    ``from ..api.scan_service import run_scan`` 那行在 ``try`` **上面**，
    import 失败时 finally 根本不会执行，计数器就永远减不掉。
    done_callback 是保证「恰好一次」的唯一钩子。
    """
    _INFLIGHT[0] = max(0, _INFLIGHT[0] - 1)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is None:
        return
    job_id = _JOB_OF_TASK.get(id(task))
    if job_id is None:
        return
    _remember(job_id, {
        **_TASKS.get(job_id, {}),
        "status": "failed",
        "error": f"{type(exc).__name__}: {exc}",
    })


@router.get("/jobs/{job_id}", response_model=JobStatus)
async def job_state(job_id: int) -> JobStatus:
    task = _TASKS.get(job_id)
    if task is None:
        # 404 而不是「还在跑」：进程重启会清空这张表，
        # 谎称 running 会让用户对着永远不动的进度条等下去。
        raise HTTPException(404, "任务不存在或服务已重启，请重新发起体检")
    return JobStatus(
        status=task["status"],
        elapsed=round(time.monotonic() - task.get("started", time.monotonic()), 1),
        error=task.get("error"),
        report=task.get("report"),
    )


__all__ = ["router", "QuickScanRequest", "QuickScanAccepted", "JobStatus"]