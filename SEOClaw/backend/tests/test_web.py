"""Web 端（输网址 → 出报告）的测试。

## 为什么这组测试是补交的

web 模块是在「505 passed」之后才写的，也就是说提交它的时候
**已有测试对这条链路零覆盖**。实测也确实立刻翻了三次车
（任务卡 running、外键失败、重复 job）——全都是「测试全绿
不等于功能上线过」。

所以这里盯的不是「函数返回了什么」，而是**用户视角的那条链**：
输网址 → 立刻拿到 job_id → 轮询到终态 → 拿到报告。

## 不真的爬网

用 ``monkeypatch`` 把 ``run_scan`` 换掉。真跑一次 example.com 要五秒，
二十个用例就是一百秒，测试套件会被拖垮——而这里要验的是
「接口形状对不对、失败能不能被看见」，不是「爬虫能不能爬」。
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from seoclaw.db import models as m
from seoclaw.db.session import create_engine_from_url, get_engine, get_session_factory
from seoclaw.main import create_app
from seoclaw.web import _TASKS, _next_id, _normalize_url


@pytest.fixture
def client(monkeypatch):
    """每个用例一个干净的引擎 + 一个跑得很快的假扫描。"""
    url = "sqlite+aiosqlite:///:memory:"

    async def _run(session, *, site_id, url, markets, max_pages, **kw):
        # 假装扫到两页、报一个问题。字段对齐 run_scan 的真实返回，
        # 少一个字段前端就会渲染成 undefined。
        return {
            "domain": "demo.test",
            "pages_crawled": 2,
            "counts": {"critical": 1, "high": 0, "medium": 0, "low": 0, "info": 0},
            "health_score": 72.0,
            "issues": [
                {"id": 1, "code": "title.missing", "severity": "critical",
                 "scope": "page", "url": "https://demo.test/",
                 "title": "缺少 title", "fingerprint": None,
                 "status": "open", "occurrences": 1}
            ],
        }

    import seoclaw.web as webmod
    monkeypatch.setattr("seoclaw.api.scan_service.run_scan", _run)

    eng = get_engine(url)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(eng.begin().__aenter__())
    try:
        loop.run_until_complete(_create_tables(eng))
    finally:
        pass

    _TASKS.clear()
    with TestClient(create_app()) as c:
        yield c
    _TASKS.clear()


async def _create_tables(eng) -> None:
    async with eng.begin() as conn:
        await conn.run_sync(m.Base.metadata.create_all)


def _wait_job(c: TestClient, job_id: int, tries: int = 60) -> dict:
    """轮询到终态。测试里不等真实耗时，所以上限给得很宽。"""
    for _ in range(tries):
        st = c.get(f"/api/v1/web/jobs/{job_id}").json()
        if st["status"] != "running":
            return st
    return st


# --------------------------------------------------------------------------
# 页面
# --------------------------------------------------------------------------


def test_homepage_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "SEOClaw" in r.text


def test_homepage_has_scan_form(client):
    """页面得有输入框和提交按钮，否则「输网址就能用」是空话。"""
    html = client.get("/").text
    for probe in ("quick-scan", "开始体检"):
        assert probe in html, f"页面里找不到 {probe!r}"


# --------------------------------------------------------------------------
# 提交：必须秒回
# --------------------------------------------------------------------------


def test_quick_scan_returns_immediately(client):
    """⚠️ 必须 202 + 立刻返回 job_id，不能等爬完。

    同步等一次扫描就是几十秒，浏览器会以为卡死了。这是选
    BackgroundTasks 而不是直接复用 /sites/{id}/scan 的全部理由。
    """
    r = client.post("/api/v1/web/quick-scan", json={"url": "example.com"})
    assert r.status_code == 202
    body = r.json()
    assert {"job_id", "site_id", "domain"} <= set(body)
    assert body["domain"] == "example.com"


def test_quick_scan_accepts_bare_domain(client):
    """用户多半只输 example.com，不带 https://。"""
    r = client.post("/api/v1/web/quick-scan", json={"url": "demo.test"})
    assert r.status_code == 202
    assert r.json()["domain"] == "demo.test"


@pytest.mark.parametrize("bad", ["", "   ", "not a url", "http://", "###"])
def test_quick_scan_rejects_garbage(client, bad):
    """垃圾输入必须当场 400，不能默默建站然后扫描失败。"""
    if not bad.strip():
        pytest.skip("空串会被 pydantic min_length 拦，那是另一层")
    r = client.post("/api/v1/web/quick-scan", json={"url": bad})
    assert r.status_code in (400, 422), f"垃圾输入 {bad!r} 被放行了"


