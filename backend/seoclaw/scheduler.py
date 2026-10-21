"""定时扫描调度：托管站点的到期复扫（改造阶段 2b）。

## 职责边界

调度器只做一件事：把「到期的托管站点」变成 `scan_tasks` 里的一条任务。
排队、并发、崩溃恢复全部交给 tasks.py 的队列——调度器不执行扫描，
也不碰 crawl_jobs。两边靠 `wake()` 衔接（同进程秒级开跑，跨进程靠
队列的慢轮询兜底）。

## 三个语义决策（每条都有测试钉着）

1. **推进先于入队，at-most-once**：CAS 认领（把 next_scan_at 推到下个
   周期）与入队在同一个事务里，认领在前。进程在提交前崩掉 = 这个周期
   整体作废、下个周期照常——**漏掉比双跑好**：双跑是给目标站双倍压力，
   漏跑只是晚看一次报告。对第三方站点，宁可少扫不可多扫。
2. **不叠任务**：站点已有 pending/running 任务时跳过入队，next_scan_at
   照常推进（按时间节奏走，不按完成节奏走）。扫描比周期长时，队列里
   不会越积越多。
3. **参数定格**：执行参数读 schedule_params 快照（托管开启时定格），
   不实时读站点设置。要改参数就重新提交托管。

另有一条背压规则：**队列满不认领**（不推进周期，留到下个 tick）。
「排队承诺必须兑现」是队列的底线，定时任务也不例外——宁可晚扫，
不接兑现不了的活。

## 失败语义

任务跑失败不影响调度：下个周期照常入队。复扫的意义是「持续盯着」，
一次失败不该让站点从此退出观察。
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from .db.repository import ScanTaskRepository, SiteRepository, utcnow
from .db.session import get_session_factory
from .tasks import MAX_PENDING, wake

log = logging.getLogger(__name__)

#: 调度 tick 间隔（秒）。60s 足够：托管复扫的最小周期是小时级，
#: 调度精度差一分钟没有任何产品影响。
DEFAULT_POLL_S = float(os.getenv("SEO_CLAW_SCHEDULE_POLL_S", "60"))


async def tick(*, now: Optional[datetime] = None, limit: int = 20) -> int:
    """扫一遍到期站点并入队。返回本次入队条数。

    每个到期站点：CAS 认领（推进 next_scan_at）→ 不叠任务守卫 → 入队。
    认领与入队同一事务：提交前崩掉则整体作废（见模块 docstring）。
    """
    now = now or utcnow()
    enqueued = 0
    async with get_session_factory()() as session:
        sites_repo = SiteRepository(session)
        task_repo = ScanTaskRepository(session)
        for site in await sites_repo.due_schedules(now=now, limit=limit):
            interval = site.scan_interval_s or 0
            if interval <= 0:  # due_schedules 已排除 NULL，这里是防御
                continue
            if await task_repo.has_active(site.id):
                # 上一轮还没跑完：不叠任务，但 next_scan_at 照常推进——
                # 按时间节奏走，扫描比周期长时队列不会越积越多。
                await sites_repo.claim_schedule(
                    site.id, now=now, next_scan_at=now + timedelta(seconds=interval)
                )
                log.info(
                    "定时复扫跳过（任务在跑）site_id=%s domain=%s",
                    site.id,
                    site.domain,
                )
                continue
            if await task_repo.count_pending() >= MAX_PENDING:
                # 队列满：不认领、不推进，留在 due 状态下个 tick 再试。
                # 与 web 端的拒收同一条底线，只是这里改「晚点再交」。
                log.warning("定时复扫暂缓（队列满）site_id=%s domain=%s", site.id, site.domain)
                continue
            claimed = await sites_repo.claim_schedule(
                site.id, now=now, next_scan_at=now + timedelta(seconds=interval)
            )
            if not claimed:
                # 被另一个调度实例抢了（多 worker 部署）。让给它。
                continue
            params = dict(site.schedule_params or {})
            await task_repo.enqueue(
                site_id=site.id,
                # ⚠️ 参数来自快照，缺省兜底才落到站点当前值——快照是
                # 「当初约好的」，站点当前值只是防快照残缺的保险丝。
                url=str(params.get("url") or f"https://{site.domain}"),
                markets=list(params.get("markets") or site.markets or ["base"]),
                max_pages=int(params.get("max_pages") or 30),
                max_depth=int(params.get("max_depth") or 6),
                respect_robots=bool(params.get("respect_robots", True)),
                render_js=bool(params.get("render_js", False)),
            )
            enqueued += 1
            log.info(
                "定时复扫已入队 site_id=%s domain=%s interval=%ss",
                site.id,
                site.domain,
                interval,
            )
        await session.commit()
    if enqueued:
        wake()  # 同进程 worker 立刻开跑；跨进程靠队列慢轮询
    return enqueued


async def scheduler_loop(*, poll_interval: Optional[float] = None) -> None:
    """调度主循环。放进事件循环跑，进程退出时由 lifespan 取消。

    poll_interval 不传时**启动时**读环境变量 ``SEO_CLAW_SCHEDULE_POLL_S``
    （测试靠 monkeypatch 环境变量拉小它，验证真的接上了）。
    """
    if poll_interval is None:
        poll_interval = float(os.getenv("SEO_CLAW_SCHEDULE_POLL_S", "60"))
    while True:
        try:
            await tick()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 —— 调度抖一下不该弄死循环
            log.exception("定时调度 tick 失败，稍后重试")
        await asyncio.sleep(poll_interval)
