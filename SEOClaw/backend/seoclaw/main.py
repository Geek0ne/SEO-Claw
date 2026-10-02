"""FastAPI 应用入口。

启动：
    PYTHONPATH=.deps:backend DATABASE_URL=sqlite+aiosqlite:///./seo_agent.db \
      python3 -m uvicorn seoclaw.main:app --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from .api import router
from .db.session import create_all, dispose_engine


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
        title="SEOClaw",
        version="0.1.0",
        description="站点 SEO 健康审计服务",
        lifespan=lifespan,
    )
    app.include_router(router)
    return app


app = create_app()
