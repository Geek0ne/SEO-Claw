"""定时扫描调度（改造阶段 2b）的测试。

三层各测各的：

- **tick() 语义**：到期触发 / CAS 单赢家 / 不叠任务 / 队列满不认领 /
  参数定格 / 失败不影响调度 / 停用与停站不触发 —— 用 test_db.py 的
  「一用例一 loop + 内存库」打法，不碰 TestClient；
- **API**：PUT/GET /sites/{id}/schedule 的开启 / 停用 / 校验 —— TestClient；
- **接线**：lifespan 真的把 scheduler_loop 跑起来了 —— TestClient +
  把轮询间隔拉小，等它**自己**触发。只测 tick() 不测接线，就存在
  「函数全对、没接上电」的空隙——这正是本仓库反复吃过的亏
  （「测试绿不代表路径通」）。

## ⚠️ tick() 不吃注入的 session，走全局 factory

跟 tasks.py 同一个纪律：生产路径什么样测试就走什么样。测试把
``seoclaw.scheduler.get_session_factory`` 换成内存库的 factory
（monkeypatch），而不是给 tick 加参数——加参数等于测一条生产不走的路。
内存库是 StaticPool 单连接，所以**用完的会话必须关掉**再开下一个
（helper 都是 `async with factory() as s:` 短事务）。

## ⚠️ 时间断言统一用 naive UTC

SQLite 的 DATETIME 列读回来是 naive 的（写入时区被剥掉，存的是 UTC
墙钟）。拿 aware 的 utcnow() 去比会 TypeError——断言前统一
``_naive()`` 剥时区，别在测试里发明第二套时间语义。
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Coroutine

# ⚠️ 必须在 import seoclaw.* 之前设（与 test_api/test_web 同一纪律）：
# 全局会话工厂会缓存引擎，设晚了会连到别的库上。注意 pytest 收集时
# 后 import 的模块会覆盖本值——所以本文件的 SQL 断言**运行时**从
# os.environ 读库路径，不用模块常量（见 _db_path）。
_TMP_DB = os.path.join(tempfile.mkdtemp(), "scheduler_test.db")
os.environ["SEO_CLAW_DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB}"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from seoclaw.db import models as m
from seoclaw.db.repository import ScanTaskRepository, SiteRepository, utcnow
from seoclaw.db.session import create_engine_from_url
from seoclaw.scheduler import tick
from seoclaw.main import app


def _naive(dt: datetime) -> datetime:
    """剥时区：SQLite 读回的 DATETIME 是 naive UTC，统一后再比。"""
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


# --------------------------------------------------------------------------
# tick() 语义（内存库，一用例一 loop）
# --------------------------------------------------------------------------


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
def mem_factory(acall, monkeypatch):
    """内存库 + 会话工厂，并把 scheduler 指过去。"""
    eng = create_engine_from_url("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(
        bind=eng, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )

    async def _setup() -> None:
        async with eng.begin() as conn:
            await conn.run_sync(m.Base.metadata.create_all)

    acall(_setup())
    monkeypatch.setattr("seoclaw.scheduler.get_session_factory", lambda: factory)
    try:
        yield factory
    finally:
        acall(eng.dispose())


async def _mk_site(
    factory,
    domain: str = "sched.test",
    *,
    interval_s: int | None = 3600,
    first_run_at: datetime | None = None,
    params: dict | None = None,
    active: bool = True,
) -> int:
    async with factory() as s:
        repo = SiteRepository(s)
        site = await repo.create(domain, markets=["base"])
        if interval_s is not None:
            await repo.set_schedule(
                site.id,
                interval_s=interval_s,
                params=params or {"max_pages": 30},
                first_run_at=first_run_at,
            )
        if not active:
            site.is_active = False
        await s.commit()
        return site.id


async def _snapshot(factory, domain: str) -> tuple[list[m.ScanTask], m.Site]:
    async with factory() as s:
        tasks = (
            (await s.execute(select(m.ScanTask).order_by(m.ScanTask.id))).scalars().all()
        )
        site = await SiteRepository(s).get_by_domain(domain)
        return list(tasks), site


def test_due_schedule_fires_and_advances(acall, mem_factory):
    """到期 → 入队一条任务，next_scan_at 推进到下个周期。"""
    acall(
        _mk_site(
            mem_factory,
            first_run_at=utcnow() - timedelta(seconds=1),
            params={"max_pages": 7},
        )
    )
    n = acall(tick())
    tasks, site = acall(_snapshot(mem_factory, "sched.test"))
    assert n == 1, "到期站点没有入队"
    assert len(tasks) == 1
    assert tasks[0].max_pages == 7, "执行参数没走快照"
    assert site.scan_interval_s == 3600
    assert _naive(site.next_scan_at) > _naive(utcnow()), "next_scan_at 没推进"


def test_not_yet_due_is_untouched(acall, mem_factory):
    acall(
        _mk_site(
            mem_factory,
            first_run_at=utcnow() + timedelta(hours=1),
        )
    )
    assert acall(tick()) == 0
    tasks, site = acall(_snapshot(mem_factory, "sched.test"))
    assert not tasks, "没到期就开扫了"


def test_disabled_schedule_is_untouched(acall, mem_factory):
    """interval_s=NULL = 未开启托管，永远不触发。"""
    acall(_mk_site(mem_factory, interval_s=None))
    assert acall(tick()) == 0
    tasks, _ = acall(_snapshot(mem_factory, "sched.test"))
    assert not tasks


def test_inactive_site_is_untouched(acall, mem_factory):
    """停用的站不该继续对外发扫描。"""
    acall(
        _mk_site(
            mem_factory,
            first_run_at=utcnow() - timedelta(seconds=1),
            active=False,
        )
    )
    assert acall(tick()) == 0
    tasks, _ = acall(_snapshot(mem_factory, "sched.test"))
    assert not tasks


def test_no_stacking_when_task_active(acall, mem_factory):
    """已有 pending/running 任务：不叠任务，但 next_scan_at 照常推进。

    这是「按时间节奏走」语义的关键：扫描比周期长时队列不会越积越多。
    """
    acall(
        _mk_site(
            mem_factory,
            first_run_at=utcnow() - timedelta(seconds=1),
        )
    )
    site_id = acall(_snapshot(mem_factory, "sched.test"))[1].id

    async def _enqueue_pending() -> None:
        async with mem_factory() as s:
            await ScanTaskRepository(s).enqueue(
                site_id=site_id,
                url="https://sched.test/",
                markets=["base"],
                max_pages=30,
                max_depth=6,
                respect_robots=True,
                render_js=False,
            )
            await s.commit()

    acall(_enqueue_pending())
    assert acall(tick()) == 0, "任务在跑还叠新任务"
    tasks, site = acall(_snapshot(mem_factory, "sched.test"))
    assert len(tasks) == 1, "pending 之外又插了一条"
    assert _naive(site.next_scan_at) > _naive(utcnow()), "跳归跳，节奏不能乱"


def test_queue_full_defers_without_advancing(acall, mem_factory):
    """队列满：不认领、不推进——留在 due，下个 tick 再试。

    排队承诺必须兑现：宁可晚扫，不接兑现不了的活。

    ⚠️ 填队任务必须挂在**别的**站点上：挂在本站点会先命中不叠任务
    分支（那条路是照常推进周期的），测的就不是队列满语义了。
    """
    acall(
        _mk_site(
            mem_factory,
            first_run_at=utcnow() - timedelta(seconds=1),
        )
    )

    async def _fill_queue() -> None:
        async with mem_factory() as s:
            repo = ScanTaskRepository(s)
            filler_site = await SiteRepository(s).create("filler.test", markets=["base"])
            for i in range(50):  # MAX_PENDING 的口径，别从 tasks.py import 常量漂移
                await repo.enqueue(
                    site_id=filler_site.id,
                    url=f"https://filler.test/{i}",
                    markets=["base"],
                    max_pages=30,
                    max_depth=6,
                    respect_robots=True,
                    render_js=False,
                )
            await s.commit()

    acall(_fill_queue())
    assert acall(tick()) == 0
    tasks, site = acall(_snapshot(mem_factory, "sched.test"))
    mine = [t for t in tasks if t.site_id == site.id]
    assert len(mine) == 0, "队列满时还往里塞"
    assert _naive(site.next_scan_at) <= _naive(utcnow()) + timedelta(seconds=5), (
        "队列满时不该推进周期——任务留在 due，下个 tick 才能补上"
    )


def test_claim_is_single_winner(acall, mem_factory):
    """CAS：两个调度实例抢同一到期触发，只有一个赢。

    这是多 worker 部署不双扫的唯一防线——条件 UPDATE 看 rowcount，
    别改成先 SELECT 再 UPDATE。
    """
    from seoclaw.db.repository import SiteRepository as SR

    site_id = acall(
        _mk_site(mem_factory, first_run_at=utcnow() - timedelta(seconds=1))
    )
    now = utcnow()

    async def _double_claim() -> tuple[bool, bool]:
        async with mem_factory() as s:
            first = await SR(s).claim_schedule(
                site_id, now=now, next_scan_at=now + timedelta(seconds=3600)
            )
            await s.commit()
        async with mem_factory() as s:
            second = await SR(s).claim_schedule(
                site_id, now=now, next_scan_at=now + timedelta(seconds=3600)
            )
            await s.commit()
        return first, second

    first, second = acall(_double_claim())
    assert first is True and second is False, "CAS 没拦住第二次认领"


def test_params_snapshot_not_live_settings(acall, mem_factory):
    """执行参数定格在开启托管那一刻，不随后续站点设置漂移。"""
    acall(
        _mk_site(
            mem_factory,
            first_run_at=utcnow() - timedelta(seconds=1),
            params={
                "url": "https://snap.test/pricing",
                "markets": ["google"],
                "max_pages": 7,
                "max_depth": 2,
                "respect_robots": False,
                "render_js": True,
            },
        )
    )

    async def _mutate_site() -> None:
        async with mem_factory() as s:
            site = await SiteRepository(s).get_by_domain("sched.test")
            site.markets = ["baidu"]
            await s.commit()

    acall(_mutate_site())
    acall(tick())
    tasks, _ = acall(_snapshot(mem_factory, "sched.test"))
    (task,) = tasks
    assert task.url == "https://snap.test/pricing"
    assert list(task.markets) == ["google"], "快照被站点当前设置覆盖了"
    assert task.max_pages == 7 and task.max_depth == 2
    assert task.respect_robots is False and task.render_js is True


def test_failed_scan_does_not_stop_schedule(acall, mem_factory):
    """上一轮扫失败，下个周期照常复扫：复扫的意义是「持续盯着」。"""
    site_id = acall(
        _mk_site(
            mem_factory,
            first_run_at=utcnow() - timedelta(seconds=1),
        )
    )
    acall(tick())
    tasks, site = acall(_snapshot(mem_factory, "sched.test"))
    assert len(tasks) == 1

    async def _fail_and_re_due() -> None:
        async with mem_factory() as s:
            await ScanTaskRepository(s).fail(tasks[0].id, "测试：炸了")
            site_row = await SiteRepository(s).get(site_id)
            site_row.next_scan_at = utcnow() - timedelta(seconds=1)
            await s.commit()

    acall(_fail_and_re_due())
    assert acall(tick()) == 1
    tasks, _ = acall(_snapshot(mem_factory, "sched.test"))
    assert len(tasks) == 2, "失败一轮就把站点踢出观察了"


# --------------------------------------------------------------------------
# API（TestClient）
# --------------------------------------------------------------------------


def _db_path() -> str:
    """运行时读共享库路径（import 顺序会覆盖模块常量，见模块 docstring）。"""
    url = os.environ["SEO_CLAW_DATABASE_URL"]
    return url.split("///", 1)[1]


def _exec_sql(sql: str, params: tuple = ()) -> list[tuple]:
    import sqlite3

    try:
        con = sqlite3.connect(_db_path(), timeout=5)
        try:
            rows = con.execute(sql, params).fetchall()
            con.commit()
            return rows
        finally:
            con.close()
    except sqlite3.OperationalError:
        return []


async def _fake_scan(session, *, site_id, url, markets, max_pages, **kw):
    return {
        "domain": "sched.test",
        "pages_crawled": 1,
        "counts": {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0},
        "health_score": 99.0,
        "issues": [],
    }


@pytest.fixture
def client(monkeypatch):
    """⚠️ 收尾必须把本站点删干净：本文件的站点一旦留着到期调度，
    后续任何 TestClient 启动（scheduler_loop 首拍就会 tick）都会替它
    入队扫描——跨文件污染别人的断言。"""
    monkeypatch.setattr("seoclaw.api.scan_service.run_scan", _fake_scan)
    _exec_sql("DELETE FROM scan_tasks")
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    _exec_sql("DELETE FROM sites WHERE domain LIKE 'sched-%.test'")


_n = 0


def _new_site(c: TestClient) -> int:
    global _n
    _n += 1
    r = c.post("/api/v1/sites", json={"domain": f"sched-{_n}.test"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_put_schedule_roundtrip(client):
    site_id = _new_site(client)
    r = client.put(
        f"/api/v1/sites/{site_id}/schedule",
        json={"interval_s": 86400, "max_pages": 5, "markets": ["google"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    assert body["interval_s"] == 86400
    assert body["next_scan_at"] is not None, "开启托管没安排首次复扫"
    assert body["params"]["max_pages"] == 5
    assert body["params"]["markets"] == ["google"]

    r2 = client.get(f"/api/v1/sites/{site_id}/schedule")
    assert r2.json() == body, "GET 与 PUT 口径不一致"


def test_put_schedule_first_run_is_immediate(client):
    """提交即安排第一次复扫（next_scan_at≈now），不是等一个周期。"""
    site_id = _new_site(client)
    client.put(f"/api/v1/sites/{site_id}/schedule", json={"interval_s": 86400})
    rows = _exec_sql(
        "SELECT next_scan_at, scan_interval_s FROM sites WHERE id=?", (site_id,)
    )
    (next_scan_at, interval) = rows[0]
    assert interval == 86400
    stored = _naive(datetime.fromisoformat(next_scan_at))
    assert stored <= _naive(utcnow()) + timedelta(seconds=5), (
        f"首次复扫被排到了一个周期之后：{next_scan_at}"
    )


def test_put_schedule_disable_clears_everything(client):
    site_id = _new_site(client)
    client.put(f"/api/v1/sites/{site_id}/schedule", json={"interval_s": 86400})
    r = client.put(f"/api/v1/sites/{site_id}/schedule", json={"interval_s": None})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is False
    assert body["interval_s"] is None
    assert body["next_scan_at"] is None
    assert body["params"] == {}
    rows = _exec_sql(
        "SELECT scan_interval_s, next_scan_at, schedule_params FROM sites WHERE id=?",
        (site_id,),
    )
    # ⚠️ JSON 列的 Python None 会存成 JSON 'null' 文本（JSON 类型
    # none_as_null 默认 False），读回时反序列化又是 None——ORM 与
    # API 看到的都是「清空了」，只有裸 SQL 能看见 'null' 文本。
    # 标量两列必须是真 NULL，JSON 列两者都算清（口径钉在 API 上）。
    assert rows[0][0] is None and rows[0][1] is None, "停用没把标量列清干净"
    assert rows[0][2] in (None, "null"), "停用没把快照清干净"
    r3 = client.get(f"/api/v1/sites/{site_id}/schedule")
    assert r3.json()["params"] == {} and r3.json()["enabled"] is False


def test_put_schedule_rejects_tiny_interval(client):
    site_id = _new_site(client)
    r = client.put(f"/api/v1/sites/{site_id}/schedule", json={"interval_s": 60})
    assert r.status_code == 422, f"60 秒的托管间隔居然收下了：{r.text}"


def test_put_schedule_rejects_unknown_market(client):
    site_id = _new_site(client)
    r = client.put(
        f"/api/v1/sites/{site_id}/schedule",
        json={"interval_s": 86400, "markets": ["nope"]},
    )
    assert r.status_code == 400, r.text


def test_schedule_unknown_site_is_404(client):
    assert client.get("/api/v1/sites/999999/schedule").status_code == 404


# --------------------------------------------------------------------------
# 接线：lifespan 真的把 scheduler_loop 跑起来了
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# 收尾不能挂死（回归钉）
# --------------------------------------------------------------------------


def test_rapid_client_cycles_do_not_wedge_shutdown():
    """⚠️ 收尾必须有界：快速开关 TestClient 不能挂死。

    回归钉的是 2026-10-20 踩到的坑：取消撞上 SQLAlchemy 异步驱动的
    greenlet 交接区时，任务会吊死在没人置位的 future 上（实测栈：
    worker 卡在 aiosqlite `_terminate_graceful_close` 的 asyncio.shield
    里，线程已空闲、close future 永远不完成），当时 lifespan 收尾是
    无界 await → TestClient 关闭**随机挂起**，挂哪条取决于取消命中
    哪个 DB 操作（启动时连续三个 DB 调用，首关命中率最高）。

    用线程 + join 超时：真回归时这里 FAIL，而不是把整个测试套件挂死。
    """
    import threading

    _exec_sql("DELETE FROM scan_tasks")  # 不让 worker 顺手跑真实扫描

    def _cycles() -> None:
        for _ in range(6):
            with TestClient(app, raise_server_exceptions=False) as c:
                c.get("/api/v1/health")

    t = threading.Thread(target=_cycles, daemon=True)
    t.start()
    t.join(30)
    assert not t.is_alive(), (
        "快速开关 TestClient 挂死了——lifespan 收尾的有界等待是不是没了？"
    )


def test_scheduler_loop_really_runs(monkeypatch):
    """⚠️ 只测 tick() 不测接线，就存在「函数全对、没接上电」的空隙。

    这里不手动调任何东西：拉小轮询间隔，等 scheduler_loop 自己触发、
    自己入队、worker 自己跑完——走的就是生产的那条路。
    """
    monkeypatch.setattr("seoclaw.api.scan_service.run_scan", _fake_scan)
    monkeypatch.setenv("SEO_CLAW_SCHEDULE_POLL_S", "0.05")
    _exec_sql("DELETE FROM scan_tasks")
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.post("/api/v1/sites", json={"domain": "sched-wired.test"})
        site_id = r.json()["id"]
        c.put(f"/api/v1/sites/{site_id}/schedule", json={"interval_s": 86400})

        task_row = None
        for _ in range(200):  # 最多 4 秒
            rows = _exec_sql(
                "SELECT id, status FROM scan_tasks WHERE site_id=?", (site_id,)
            )
            if rows and rows[0][1] in ("done", "failed"):
                task_row = rows[0]
                break
            time.sleep(0.02)

    assert task_row is not None, (
        "调度循环没有触发：要么 scheduler_loop 没被 lifespan 启动，"
        "要么 tick 没入队——这条断言就是防「函数全对、没接上电」的"
    )
    assert task_row[1] == "done", f"定时任务没跑完：{task_row}"
    _exec_sql("DELETE FROM sites WHERE domain = 'sched-wired.test'")
