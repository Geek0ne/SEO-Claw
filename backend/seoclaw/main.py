"""FastAPI 应用入口。

启动：
    PYTHONPATH=.deps:backend DATABASE_URL=sqlite+aiosqlite:///./seo_agent.db \
      python3 -m uvicorn seoclaw.main:app --port 8000
"""

from __future__ import annotations

import asyncio
import contextlib
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
    try:
        yield
    finally:
        # 先停 worker 再关库：反过来 worker 会在关库后拿连接，报错刷屏。
        # 取消时正在跑的任务行会留在 running，下次启动由 recover_stale 捞回。
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker
        await dispose_engine()


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