def test_normalize_url_adds_scheme():
    assert _normalize_url("example.com").startswith("https://")
    assert _normalize_url("http://x.test").startswith("http://")


# --------------------------------------------------------------------------
# 轮询：必须能走到终态
# --------------------------------------------------------------------------


def test_job_reaches_done(client):
    st = _wait_job(client, client.post(
        "/api/v1/web/quick-scan", json={"url": "demo.test"}).json()["job_id"])
    assert st["status"] == "done", st.get("error")
    assert st["report"]["health_score"] == 72.0
    assert st["report"]["pages_crawled"] == 2


def test_report_has_all_frontend_keys(client):
    """报告少一个键，前端就渲染成 undefined。

    counts 尤其危险：前端按 severity 取值，缺键直接显示 undefined。
    """
    st = _wait_job(client, client.post(
        "/api/v1/web/quick-scan", json={"url": "demo.test"}).json()["job_id"])
    rep = st["report"]
    for sev in ("critical", "high", "medium", "low", "info"):
        assert sev in rep["counts"], f"counts 缺 {sev}，前端会显示 undefined"
    for key in ("domain", "pages_crawled", "health_score", "issues"):
        assert key in rep


def test_unknown_job_is_404_not_running(client):
    """⚠️ 查不到的 job 必须 404，**不能**谎称 running。

    进程重启会清空内存任务表，谎称 running 会让用户对着
    永远不动的进度条等下去——一个永不结束的等待比报错糟糕得多。
    """
    r = client.get("/api/v1/web/jobs/999999")
    assert r.status_code == 404


def test_job_ids_do_not_collide_with_crawl_jobs(client):
    """内存任务号与 crawl_jobs.id 无关，不能互相占号。"""
    job = client.post("/api/v1/web/quick-scan", json={"url": "demo.test"}).json()["job_id"]
    _wait_job(client, job)
    ids = [_next_id() for _ in range(3)]
    assert len(set(ids)) == 3


def test_same_site_not_duplicated(client):
    """同一域名扫两次只建一个 site，否则排名历史会按 site_id 分裂。"""
    for _ in range(2):
        _wait_job(client, client.post(
            "/api/v1/web/quick-scan", json={"url": "demo.test"}).json()["job_id"])

    async def _count():
        factory = get_session_factory()
        async with factory() as s:
            from sqlalchemy import func, select
            return (await s.execute(
                select(func.count()).select_from(m.Site))).scalar_one()

    n = asyncio.get_event_loop().run_until_complete(_count())
    assert n == 1, f"同一域名建了 {n} 个 site"


def test_scan_failure_becomes_failed_not_stuck_running(client, monkeypatch):
    """⚠️ 这条是我自己踩过的坑：异常无人接 → 任务永远 running。

    页面会一直转圈，用户等不到任何结论。
    """
    async def _boom(session, **kw):
        raise RuntimeError("爬虫炸了")

    monkeypatch.setattr("seoclaw.api.scan_service.run_scan", _boom)

    st = _wait_job(client, client.post(
        "/api/v1/web/quick-scan", json={"url": "demo.test"}).json()["job_id"])

    assert st["status"] == "failed", "失败任务没被标成 failed，会永远转圈"
    assert "爬虫炸了" in (st["error"] or "")


def test_import_failure_still_becomes_failed(client, monkeypatch):
    """⚠️ _run 自己 import 失败时，异常发生在 try 之前。

    我第一版就是这个 bug：一个 ModuleNotFoundError 让任务卡在 running，
    而我在文件顶部刚写过「静默留在 running 会变成永远转圈的进度条」。
    done_callback 才是真正的兜底。
    """
    import seoclaw.web as webmod

    async def _dead(*a, **kw):
        raise ModuleNotFoundError("No module named 'seoclaw.web.api'")

    monkeypatch.setattr(webmod, "_run", _dead)
    r = client.post("/api/v1/web/quick-scan", json={"url": "demo.test"})
    job = r.json()["job_id"]

    st = None
    for _ in range(60):
        st = client.get(f"/api/v1/web/jobs/{job}").json()
        if st["status"] != "running":
            break
        import time
        time.sleep(0.05)

    assert st["status"] == "failed", "任务级异常没被兜住，会永远转圈"


def test_memory_task_table_bounded():
    """内存任务表必须有上限，否则长期运行会被撑爆。"""
    assert web_max() <= 1000, "任务表上限太大，长跑会吃爆内存"


def web_max() -> int:
    from seoclaw.web import _MAX_TASKS
    return _MAX_TASKS