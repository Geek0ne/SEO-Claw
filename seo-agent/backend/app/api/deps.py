"""FastAPI 依赖注入。

每个请求一个 DB 会话（由 `db.session.get_session` 提供），扫描走
`run_scan`，其余仓储都挂同一个会话上。
"""

from __future__ import annotations

from typing import AsyncIterator

from ..db.repository import UnitOfWork
from ..db.session import get_session


async def get_uow() -> AsyncIterator[UnitOfWork]:
    """每请求一个 UnitOfWork：共享一个 session 与事务边界。"""
    async for session in get_session():
        uow = UnitOfWork(session)
        try:
            yield uow
        finally:
            await session.commit()