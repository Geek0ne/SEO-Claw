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

## ⚠️ 别自己驱动事件循环（我第一版就栽在这）

我最初在 fixture 里写 ``asyncio.get_event_loop().run_until_complete(...)``
去建表，结果全量跑是 **507 passed / 16 errors**：
``RuntimeError: This event loop is already running``。

``TestClient`` 自己就在跑一个 loop。**同一个 loop 不能一边运行
一边再被 run_until_complete驱动。** 单独跑这个文件是 16 passed，
混在全量套件里才炸——又是一次「单跑绿、全量红」。

正确做法照 ``test_api.py``：环境变量在 import 之前设好，
建表交给 lifespan，测试完全不碰 loop。
"""

from __future__ import annotations

import os
import tempfile
import time

# ⚠️ 必须在 import seoclaw.* 之前设：``get_session_factory()`` 会缓存引擎，
# 设晚了会连到别的库上，表现为「测试之间互相污染」。
# 与 test_api.py 用同一个库是**故意的**：两个模块都在 import 前设同一个值，
# 谁先设算谁的，但至少不会出现「一半用例连 A 库、一半连 B 库」。
# 因此断言**不能依赖全库计数**，只能按域名查（见 test_same_domain_not_duplicated）。
_TMP_DB = os.path.join(tempfile.mkdtemp(), "web_test.db")
os.environ["SEO_CLAW_DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB}"

import pytest
from fastapi.testclient import TestClient

from seoclaw.main import app
from seoclaw.web import _normalize_url


def _exec_sql(sql: str, params: tuple = ()) -> list[tuple]:
    """直接对测试库执行 SQL（同步 sqlite3），返回全部行。

    ⚠️ 不用 ORM/async 会话：测试是同步的，而驱动事件循环的教训在模块
    docstring 里。断言辅助的轻量读写走裸连接最稳。表还没建时返回 []。
    """
    import sqlite3

    try:
        con = sqlite3.connect(_TMP_DB, timeout=5)
        try:
            rows = con.execute(sql, params).fetchall()
            con.commit()
            return rows
        finally:
            con.close()
    except sqlite3.OperationalError:
        return []


async def _fake_scan(session, *, site_id, url, markets, max_pages, **kw):
    """假装扫到两页、报一个问题。

    ⚠️ 必须是 ``async def``：web 层写的是 ``await run_scan(...)``。
    我第一版写成同步函数，单跑不报错（轮询超时就直接返回了），
    全量跑才炸 ``TypeError: object dict can't be used in 'await' expression``
    ——又是一次「只跑新文件看不出来」的坑。

    字段严格对齐 ``run_scan`` 的真实返回——少一个字段前端就渲染成
    undefined，而那正是这类测试最容易漏的东西。
    """
    return {
        "domain": "demo.test",
        "pages_crawled": 2,
        "counts": {"critical": 1, "high": 0, "medium": 0, "low": 0, "info": 0},
        "health_score": 72.0,
        "issues": [
            {
                "id": 1, "code": "title.missing", "severity": "critical",
                "scope": "page", "url": "https://demo.test/",
                "title": "缺少 title", "fingerprint": None,
                "status": "open", "occurrences": 1,
            }
        ],
    }


@pytest.fixture
def client(monkeypatch):
    """⚠️ 不碰事件循环——建表交给 lifespan（见模块 docstring）。

    ``raise_server_exceptions=False``：默认 True 时路由里抛的异常会
    在测试进程里重新抛出，压根拿不到响应，也就无法断言
    「job 已被标记 failed」——而那正是这组测试最想钉住的东西。
    """
    monkeypatch.setattr("seoclaw.api.scan_service.run_scan", _fake_scan)

    # ⚠️ 限流器是**全进程共用**的（production 里就该如此）。
    # 本文件有 8 处 quick-scan 提交，burst 只有 3 —— 不清空的话
    # 后面的用例会收到 429，然后我花半天去查「为什么测试顺序会互相影响」。
    # 这不是生产问题，是测试隔离问题：生产里每个 IP 各自一个桶。
    from seoclaw.web import guard
    guard.public_limiter._buckets.clear()

    # ⚠️ 假域名也要过 SSRF 校验，而 ``.test`` 是 RFC 保留 TLD，本就解析不出来。
    # 于是我自己加的守卫把 6 个用例全拒了——报「域名解析失败」。
    #
    # 修法是**让假域名解析到一个公网 IP**，不是放宽守卫：
    # 守卫在生产里拒绝不可解析域名是对的（那是 DNS rebinding 的一环），
    # 改它等于为了测试通过而打开一个洞。
    import socket
    _real_gai = socket.getaddrinfo

    def _fake_gai(host, port, *a, **kw):
        if host.endswith((".test", ".invalid")):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "",
                 ("93.184.216.34", port)),
            ]
        return _real_gai(host, port, *a, **kw)

    monkeypatch.setattr(socket, "getaddrinfo", _fake_gai)

    # ⚠️ 并发计数器同样是**全局**的。上一条用例若泄漏了计数，
    # 这一条就会莫名其妙收到 503 —— 而且症状是「测试之间互相影响」，
    # 极难定位。跟限流桶一样，每个用例进来先清干净。
    # ⚠️ 任务状态落库后，测试隔离靠清表：上个用例遗留的 pending 行会被
    # 本用例的 worker 认领，污染断言（尤其队列上限那条）。
    # 直接同步 sqlite3 清——这里不碰事件循环（见模块 docstring）。
    _exec_sql("DELETE FROM scan_tasks")

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    guard.public_limiter._buckets.clear()


def _submit(c: TestClient, url: str = "demo.test") -> int:
    r = c.post("/api/v1/web/quick-scan", json={"url": url})
    assert r.status_code == 202, r.text
    return r.json()["job_id"]


def _wait_job(c: TestClient, job_id: int, tries: int = 200) -> dict:
    """轮询到终态。假扫描是纯内存的，很快就会结束。"""
    st = {"status": "running"}
    for _ in range(tries):
        st = c.get(f"/api/v1/web/jobs/{job_id}").json()
        if st["status"] != "running":
            return st
        time.sleep(0.02)
    return st


# --------------------------------------------------------------------------
# 页面
# --------------------------------------------------------------------------


def test_homepage_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "SEO-Claw" in r.text


def test_homepage_has_scan_form(client):
    """页面得有接入站点的入口和发起体检的按钮，否则「输网址就能用」是空话。

    ⚠️ 这条断言改过一次。原文查的是 ``quick-scan`` —— 那是老版单页表单
    用的 ``POST /web/quick-scan``，重建后已经不存在。现在查的是**当前**
    真实入口：侧栏的「接入站点」按钮 + 站点详情页的「开始体检」按钮 +
    对应的 API 路径。

    ⚠️ 改的是**测试不是产品**：老界面的那个端点还在（/web/quick-scan
    仍可用），但页面不再用它。把界面退回旧版来迁就一条测试，等于
    为了让断言变绿而牺牲已经做完的东西。
    """
    html = client.get("/").text
    # ⚠️ 查的是前端**实际写的**路径前缀。上一版我断言字面量
    # "/api/v1/sites/{site_id}/scan"，但 JS 里是模板串 ${id} ——
    # 断言了一个页面上根本不存在的字符串，红的是断言不是页面。
    for probe in ("btnAdd", "接入站点", "/api/v1/sites/", "开始体检"):
        assert probe in html, f"页面里找不到 {probe!r}"


# --------------------------------------------------------------------------
# 提交：必须秒回
# --------------------------------------------------------------------------


def test_quick_scan_returns_immediately(client):
    """⚠️ 必须 202 + 立刻返回 job_id，不能等爬完。

    同步等一次扫描就是几十秒，浏览器会以为卡死了。这是选
    BackgroundTasks 而不是直接复用 /sites/{id}/scan 的全部理由。
    """
    job_id = _submit(client, "example.com")
    assert isinstance(job_id, int)


def test_quick_scan_accepts_bare_domain(client):
    """用户多半只输 example.com，不带 https://。"""
    assert _submit(client, "bare.test") > 0


