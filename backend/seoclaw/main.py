"""FastAPI 应用入口。

启动：
    PYTHONPATH=.deps:backend DATABASE_URL=sqlite+aiosqlite:///./seo_agent.db \
      python3 -m uvicorn seoclaw.main:app --port 8000
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from .api.auth import auth_middleware
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .db.session import create_all, dispose_engine
from .log import configure
from .web import router as web_router

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # 结构化日志（log.py）：级别/格式由 SEO_CLAW_LOG_LEVEL / _FORMAT 控制。
    # 放 lifespan 而不是模块导入时：import seoclaw.main 不该有全局副作用
    # （测试和 CLI 都会 import 它）。
    configure()
    # ⚠️ 这里是 create_all 而非跑 Alembic 迁移。
    # 它只保证「空库能跑起来」，**不会给已有库补新列**——那必须走
    # `alembic upgrade head`。两者的区别要讲清楚，否则上线时新增字段
    # 会只在测试里生效（测试每次建新库），生产直接 500。
    await create_all()
    # 任务队列：先捞回上个进程死掉时留下的孤儿任务，再启动执行器。
    # 顺序反了会让孤儿任务和新任务抢并发额度。
    from . import tasks as task_queue

    await task_queue.recover_stale()
    worker = asyncio.create_task(task_queue.worker_loop())
    # 定时扫描调度（阶段 2b）：把到期的托管站点变成队列任务。
    # 与 worker 同生共死——先停它们再关库（顺序见 finally）。
    from . import scheduler as scan_scheduler

    sched = asyncio.create_task(scan_scheduler.scheduler_loop())
    try:
        yield
    finally:
        # 先停 worker/调度再关库：反过来它们会在关库后拿连接，报错刷屏。
        # 取消时正在跑的任务行会留在 running，下次启动由 recover_stale 捞回。
        for t in (sched, worker):
            t.cancel()
        # ⚠️ 有界等待，绝不无界 await——这是实测踩出来的（0008 阶段）：
        # 取消落在 SQLAlchemy 异步驱动的 greenlet 交接区时，任务会吊死在
        # 没人置位的 future 上（实测栈：worker 卡在 aiosqlite 的
        # `AsyncAdapt_aiosqlite_connection._terminate_graceful_close` 的
        # asyncio.shield 里，aiosqlite 线程已空闲、close future 却永远
        # 不完成），无界 await 会把 lifespan 收尾、TestClient 关闭、
        # 进程退出一起拖死。症状极具迷惑性：测试套件**随机挂起**，
        # 挂哪条取决于取消命中哪个数据库操作（窗口期就是每个 DB 调用的
        # 毫秒级瞬间，启动时连续三个 DB 调用，命中率最高）。
        # 到点就走：进程即将退出，吊死的任务随进程消失——为「优雅」
        # 无限期挂住不优雅。2s 盖过正常收尾（毫秒级）三个数量级，
        # 又不会让命中吊死的测试用例慢到不可忍。
        _done, _stuck = await asyncio.wait({sched, worker}, timeout=2)
        if _stuck:
            log.warning("后台任务取消后 2s 未退出（%d 个），放弃等待", len(_stuck))
        # dispose 同理有界：同一类吊死可能发生在连接关闭的 greenlet
        # 交接里。用 task + asyncio.wait 而不是 wait_for——wait_for
        # 超时后还会等取消完成，对吊死的任务同样会永久挂住。
        _dispose = asyncio.create_task(dispose_engine())
        _done, _stuck = await asyncio.wait({_dispose}, timeout=2)
        if _stuck:
            log.warning("数据库连接池关闭超时，放弃等待（进程即将退出）")


def create_app() -> FastAPI:
    app = FastAPI(
        title="SEO-Claw",
        version="0.1.0",
        description="站点 SEO 健康审计服务",
        lifespan=lifespan,
    )
    # ⚠️ 鉴权做成中间件而不是逐端点加参数：站点相关端点有 15 个，
    # 逐个加意味着以后新增端点时**忘了加就会静默越权**，而漏掉的那一个
    # 不会报错、只会放行 —— 那是最坏的失败方式。
    app.middleware("http")(auth_middleware)
    app.include_router(router)
    app.include_router(web_router)

    # 页面与静态资源放在包内，随 wheel 一起装走。
    # 用 StaticFiles 挂整个目录而不是只挂 index.html：以后加 favicon、
    # 埋点脚本、样式拆分都不用改代码。
    static_dir = Path(__file__).parent / "web" / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(static_dir / "index.html")

    return app


app = create_app()
