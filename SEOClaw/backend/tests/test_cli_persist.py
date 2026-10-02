"""CLI 落库链路测试（`scan --db`）。

## 为什么这组测试存在

2026-10-02 实测发现：``app/cli.py`` 里落库调用 **0** 处，
而 ``app/api/scan_service.py`` 有 6 处 —— 9 张表建好了、Alembic 迁移齐了，
但 CLI 这条最常用的入口**一次都没往库里写过**。

所以这组测试盯的不是「某个函数返回了什么」，而是
「一条命令扫完之后，库里到底有没有东西」。测试绿而功能没上线过，
是这类活最容易出现的假完成。

## 不依赖 pytest-asyncio

沿用 test_db.py 的做法：一个用例一个 event loop。
asyncpg/aiosqlite 的连接绑定在创建它的 loop 上，换 loop 后连接可见状态会失真，
表现为「刚插入的行 SELECT 不到」，进而被误判成唯一约束冲突。
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Coroutine

import pytest

from app.db import models as m
from app.db.session import create_engine_from_url
from app.models import Issue, Market, Page, Severity


@pytest.fixture
def loop():
    new_loop = asyncio.new_event_loop()
    try:
        yield new_loop
    finally:
        new_loop.close()


@pytest.fixture
def acall(loop) -> Callable[[Coroutine[Any, Any, Any]], Any]:
    def _acall(coro: Coroutine[Any, Any, Any]) -> Any:
        return loop.run_until_complete(coro)

    return _acall


@pytest.fixture
def engine(acall):
    eng = create_engine_from_url("sqlite+aiosqlite:///:memory:")

    async def _setup() -> None:
        async with eng.begin() as conn:
            await conn.run_sync(m.Base.metadata.create_all)

    acall(_setup())
    try:
        yield eng
    finally:
        acall(eng.dispose())


@pytest.fixture
def session(acall, engine):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
    sess = factory()
    try:
        yield sess
    finally:
        acall(sess.close())


# --------------------------------------------------------------------------
# 样本
# --------------------------------------------------------------------------


def _pages() -> list[Page]:
    return [
        Page(url="https://demo.test/", title="首页", status_code=200, word_count=30,
             text="内容", is_html=True),
        Page(url="https://demo.test/a", title="A", status_code=200, word_count=800,
             text="内容" * 400, is_html=True),
        Page(url="https://demo.test/b", title="B", status_code=404, is_html=True,
             error="http_error: NotFound"),
    ]


def _issues() -> list[Issue]:
    return [
        Issue(code="meta.missing", severity=Severity.HIGH, market=Market.BASE,
              scope="page", url="https://demo.test/a", title="缺 meta",
              description="d", fix_hint="h", evidence={"k": 1}),
        # 站点级问题：url 为 None，不该有 page_id
        Issue(code="sitemap.missing", severity=Severity.HIGH, market=Market.BASE,
              scope="site", url=None, title="缺 sitemap",
              description="d", fix_hint="h", evidence={"k": 2}),
    ]


# --------------------------------------------------------------------------
# 核心：落库真的写进去了
# --------------------------------------------------------------------------


def test_persist_scan_writes_pages_and_issues(acall, session):
    from app.persist import get_or_create_site, persist_scan

    async def _run():
        site_id = await get_or_create_site(
            session, "https://demo.test/a", markets=["base"]
        )
        return await persist_scan(
            session, site_id=site_id, pages=_pages(), issues=_issues(),
            url_count=10, elapsed=1.0,
        )

    info = acall(_run())
    acall(session.commit())

    assert info["pages_written"] == 3
    assert info["issues_written"] == 2

    n_pages = acall(_run_count(session, m.Page))
    n_issues = acall(_run_count(session, m.Issue))
    assert n_pages == 3, "页没落进库 —— 这就是「建了表但没人写」的现场"
    assert n_issues == 2


async def _run_count(session, model) -> int:
    from sqlalchemy import func, select

    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


def test_job_reaches_succeeded(acall, session):
    """job 必须落到终态。卡在 running 的 job 是最恶心的状态：
    报告早就出了，库里却显示「还在跑」，查问题的人会一直等。"""
    from app.db.models import JobStatus
    from app.persist import get_or_create_site, persist_scan

    async def _run():
        site_id = await get_or_create_site(session, "https://demo.test/a")
        return await persist_scan(
            session, site_id=site_id, pages=_pages(), issues=_issues(), url_count=7
        )

    info = acall(_run())
    acall(session.commit())

    job = acall(session.get(m.CrawlJob, info["job_id"]))
    assert job.status == JobStatus.SUCCEEDED
    assert job.url_count == 7
    # pages_crawled 只数抓成功的：404 那页进了 pages 列表但没内容
    assert job.pages_crawled == 2, "pages_crawled 把失败页也算进去了"


def test_site_reused_across_scans(acall, session):
    """⚠️ 同域必须复用同一条 site 记录。

    否则每扫一次就新建一个 site_id：pages/issues 外键全断，
    而 rank_history 会按不同 site_id 分裂成互不相干的几条历史 ——
    「排名监控」这个功能直接失效。
    """
    from app.persist import get_or_create_site

    async def _run():
        a = await get_or_create_site(session, "https://demo.test/a")
        b = await get_or_create_site(session, "https://demo.test/b")
        c = await get_or_create_site(session, "https://www.demo.test/c")
        return a, b, c

    a, b, c = acall(_run())
    acall(session.commit())
    assert a == b == c, "同域被拆成多个 site_id"


def test_page_level_issue_gets_page_id(acall, session):
    """页面级问题必须能回溯到具体页面，否则「按页聚合」做不了。"""
    from app.persist import get_or_create_site, persist_scan

    async def _run():
        site_id = await get_or_create_site(session, "https://demo.test/a")
        await persist_scan(
            session, site_id=site_id, pages=_pages(), issues=_issues()
        )

    acall(_run())
    acall(session.commit())

    from sqlalchemy import select

    rows = acall(session.execute(select(m.Issue).order_by(m.Issue.id))).scalars().all()
    by_url = {r.url: r for r in rows}
    assert by_url["https://demo.test/a"].page_id is not None
    assert by_url[None].page_id is None, "站点级问题不该挂到某个页面上"


# --------------------------------------------------------------------------
# 同步 dispose 那个坑
# --------------------------------------------------------------------------


def test_get_engine_does_not_leak_await_warning(acall):
    """⚠️ get_engine() 是同步函数，曾直接调 async 的 dispose_engine()。

    协程从未被 await → 旧连接池**根本没关**，只是把全局引用置空。
    现象是 RuntimeWarning: coroutine 'dispose_engine' was never awaited，
    2026-10-02 跑 scan --db 才暴露。

    这里用 warnings 捕获来锁死：Pytest 默认不把 RuntimeWarning 显示成
    失败，所以得显式抓 —— 「不报错」不等于「没发生」。
    """
    import warnings

    from app.db import session as sess_mod

    async def _run():
        eng1 = sess_mod.get_engine("sqlite+aiosqlite:///:memory:")
        async with eng1.begin() as conn:
            await conn.run_sync(m.Base.metadata.create_all)
        eng2 = sess_mod.get_engine("sqlite+aiosqlite:///:memory:")
        return eng1, eng2

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        acall(_run())

    leaked = [
        w for w in caught
        if "never awaited" in str(w.message) and "dispose_engine" in str(w.message)
    ]
    assert not leaked, f"同步上下文里调 async dispose：{[str(w.message) for w in leaked]}"

    acall(sess_mod.dispose_engine())


def test_db_flag_exists_and_defaults_to_off():
    """⚠️ --db 不给时必须**完全不落库**。

    悄悄给用户建一个 db 文件是侵入行为：报告能出、文件却多出来一个，
    而用户从没要求过。
    """
    from app.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["scan", "https://demo.test/"])
    assert args.db is None
    args2 = parser.parse_args(["scan", "https://demo.test/", "--db", "x.db"])
    assert args2.db == "x.db"