def test_normalize_url_adds_scheme():
    assert _normalize_url("example.com").startswith("https://")
    assert _normalize_url("http://x.test").startswith("http://")


@pytest.mark.parametrize("bad", ["not a url", "http://", "###", "   x y z"])
def test_quick_scan_rejects_garbage(client, bad):
    """垃圾输入必须当场 400，不能默默建站然后扫描失败。"""
    r = client.post("/api/v1/web/quick-scan", json={"url": bad})
    assert r.status_code in (400, 422), f"垃圾输入 {bad!r} 被放行了"


# --------------------------------------------------------------------------
# 轮询：必须能走到终态
# --------------------------------------------------------------------------


def test_job_reaches_done(client):
    st = _wait_job(client, _submit(client))
    assert st["status"] == "done", st.get("error")
    assert st["report"]["health_score"] == 72.0
    assert st["report"]["pages_crawled"] == 2


def test_report_has_all_frontend_keys(client):
    """报告少一个键，前端就渲染成 undefined。

    counts 尤其危险：前端按 severity 取值，缺键直接显示 undefined。
    """
    rep = _wait_job(client, _submit(client))["report"]
    for sev in ("critical", "high", "medium", "low", "info"):
        assert sev in rep["counts"], f"counts 缺 {sev}，前端会显示 undefined"
    for key in ("domain", "pages_crawled", "health_score", "issues"):
        assert key in rep


