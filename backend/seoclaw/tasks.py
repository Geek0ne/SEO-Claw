"""持久任务队列的执行器：认领 → 执行 → 收尾，进程重启不丢活儿。

## 形态选择：进程内 worker 循环，不上 Celery

一次体检就是「爬一个站」，几十秒到几分钟；上 Celery 要先养 Redis +
独立 worker 进程，对当前量级是运维成本远超收益。这里做的是**每个
web 进程各跑一个循环**，靠数据库的原子认领互斥——多 worker 部署天然
安全，将来真要独立扩容，把 :func:`worker_loop` 搬进独立进程即可，
队列表的语义一行不用改。

## 任务发现：唤醒事件 + 慢轮询兜底

- 同进程提交：enqueue 后置唤醒事件，任务**秒级**开跑（体感）；
- 跨进程提交（另一个 worker 收的请求）：靠 ``poll_interval`` 慢轮询发现。
  两个都留，是因为只靠轮询会让单机用户白等一个轮询周期，只靠事件则
  多 worker 部署下任务会滞留。

## 崩溃恢复

启动时调 :func:`recover_stale`：running 超过阈值还没终态的行 = 认领它的
进程已经死了。给一次重试机会（attempts 未超限则回 pending），否则标
failed——**绝不留下永远 running 的行**，那等于让用户对着不动的进度条等。
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from .db.repository import ScanTaskRepository
from .db.session import get_session_factory

log = logging.getLogger(__name__)

#: 同时在跑的任务上限（跨 worker 的咨询式上限，见 claim_next 注释）。
#: 为什么是 2：一次体检峰值内存约 100 MB（实测），2 并发留足余量；
#: 再多对 512 MB 的小实例就是自杀。
MAX_CONCURRENT = 2

#: 队列深度上限。满了拒收而不是无限排队——兑现不了的排队承诺
#: （「你前面还有 30 个任务」）比当场说「现在忙」更伤信任。
MAX_PENDING = 50

#: 唤醒事件：同进程 enqueue 后立刻开跑。跨进程靠轮询兜底。
#: ⚠️ 不能在模块 import 时创建：asyncio.Event 首次使用就绑定当时的事件
#: 循环，下一个 TestClient 的新循环再碰它就是「bound to a different event
#: loop」。按循环惰性重建（生产一进程一循环，永远只建一次）。
_WAKE: Optional[asyncio.Event] = None
_WAKE_LOOP: Optional[asyncio.AbstractEventLoop] = None


def _event() -> asyncio.Event:
    """取当前循环的唤醒事件；换循环（测试的下一个 TestClient）则重建。"""
    global _WAKE, _WAKE_LOOP
    loop = asyncio.get_running_loop()
    if _WAKE is None or _WAKE_LOOP is not loop:
        _WAKE = asyncio.Event()
        _WAKE_LOOP = loop
    return _WAKE

#: running 行超过这个秒数还不到终态，视为孤儿（进程已死）。
#: 取值要盖过最长合理扫描（500 页 × 3rps ≈ 3 分钟）再多给余量；
#: 太短会把活人的任务误判成孤儿，太长则崩掉的进程拖着队列。
DEFAULT_STALE_S = float(os.getenv("SEO_CLAW_TASK_STALE_S", "900"))


def wake() -> None:
    """通知 worker：有新活了。"""
    _event().set()


async def recover_stale(older_than_seconds: Optional[float] = None) -> int:
    """启动时调用。返回捞回的条数。

    阈值不传时**调用时**读环境变量（不是 import 时绑死默认值）——
    测试要能在不重载模块的前提下改它。
    """
    if older_than_seconds is None:
        older_than_seconds = float(os.getenv("SEO_CLAW_TASK_STALE_S", "900"))
    async with get_session_factory()() as session:
        n = await ScanTaskRepository(session).recover_stale(
            older_than_seconds=older_than_seconds
        )
        await session.commit()
    if n:
        log.info("启动恢复：%d 个中断任务已重新排队/收尾", n)
    return n


async def _execute(task_id: int) -> None:
    """跑一个已认领的任务。内部失败落 failed；异常尽量自己消化。"""
    # ⚠️ 延迟导入 + import 形式是给测试留的口子：
    # 测试 monkeypatch 的是 `seoclaw.api.scan_service.run_scan`，
    # 只有在这里现 import 才能拿到替换后的实现。
    from .api.scan_service import run_scan

    try:
        async with get_session_factory()() as session:
            repo = ScanTaskRepository(session)
            task = await repo.get(task_id)
            if task is None:
                return
            summary = await run_scan(
                session,
                site_id=task.site_id,
                url=task.url,
                markets=list(task.markets or []),
                max_pages=task.max_pages,
                max_depth=task.max_depth,
                respect_robots=task.respect_robots,
                render_js=task.render_js,
            )
            # run_scan 自己不提交（API 层由 deps 的 finally 提交），这里必须
            # 自己 commit，否则报告随连接关闭一起蒸发。
            await session.commit()
            await repo.finish(task_id, summary)
            await session.commit()
            log.info(
                "任务完成 task_id=%s health=%s issues=%s",
                task_id,
                summary.get("health_score"),
                summary.get("issue_count"),
            )
    except Exception as exc:  # noqa: BLE001 —— 任务失败必须落库，绝不留 running
        try:
            async with get_session_factory()() as session:
                await ScanTaskRepository(session).fail(
                    task_id, f"{type(exc).__name__}: {exc}"
                )
                await session.commit()
        except Exception:  # noqa: BLE001 —— 落库失败不能盖掉原始异常的痕迹
            log.exception("任务失败连落库都失败 task_id=%s", task_id)
        log.error("任务失败 task_id=%s：%s: %s", task_id, type(exc).__name__, exc)


async def worker_loop(
    *, poll_interval: float = 1.5, max_concurrent: int = MAX_CONCURRENT
) -> None:
    """队列主循环。放进事件循环跑，进程退出时由 lifespan 取消。"""
    while True:
        try:
            async with get_session_factory()() as session:
                task = await ScanTaskRepository(session).claim_next(
                    max_running=max_concurrent
                )
                await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 —— 队列查询抖一下不该弄死循环
            log.exception("队列查询失败，稍后重试")
            task = None

        if task is None:
            # 没活干：等唤醒事件，超时则走慢轮询（发现别的进程提交的任务）。
            ev = _event()
            try:
                await asyncio.wait_for(ev.wait(), timeout=poll_interval)
            except asyncio.TimeoutError:
                pass
            ev.clear()
            continue

        try:
            await _execute(task.id)
        except asyncio.CancelledError:
            # 进程关闭正在取消我们：任务行留在 running，
            # 下次启动 recover_stale 会捞回——这是设计内的行为。
            raise
        except Exception as exc:  # noqa: BLE001 —— _execute 之外的兜底（如 import 失败）
            log.exception("任务执行器未捕获异常 task_id=%s", task.id)
            try:
                async with get_session_factory()() as session:
                    await ScanTaskRepository(session).fail(
                        task.id, f"执行器异常：{type(exc).__name__}: {exc}"
                    )
                    await session.commit()
            except Exception:  # noqa: BLE001
                log.exception("兜底落库也失败 task_id=%s", task.id)
