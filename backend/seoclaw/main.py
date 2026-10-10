"""FastAPI 应用入口。

启动：
    PYTHONPATH=.deps:backend DATABASE_URL=sqlite+aiosqlite:///./seo_agent.db \
      python3 -m uvicorn seoclaw.main:app --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from .api.auth import auth_middleware
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .db.session import create_all, dispose_engine
from .web import router as web_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # ⚠️ 这里是 create_all 而非跑 Alembic 迁移。
    # 它只保证「空库能跑起来」，**不会给已有库补新列**——那必须走
    # `alembic upgrade head`。两者的区别要讲清楚，否则上线时新增字段
    # 会只在测试里生效（测试每次建新库），生产直接 500。
    await create_all()
    try:
        yield
    finally:
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