def test_unknown_job_is_404_not_running(client):
    """⚠️ 查不到的 job 必须 404，**不能**谎称 running。

    进程重启会清空内存任务表，谎称 running 会让用户对着
    永远不动的进度条等下去——一个永不结束的等待比报错糟糕得多。
    """
    assert client.get("/api/v1/web/jobs/999999").status_code == 404


def test_task_ids_are_unique(client):
    """落库任务号唯一（自增主键）：两次提交拿到不同 id。"""
    assert _submit(client) != _submit(client)


def test_queue_cap_rejects_when_backed_up(client, monkeypatch):
    """队列满必须当场拒收。

    ⚠️ 这条替换了旧的「并发上限当场拒」——现在真的有队列了，排队是
    可兑现的承诺。但队列深度要有上限：收下排到天黑的活儿比明说
    「现在忙」更伤信任。
    """
    import seoclaw.web as webmod

    monkeypatch.setattr(webmod, "_MAX_PENDING", 0)
    r = client.post("/api/v1/web/quick-scan", json={"url": "busy.test"})
    assert r.status_code == 503
    assert "Retry-After" in r.headers, "503 必须带 Retry-After"


def test_same_domain_not_duplicated(client):
    """同一域名扫两次只建一个 site，否则排名历史会按 site_id 分裂。

    ⚠️ 只能**按域名**查，不能数全库：本文件与 test_api.py 共用一个
    测试库（见模块 docstring），数全库会把别的模块的站点也算进来。
    """
    _wait_job(client, _submit(client, "dup.test"))
    _wait_job(client, _submit(client, "dup.test"))

    sites = client.get("/api/v1/sites").json()
    mine = [s for s in sites if s["domain"] == "dup.test"]
    assert len(mine) == 1, f"同一域名建了 {len(mine)} 个 site"


# --------------------------------------------------------------------------
# 失败必须看得见
# --------------------------------------------------------------------------


def test_scan_failure_becomes_failed(client, monkeypatch):
    """⚠️ 这条是我自己踩过的坑：异常无人接 → 任务永远 running。

    页面会一直转圈，用户等不到任何结论。
    """

    async def _boom(session, **kw):
        raise RuntimeError("爬虫炸了")

    monkeypatch.setattr("seoclaw.api.scan_service.run_scan", _boom)

    st = _wait_job(client, _submit(client))
    assert st["status"] == "failed", "失败任务没被标成 failed，会永远转圈"
    assert "爬虫炸了" in (st["error"] or "")


