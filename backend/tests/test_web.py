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
from seoclaw.web import _MAX_TASKS, _TASKS, _next_id, _normalize_url


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
    import seoclaw.web as _webmod
    _webmod._INFLIGHT[0] = 0

    _TASKS.clear()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    _TASKS.clear()
    guard.public_limiter._buckets.clear()
    _webmod._INFLIGHT[0] = 0


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


def test_task_ids_are_unique():
    ids = [_next_id() for _ in range(50)]
    assert len(set(ids)) == 50


def test_memory_task_table_bounded():
    """内存任务表必须有上限，否则长期运行会被撑爆。"""
    assert _MAX_TASKS <= 1000


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
    """⚠️ _run 自己 import 失败时，异常发生在 try 之前。

    我第一版就是这个 bug：一个 ModuleNotFoundError 让任务卡在 running，
    而我在文件顶部刚写过「静默留在 running 会变成永远转圈的进度条」。
    done_callback 才是真正的兜底。
    """
    import seoclaw.web as webmod

    async def _dead(*a, **kw):
        raise ModuleNotFoundError("No module named 'seoclaw.web.api'")

    monkeypatch.setattr(webmod, "_run", _dead)

    st = _wait_job(client, _submit(client))
    assert st["status"] == "failed", "任务级异常没被兜住，会永远转圈"

# --------------------------------------------------------------------------
# 并发闸
# --------------------------------------------------------------------------
#
# ⚠️ 这道闸最阴的坑是「计数器忘了减」：症状是「刚才还好好的，
# 突然全站 503」，而且**极难定位**——日志里没有异常，没有报错，
# 只有一个慢慢涨上去再也降不下来的整数。我自己写第一版就漏了释放，
# 所以这里必须钉死。


def test_inflight_released_after_success(client):
    """跑完之后计数器必须回到 0。"""
    import seoclaw.web as webmod

    _wait_job(client, _submit(client))
    # done_callback 在事件循环里跑，轮询终态后可能还没执行完
    for _ in range(100):
        if webmod._INFLIGHT[0] == 0:
            break
        time.sleep(0.02)
    assert webmod._INFLIGHT[0] == 0, (
        f"计数器没释放：{webmod._INFLIGHT[0]}。"
        "再跑几次之后这个服务就永久 503 了"
    )


def test_inflight_released_after_failure(client, monkeypatch):
    """⚠️ 失败也必须释放。只在成功路径 release 的话，
    「爬虫一挂就永久 503」——比不设闸还糟。"""

    async def _boom(session, **kw):
        raise RuntimeError("炸了")

    monkeypatch.setattr("seoclaw.api.scan_service.run_scan", _boom)

    import seoclaw.web as webmod
    _wait_job(client, _submit(client))
    for _ in range(100):
        if webmod._INFLIGHT[0] == 0:
            break
        time.sleep(0.02)
    assert webmod._INFLIGHT[0] == 0, "任务失败后计数器没释放"


def test_inflight_released_when_task_never_starts(client, monkeypatch):
    """⚠️ 任务级异常（import 失败那种）也必须释放。

    `from ..api.scan_service import run_scan` 在 try **上面**，
    所以 _run 自己的 finally 覆盖不到那条路——我第一版就把释放
    写在 finally 里，结果这条路径漏了。
    """
    import seoclaw.web as webmod

    async def _dead(*a, **kw):
        raise ModuleNotFoundError("No module named 'seoclaw.web.api'")

    monkeypatch.setattr(webmod, "_run", _dead)
    _wait_job(client, _submit(client))
    for _ in range(100):
        if webmod._INFLIGHT[0] == 0:
            break
        time.sleep(0.02)
    assert webmod._INFLIGHT[0] == 0, "任务级异常路径没释放计数器"


def test_concurrency_limit_rejects_extra(client, monkeypatch):
    """超过上限要当场 503，而不是默默排队。

    排队等比拒绝更糟：用户等 5 分钟才知道要排 8 个人，
    不如当场告诉他「现在忙」。
    """

    async def _slow(session, **kw):
        # 卡住不返回，让前两个任务一直占着并发位
        import asyncio as _a
        await _a.sleep(30)

    monkeypatch.setattr("seoclaw.api.scan_service.run_scan", _slow)

    first = client.post("/api/v1/web/quick-scan", json={"url": "a.test"})
    second = client.post("/api/v1/web/quick-scan", json={"url": "b.test"})
    assert first.status_code == 202
    assert second.status_code == 202

    third = client.post("/api/v1/web/quick-scan", json={"url": "c.test"})
    assert third.status_code == 503, "超过并发上限却放行了"
    assert "Retry-After" in third.headers, "503 必须带 Retry-After"
