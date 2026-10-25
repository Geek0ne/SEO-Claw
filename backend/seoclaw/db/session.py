"""异步引擎与会话管理。

设计取舍：

1. **引擎全局单例。** `create_async_engine` 会为每个连接分配一整个连接池，
   在 FastAPI 里每请求建一次引擎是经典的连接耗尽写法。这里用模块级惰性单例
   + 显式 `get_engine()` 获取。

2. **会话是"每单位工作一个"而不是"每请求一个"。**
   `session_scope()` 以 contextmanager 形式给出 commit/rollback 边界：
   抓取 Agent 可能跑几十分钟，把一次扫描切成上百个事务，而不是把整场扫描
   压进一个巨型事务（那样既锁行又会让回滚丢掉整场成果）。

3. **同时给出同步 URL 转换。** Alembic 迁移跑在同步 engine 上，而应用跑在
   async engine 上；两边必须指向同一个库。`to_sync_url` / `to_async_url`
   保证驱动名转换不会漏（asyncpg ↔ psycopg，SQLite aiosqlite ↔ sqlite）。

4. **URL 从环境变量读，不硬编码。** 12-factor：容器里只换 env 就能从
   SQLite 切到 PG。
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .models import Base

# 默认库：本地开发用文件型 SQLite，零配置可跑。
# 生产通过 DATABASE_URL 覆盖成 postgresql+asyncpg://...
DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./seoclaw.db"


def get_database_url() -> str:
    """读取数据库连接串。

    优先用 ``DATABASE_URL``；同时兼容 ``SEO_CLAW_DATABASE_URL``（改名前的
    旧名 ``SEO_AGENT_DATABASE_URL`` 保留为后门，删掉会让已有部署静默
    指向另一个库 —— 不报错，只是数据看不见）。

    ``SEO_CLAW_DATABASE_URL`` 排在 ``SEO_AGENT_DATABASE_URL`` 之前。
    """
    return (
        os.getenv("SEO_CLAW_DATABASE_URL")
        or os.getenv("SEO_AGENT_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or DEFAULT_DATABASE_URL
    )


def to_sync_url(url: str) -> str:
    """把 async URL 转成 Alembic 用的同步 URL。

    Alembic 的 autogenerate 用同步 engine 连接数据库做反射，asyncpg 的
    连接串必须换成同步驱动，否则 alembic 会在建连接时挂住。
    """
    if url.startswith("postgresql+asyncpg://"):
        # 同步侧统一走 psycopg2：它是 PG 生态默认驱动，Alembic 对它的
        # 支持最完整（类型反射、CHECK 约束识别都无需额外配置）。
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    if url.startswith("sqlite+aiosqlite://"):
        return url.replace("sqlite+aiosqlite://", "sqlite://", 1)
    return url


def to_async_url(url: str) -> str:
    """把同步 URL 转成 async URL（供测试/工具复用同步配置时用）。"""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("sqlite://") and "+aiosqlite" not in url:
        return url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    return url


_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def create_engine_from_url(
    url: Optional[str] = None, *, echo: bool = False
) -> AsyncEngine:
    """按连接串新建引擎（不写全局单例）。

    测试用它为每个用例造独立内存库 —— 引擎和连接池的生命周期必须跟
    测试一一对应，否则用例间会串数据。
    """
    target = url or get_database_url()
    kwargs: dict = {"echo": echo, "future": True}
    # ⚠️ StaticPool 只该给内存库：它让全进程共享唯一一条连接，任何会话
    # close() 时的池 reset 都会把别人未提交的事务一并回滚（2026-10-25
    # 容器实测：worker 长事务插完 crawl_jobs/pages 未提交，轮询会话一关，
    # issues 插入即 FOREIGN KEY constraint failed，整场扫描丢失）。
    # 文件库必须用默认连接池。判定口径：显式 :memory: / mode=memory，
    # 或去掉尾斜杠后就是裸 scheme（"sqlite:" / "sqlite+aiosqlite:"）。
    if target.startswith("sqlite") and (
        "memory" in target
        or target.rstrip("/").endswith(("sqlite:", "sqlite+aiosqlite:"))
    ):
        # 内存 SQLite 每次连接都是一个全新库，跨连接看不到对方的表。
        # 强制 StaticPool + 共享 cache，保证同一引擎内多连接看到同一份数据。
        from sqlalchemy.pool import StaticPool

        kwargs.update(
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    engine = create_async_engine(target, **kwargs)
    if target.startswith("sqlite"):
        _enable_sqlite_foreign_keys(engine)
    return engine


def _enable_sqlite_foreign_keys(engine: AsyncEngine) -> None:
    """让 SQLite 真正执行外键约束。

    SQLite 默认 ``PRAGMA foreign_keys=OFF``，也就是说 `ON DELETE CASCADE`
    和 `ON DELETE SET NULL` 全都形同虚设 —— 本地/测试环境下删站点会留下
    孤儿 pages 和 issues，而生产 PG 上却是干净的。这类"测试通过、生产才炸"
    的差异正是最贵的 bug，所以这里显式打开。

    必须在**每条连接**上设置，而 pragma 不是连接池级别的配置，因此挂到
    connect 事件上。
    """
    from sqlalchemy import event

    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragma(dbapi_connection, _record) -> None:  # pragma: no cover - 回调
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


def _dispose_engine_sync() -> None:
    """在**同步**上下文里关掉连接池并清空单例。

    ⚠️ 之前 ``get_engine()`` 直接调 async 的 ``dispose_engine()``，
    协程对象从没被 await：旧连接池**根本没关**，只是把全局引用置空。
    现象是运行时报
    ``RuntimeWarning: coroutine 'dispose_engine' was never awaited``——
    实测 2026-10-02 跑 ``scan --db`` 才暴露出来。

    这里走 ``engine.sync_engine.dispose()``：SQLAlchemy 为此专门保留了
    同步侧的 dispose，正是给「在同步代码里关 async 引擎」用的。
    """
    global _engine, _session_factory
    if _engine is not None:
        try:
            _engine.sync_engine.dispose()
        except Exception:  # noqa: BLE001 — 关不掉也不该阻断重建引擎
            pass
    _engine = None
    _session_factory = None


def get_engine(url: Optional[str] = None, *, echo: bool = False) -> AsyncEngine:
    """取全局单例引擎；传了 url 则重建（测试隔离用）。"""
    global _engine, _session_factory
    if url is not None:
        _dispose_engine_sync()
        _engine = create_engine_from_url(url, echo=echo)
    elif _engine is None:
        _engine = create_engine_from_url(get_database_url(), echo=echo)
    return _engine


def get_session_factory(
    url: Optional[str] = None, *, echo: bool = False
) -> async_sessionmaker[AsyncSession]:
    """取 async_sessionmaker 单例。

    ``expire_on_commit=False`` 是有意为之：默认 True 会在 commit 后让所有
    ORM 属性过期，访问它们会触发一次同步 IO。在 async 上下文里这意味着
    "在 await 之后再读属性"会抛 MissingGreenlet —— 这类 bug 极难排查，
    从源头关掉。
    """
    global _session_factory
    if url is not None or _session_factory is None:
        engine = get_engine(url, echo=echo)
        _session_factory = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


@asynccontextmanager
async def session_scope(
    session: Optional[AsyncSession] = None,
) -> AsyncIterator[AsyncSession]:
    """事务边界：正常结束 commit，异常 rollback。

    允许传入外部 session（测试里常用），此时只做 commit/rollback，
    不负责关闭 —— 谁创建谁关闭，避免误关调用方的会话。
    """
    if session is not None:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return

    factory = get_session_factory()
    async with factory() as own:
        try:
            yield own
            await own.commit()
        except Exception:
            await own.rollback()
            raise


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖注入用：每请求一个会话。"""
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def create_all(engine: Optional[AsyncEngine] = None) -> None:
    """按模型建表。

    **仅供测试与首次本地启动使用。** 生产一律走 Alembic：
    create_all 不做 schema 版本管理，也无法把新列安全地加到已有表上，
    混用会造出"库里缺列但代码以为是新的"的静默故障。
    """
    target = engine or get_engine()
    async with target.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_all(engine: Optional[AsyncEngine] = None) -> None:
    """删表（测试清理用）。"""
    target = engine or get_engine()
    async with target.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def dispose_engine() -> None:
    """关掉连接池。进程退出或测试 teardown 时调用。"""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


__all__ = [
    "DEFAULT_DATABASE_URL",
    "get_database_url",
    "to_sync_url",
    "to_async_url",
    "create_engine_from_url",
    "get_engine",
    "get_session_factory",
    "session_scope",
    "get_session",
    "create_all",
    "drop_all",
    "dispose_engine",
    "_dispose_engine_sync",
]