def test_task_level_exception_still_becomes_failed(client, monkeypatch):
    """⚠️ 执行器自身的异常（如 import 失败）也必须落成 failed。

    我第一版就是这个 bug：一个 ModuleNotFoundError 让任务卡在 running，
    而我在文件顶部刚写过「静默留在 running 会变成永远转圈的进度条」。
    现在 worker 的兜底 except 就是那道网，这里把它钉住。
    """
    import seoclaw.tasks as taskmod

    async def _dead(*a, **kw):
        raise ModuleNotFoundError("No module named 'seoclaw.web.api'")

    monkeypatch.setattr(taskmod, "_execute", _dead)

    st = _wait_job(client, _submit(client))
    assert st["status"] == "failed", "任务级异常没被兜住，会永远转圈"
    assert "ModuleNotFoundError" in (st["error"] or "")


# --------------------------------------------------------------------------
# 并发计数（落库后的等价物）
# --------------------------------------------------------------------------
#
# ⚠️ 这道闸最阴的坑是「计数器忘了减」：症状是「刚才还好好的，
# 突然全站 503」，而且极难定位——内存计数时代我漏过一次。落库后
# running 是**从行状态数出来的**，不存在忘减的可能，但「行永远留在
# running」是同一类病的新形态，这里改盯那个。


def test_no_running_rows_after_success(client):
    """跑完之后 running 行必须清零（done/failed 都是终态）。"""
    _wait_job(client, _submit(client))
    for _ in range(100):
        if not _exec_sql("SELECT id FROM scan_tasks WHERE status = 'running'"):
            break
        time.sleep(0.02)
    rows = _exec_sql("SELECT id, status FROM scan_tasks WHERE status = 'running'")
    assert not rows, f"有行卡在 running：{rows}——用户会对着不动的进度条等下去"


def test_no_running_rows_after_failure(client, monkeypatch):
    """⚠️ 失败也必须收尾。只在成功路径收尾的话，
    「爬虫一挂就永远 running」——比没有队列还糟。"""

    async def _boom(session, **kw):
        raise RuntimeError("炸了")

    monkeypatch.setattr("seoclaw.api.scan_service.run_scan", _boom)

    st = _wait_job(client, _submit(client))
    assert st["status"] == "failed"
    rows = _exec_sql("SELECT id FROM scan_tasks WHERE status = 'running'")
    assert not rows, f"失败任务没收尾，仍有行卡在 running：{rows}"


def test_stale_running_task_is_recovered(monkeypatch):
    """⚠️ 进程死掉留下的 running 孤儿必须被捞回——这是内存态方案根本
    做不到的事（任务当时直接蒸发）。启动恢复见 tasks.recover_stale：
    attempts 未超限回 pending 重跑，超限标 failed，绝不留 running。

    ⚠️ 这里刻意用**两个顺序的 client**而不是嵌套：第一个 client 退出
    就是「上个进程死了」，语义更真；更重要的是嵌套 TestClient 会让
    两个事件循环共享同一个引擎连接池，引发与被测逻辑无关的 500。
    """
    monkeypatch.setattr("seoclaw.api.scan_service.run_scan", _fake_scan)
    with TestClient(app, raise_server_exceptions=False) as c1:
        site_id = c1.post(
            "/api/v1/sites", json={"domain": "orphan.test"}
        ).json()["id"]
    # 造一条「上个进程」的任务：running + started_at 久远。
    # 塞成 running 而不是 pending——正在跑的活儿不会被 worker 认领，
    # 只有恢复逻辑会碰它，隔离干净。
    _exec_sql(
        "INSERT INTO scan_tasks (site_id, url, markets, max_pages, max_depth,"
        " respect_robots, render_js, status, attempts, started_at, created_at,"
        " updated_at) VALUES (?, 'https://orphan.test/', '[]', 5, 3, 1, 0,"
        " 'running', 1, '2020-01-01 00:00:00', '2020-01-01 00:00:00',"
        " '2020-01-01 00:00:00')",
        (site_id,),
    )
    task_id = _exec_sql(
        "SELECT id FROM scan_tasks WHERE site_id = ?", (site_id,)
    )[0][0]

    # 新进程上线：lifespan 的启动恢复是被测入口，阈值 0 = 只要还
    # 在 running 就算孤儿。
    monkeypatch.setenv("SEO_CLAW_TASK_STALE_S", "0")
    with TestClient(app, raise_server_exceptions=False) as c2:
        st = _wait_job(c2, task_id)
    assert st["status"] == "done", f"孤儿任务没被捞回重跑：{st}"
