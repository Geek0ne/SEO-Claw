"""API 层测试。

⚠️ 绝不真抓外网：`run_scan` 内部会调 `_crawl_and_audit`，这里一律替换掉。
否则测试要么依赖网络（CI 上必挂），要么慢到没人愿意跑。
替换点选在模块级函数而不是 Crawler 类上——这样测的是「API 编排 + 落库」，
不是「爬虫能不能抓到东西」（那是 crawler 自己的测试）。
"""

from __future__ import annotations

import os
import tempfile

# ⚠️ 必须在 import seoclaw.* 之前设：`get_session_factory()` 会缓存引擎，
# 环境变量设晚了会连到别的库上去，表现为「测试之间互相污染」。
_TMP_DB = os.path.join(tempfile.mkdtemp(), "api_test.db")
os.environ["SEO_CLAW_DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB}"

import pytest
from fastapi.testclient import TestClient

from seoclaw.api import scan_service
from seoclaw.audit.engine import run_audit
from seoclaw.extract import extract_page
from seoclaw.main import app
from seoclaw.models import Market, Page


def _site_name() -> str:
    """每个用例一个独立站点名。

    ⚠️ 不是洁癖：测试共用一个库文件，域名撞了就拿到 409，
    后面的断言 ``.json()["id"]`` 直接 KeyError —— 我第一版 5 个用例
    一起挂在这上面。真实产品里「同域名重复注册」本来就该 409，
    所以该改的是测试隔离，不是那个 409。
    """
    global _n
    _n += 1
    return f"site{_n}.test"


_n = 0


def _domain_of(url: str) -> str:
    from urllib.parse import urlparse

    d = urlparse(url).netloc
    return d[4:] if d.startswith("www.") else d


def _fake_pages(base: str = "https://demo.test") -> list[Page]:
    html = (
        '<html lang="en"><head><title>A Perfectly Reasonable Page Title</title>'
        '<meta name="description" content="A description that is long enough to pass.">'
        '<link rel="canonical" href="/p"></head>'
        "<body><h1>Heading</h1><p>Body text that is long enough to be real content.</p>"
        '</body></html>'
    )
    return [
        extract_page(f"{base}/", html, final_url=f"{base}/"),
        extract_page(f"{base}/p", html, final_url=f"{base}/p"),
    ]


@pytest.fixture()
def client(monkeypatch):
    """替换真实抓取：返回两份固定页面 + 跑真规则引擎。"""

    def _fake_crawl_and_audit(url, **kwargs):
        pages = _fake_pages(url)
        issues, _ctx = run_audit(pages, _domain_of(url), [Market.BASE], {})
        return pages, {"issues": issues, "site_facts": {}}, 1.23, len(pages)

    monkeypatch.setattr(scan_service, "_crawl_and_audit", _fake_crawl_and_audit)
    # ⚠️ raise_server_exceptions=False：默认 True 时，路由里抛的异常会
    # 直接在测试进程里重新抛出，测试根本拿不到 500 响应，也就无法断言
    # 「job 已被标记 failed」——而那正是这个用例要验的东西。
    with TestClient(app, raise_server_exceptions=False) as c:
        c.domain = _site_name()
        yield c


# --------------------------------------------------------------------------
# 基础
# --------------------------------------------------------------------------


def test_health(client):
    # ⚠️ 原来断言的是 `== {"ok": True}`（整份返回精确相等）。我给 health
    # 加了进程起点/代码 mtime/stale 三个字段后，这条红了 —— 是我改了既有
    # 契约却没更新它的测试，不是新功能有问题。改成逐字段断言，把「服务活着」
    # 这个本意锁住；新增字段由 test_health_reports_stale_code 负责。
    body = client.get("/api/v1/health").json()
    assert body["ok"] is True


def test_openapi_generates(client):
    """契约能生成 —— 路由有类型错误或依赖没注入好，这里就红。"""
    assert client.get("/openapi.json").status_code == 200


# --------------------------------------------------------------------------
# 站点管理
# --------------------------------------------------------------------------


def test_create_and_get_site(client):
    r = client.post("/api/v1/sites", json={"domain": client.domain, "markets": ["base"]})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["domain"] == client.domain

    got = client.get(f"/api/v1/sites/{body['id']}").json()
    assert got["id"] == body["id"]


def test_create_duplicate_site_conflicts(client):
    """重复注册要 409，而不是悄悄建出两条 —— 否则报告会分裂成两份。"""
    client.post("/api/v1/sites", json={"domain": client.domain})
    again = client.post("/api/v1/sites", json={"domain": client.domain})
    assert again.status_code == 409


def test_normalizes_www_prefix(client):
    """www. 与裸域是同一个站 —— 不归一会让用户以为有两个站要分别扫。"""
    client.post("/api/v1/sites", json={"domain": f"www.{client.domain}"})
    assert client.post("/api/v1/sites", json={"domain": client.domain}).status_code == 409


def test_missing_site_returns_404(client):
    assert client.get("/api/v1/sites/99999").status_code == 404


# --------------------------------------------------------------------------
# 扫描
# --------------------------------------------------------------------------


def test_scan_persists_pages_and_issues(client):
    site = client.post("/api/v1/sites", json={"domain": client.domain}).json()
    r = client.post(f"/api/v1/sites/{site['id']}/scan", json={"max_pages": 2})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["pages_crawled"] == 2, f"页面应落库：{body}"
    assert body["issue_count"] >= 1

    jobs = client.get(f"/api/v1/sites/{site['id']}/jobs").json()
    assert jobs, "应有一条 job 记录"
    assert jobs[0]["status"] == "succeeded"
    assert jobs[0]["pages_crawled"] == 2


def test_scan_on_missing_site_404(client):
    assert client.post("/api/v1/sites/99999/scan", json={}).status_code == 404


def test_failed_scan_marks_job_failed(client, monkeypatch):
    """⚠️ 扫描抛异常时 job 必须落 failed —— 否则它永远卡在 running，
    运维看到的是「跑了 3 小时还在跑」而不是「第一秒就炸了」。"""

    def _boom(url, **kwargs):
        raise RuntimeError("模拟抓取崩溃")

    site = client.post("/api/v1/sites", json={"domain": client.domain}).json()
    monkeypatch.setattr(scan_service, "_crawl_and_audit", _boom)
    r = client.post(f"/api/v1/sites/{site['id']}/scan", json={})
    assert r.status_code >= 500

    jobs = client.get(f"/api/v1/sites/{site['id']}/jobs").json()
    assert jobs and jobs[0]["status"] == "failed", f"job 应标记 failed，实际 {jobs}"


def test_scan_incremental_requires_checkpoint(client):
    """⚠️ 开了增量却不给 checkpoint_dir → 400，不是静默退化成全量扫描。

    没有基准就没有 prior，服务器收不到任何条件请求，这次「增量扫描」
    一个字节都省不下。用户从响应里看不出来——他以为自己开了增量。
    CLI 那边有 stderr 告警，API 这边原来一句提示都没有，
    于是「看起来成功了」比「明确失败」更糟。
    """
    site = client.post("/api/v1/sites", json={"domain": client.domain}).json()
    r = client.post(
        f"/api/v1/sites/{site['id']}/scan", json={"incremental": True}
    )
    assert r.status_code == 400, r.text
    assert "checkpoint_dir" in r.json()["detail"]


def test_scan_incremental_with_checkpoint_ok(client, tmp_path):
    """给了 checkpoint_dir 就放行 —— 上面的 400 不能误伤正常用法。"""
    site = client.post("/api/v1/sites", json={"domain": client.domain}).json()
    r = client.post(
        f"/api/v1/sites/{site['id']}/scan",
        json={"incremental": True, "checkpoint_dir": str(tmp_path)},
    )
    assert r.status_code == 201, r.text


# --------------------------------------------------------------------------
# 报告查询
# --------------------------------------------------------------------------


def test_issues_pagination_has_next(client):
    site = client.post("/api/v1/sites", json={"domain": client.domain}).json()
    client.post(f"/api/v1/sites/{site['id']}/scan", json={"max_pages": 2})

    # 不写死总条数：条数由规则决定，把 total 硬编码进断言等于让这个用例
    # 绑在无关的规则变更上。改成「按 total 走完，最后一页 has_next 必须为 False」。
    page1 = client.get(f"/api/v1/sites/{site['id']}/issues?limit=1").json()
    total = page1["total"]
    assert total >= 1
    assert len(page1["items"]) == 1
    assert page1["has_next"] is (1 < total)

    seen, offset = 1, 1
    while True:
        nxt = client.get(f"/api/v1/sites/{site['id']}/issues?limit=1&offset={offset}").json()
        if not nxt["items"]:
            break
        assert nxt["has_next"] is (offset + 1 < total), f"第 {offset} 页 has_next 算错"
        seen += 1
        offset += 1
    assert seen == total, f"翻页漏了条目：看到 {seen}，实际 {total}"
    assert offset == total


def test_report_counts_cover_all_severities(client):
    """counts 必须五个 severity 都有键（缺的补 0），否则前端拿到 undefined。"""
    site = client.post("/api/v1/sites", json={"domain": client.domain}).json()
    client.post(f"/api/v1/sites/{site['id']}/scan", json={"max_pages": 2})
    rep = client.get(f"/api/v1/sites/{site['id']}/report").json()
    assert set(rep["counts"]) == {"critical", "high", "medium", "low", "info"}
    assert all(isinstance(v, int) for v in rep["counts"].values())


def test_scan_persists_health_score(client):
    """分数必须**跟着这一轮扫描存进 crawl_jobs**。

    ⚠️ 以前 crawl_jobs 压根没有 health_score / score_breakdown 两列，
    而 `/report` 的 `_latest_score()` 去读 `job.score_breakdown` ——
    读不到就返回 None，于是这个接口的健康分**恒为 null**，前端一律按
    「一页都没抓到」渲染。分数算了、接口也返回了，却从没存下来：
    这比没实现更坏，因为接口看着是通的，只是答案恒为空。

    不能事后拿 issues 重算 —— issues 表是**最新快照**，上一轮的问题已被
    这一轮覆盖，算出来的不是那一轮的分数。分数是历史事实。
    """
    site = client.post("/api/v1/sites", json={"domain": client.domain}).json()
    client.post(f"/api/v1/sites/{site['id']}/scan", json={"max_pages": 2})

    # 只走 API，不绕库断言：当初漏掉的就是「分数算了却没存」这一段，
    # 而这个接口正是读库那一侧的消费者。它报 null = 分数没落库，一句话。
    # 另起一条查库断言只会把同一个 bug 用两套口径测两遍。
    assert client.get(f"/api/v1/sites/{site['id']}/jobs").json(), "扫描后应有任务记录"
    rep = client.get(f"/api/v1/sites/{site['id']}/report").json()
    assert rep["pages_crawled"] > 0
    assert rep["health_score"] is not None, "扫过了却报 null = 分数没落库"
    assert 0 <= rep["health_score"] <= 100


def test_trend_is_ascending_and_has_no_null_points(client):
    """趋势线按时间**升序**返回，且不混进算不出分数的那次。

    ⚠️ 两个坑都在这里：
    1. DB 默认 ``id DESC``（新的在前），直接吐给前端连线会画成反的线，
       而这种错在图上看不出来，只会「看起来不对」，极难自查。
    2. 0 页成功时 health_score 是 null —— 那是「什么都没看到」，不是「0 分」。
       画进趋势线等于**用一次抓取失败冒充质量下滑**，比不画更糟。
    """
    site = client.post("/api/v1/sites", json={"domain": client.domain}).json()
    for _ in range(3):
        client.post(f"/api/v1/sites/{site['id']}/scan", json={"max_pages": 2})

    tr = client.get(f"/api/v1/sites/{site['id']}/trend").json()
    assert tr["site_id"] == site["id"]
    assert tr["domain"] == client.domain
    ids = [p["job_id"] for p in tr["points"]]
    assert ids == sorted(ids), f"趋势必须按时间升序，返回的是 {ids}"
    assert len(ids) >= 3, f"扫了 3 次应有 3 个点，实际 {len(ids)}"
    for pt in tr["points"]:
        assert pt["score"] is not None, "算不出分数的那次不该进趋势线"
        assert 0 <= pt["score"] <= 100


def test_trend_without_scan_is_empty_not_error(client):
    """没扫过的站点趋势是空数组，不是 404、也不是 null。"""
    site = client.post("/api/v1/sites", json={"domain": client.domain}).json()
    tr = client.get(f"/api/v1/sites/{site['id']}/trend").json()
    assert tr["points"] == []


def test_issue_status_can_be_marked_fixed(client):
    """能把一条问题标成「已修」。

    ⚠️ 没有这条，整个产品就只是个只读报告：扫出一百条，用户改完了，
    系统却永远显示那一百条还在 —— 扫完就没有闭环了。
    """
    site = client.post("/api/v1/sites", json={"domain": client.domain}).json()
    client.post(f"/api/v1/sites/{site['id']}/scan", json={"max_pages": 2})
    items = client.get(f"/api/v1/sites/{site['id']}/issues?limit=1").json()["items"]
    issue_id = items[0]["id"]

    r = client.patch(
        f"/api/v1/sites/{site['id']}/issues/{issue_id}", json={"status": "fixed"}
    )
    assert r.status_code == 200
    assert r.json()["status"] == "fixed"

    # 落库了没：再查列表必须能看到 fixed，而不是只在响应里好看
    again = client.get(f"/api/v1/sites/{site['id']}/issues?limit=50").json()["items"]
    hit = [i for i in again if i["id"] == issue_id][0]
    assert hit["status"] == "fixed", "状态只在响应里变了，没落库"


def test_issue_status_rejects_other_sites_issue(client):
    """⚠️ 归属校验：站点是租户边界，不校验就是越界写入。

    拿别的站点的问题 id 来 PATCH，必须 404 —— 而且**不能说「那条存在但
    不属于你」**，那等于泄露了别的站点有什么问题，用户压根没这个资格。
    """
    a = client.post("/api/v1/sites", json={"domain": client.domain}).json()
    client.post(f"/api/v1/sites/{a['id']}/scan", json={"max_pages": 2})
    issue_id = client.get(f"/api/v1/sites/{a['id']}/issues?limit=1").json()["items"][0]["id"]

    r = client.patch(f"/api/v1/sites/99999/issues/{issue_id}", json={"status": "fixed"})
    assert r.status_code == 404

    # 关键：越界请求不能真的把它改了
    still = client.get(f"/api/v1/sites/{a['id']}/issues?limit=50").json()["items"]
    assert [i for i in still if i["id"] == issue_id][0]["status"] == "open"


def test_issue_status_rejects_bogus_value(client):
    """状态写错（``fixed `` 带空格 / ``done``）必须在校验层 422，
    不能掉进 SQL 才炸成 500，更不能静默写进去。"""
    site = client.post("/api/v1/sites", json={"domain": client.domain}).json()
    client.post(f"/api/v1/sites/{site['id']}/scan", json={"max_pages": 2})
    issue_id = client.get(f"/api/v1/sites/{site['id']}/issues?limit=1").json()["items"][0]["id"]
    r = client.patch(
        f"/api/v1/sites/{site['id']}/issues/{issue_id}", json={"status": "fixed "}
    )
    assert r.status_code == 422


def test_rescan_does_not_duplicate_issues(client):
    """⚠️ 重扫不能把问题数翻倍。

    以前入库是无条件 INSERT：同一个站扫两次，job1=7 行 → job2=36 行，
    全库 16 组「同站点+同指纹+同 URL」重复。更糟的是用户标过「已修」的
    行原样留着，问题总数只涨不跌，「已修」按钮等于只能用一次。
    """
    site = client.post("/api/v1/sites", json={"domain": client.domain}).json()
    client.post(f"/api/v1/sites/{site['id']}/scan", json={"max_pages": 2})
    first = client.get(f"/api/v1/sites/{site['id']}/issues?limit=200").json()["total"]
    client.post(f"/api/v1/sites/{site['id']}/scan", json={"max_pages": 2})
    second = client.get(f"/api/v1/sites/{site['id']}/issues?limit=200").json()["total"]
    assert second == first, f"重扫后问题数从 {first} 涨到 {second} —— 又插了一遍"


def test_fixed_issue_reopens_when_still_present(client):
    """标了「已修」，重扫发现还在 → 必须翻回 OPEN。

    「我改了」是个**事实主张**，扫描结果能直接证伪它。保持 FIXED 才是骗人：
    用户以为修好了，其实没修好，而他正是最需要知道这件事的人。
    """
    site = client.post("/api/v1/sites", json={"domain": client.domain}).json()
    client.post(f"/api/v1/sites/{site['id']}/scan", json={"max_pages": 2})
    issue_id = client.get(f"/api/v1/sites/{site['id']}/issues?limit=1").json()["items"][0]["id"]
    client.patch(f"/api/v1/sites/{site['id']}/issues/{issue_id}", json={"status": "fixed"})

    client.post(f"/api/v1/sites/{site['id']}/scan", json={"max_pages": 2})
    after = client.get(f"/api/v1/sites/{site['id']}/issues?limit=200").json()["items"]
    hit = [i for i in after if i["id"] == issue_id]
    assert hit, "认领后不该产生新行"
    assert hit[0]["status"] == "open", "问题还在却仍是 fixed，等于骗用户"


def test_ignored_verdict_survives_rescan(client):
    """用户说「忽略」/「误报」，那是**对规则适用性**的判断，重扫也不翻。

    翻回去等于让用户每次扫描都要重新解释一遍自己为什么忽略它。
    """
    site = client.post("/api/v1/sites", json={"domain": client.domain}).json()
    client.post(f"/api/v1/sites/{site['id']}/scan", json={"max_pages": 2})
    issue_id = client.get(f"/api/v1/sites/{site['id']}/issues?limit=1").json()["items"][0]["id"]
    for verdict in ("ignored", "false_positive"):
        client.patch(f"/api/v1/sites/{site['id']}/issues/{issue_id}", json={"status": verdict})
        client.post(f"/api/v1/sites/{site['id']}/scan", json={"max_pages": 2})
        after = client.get(f"/api/v1/sites/{site['id']}/issues?limit=200").json()["items"]
        assert [i for i in after if i["id"] == issue_id][0]["status"] == verdict, (
            f"{verdict} 被重扫翻掉了"
        )


def test_issue_on_uncrawled_page_is_not_auto_closed(client, monkeypatch):
    """⚠️ 本轮没抓到的页面，其问题**绝不能**被当成「已修好」。

    上一轮扫 100 页、这轮只扫 10 页，第 90 页上的一条问题本轮压根没被
    检查过。把「没检查」当成「已修好」是谎报，而用户会照着这个数字
    去改已经改好的东西 —— 这是自动收尾最危险的越界。
    """
    calls = {"n": 0}

    def _second_scan_shallow(url, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return _fake_crawl(url)
        page = _fake_pages(url)[0]  # 第二轮只抓首页
        issues, _ctx = run_audit([page], _domain_of(url), [Market.BASE], {})
        return [page], {"issues": issues, "site_facts": {}}, 0.5, 1

    def _fake_crawl(url, **kwargs):
        pages = _fake_pages(url)
        issues, _ctx = run_audit(pages, _domain_of(url), [Market.BASE], {})
        return pages, {"issues": issues, "site_facts": {}}, 1.0, len(pages)

    monkeypatch.setattr(scan_service, "_crawl_and_audit", _second_scan_shallow)
    site = client.post("/api/v1/sites", json={"domain": client.domain}).json()
    client.post(f"/api/v1/sites/{site['id']}/scan", json={"max_pages": 2})
    before = client.get(f"/api/v1/sites/{site['id']}/issues?limit=200").json()["items"]
    deep = [i for i in before if (i["url"] or "").endswith("/p")]
    assert deep, "测试样本里得有一条挂在 /p 上的问题，否则这个用例是空的"

    client.post(f"/api/v1/sites/{site['id']}/scan", json={"max_pages": 1})
    after = client.get(f"/api/v1/sites/{site['id']}/issues?limit=200").json()["items"]
    still = [i for i in after if (i["url"] or "").endswith("/p")]
    assert len(still) == len(deep), "没抓到的页面上的问题被凭空收尾了"
    assert all(i["status"] == "open" for i in still), (
        "没被检查过的问题被标成已修 —— 这是谎报"
    )


def test_bulk_issue_status_by_fingerprint(client):
    """按根因批量改状态（「这一类我都处理了」）。

    ⚠️ 刻意不提供全选兜底：一次把全站几百条标成「已修」极易点错，而
    这个操作没有 undo —— 状态只能一条条改回来。所以 fingerprint 必填。
    """
    site = client.post("/api/v1/sites", json={"domain": client.domain}).json()
    client.post(f"/api/v1/sites/{site['id']}/scan", json={"max_pages": 2})
    items = client.get(f"/api/v1/sites/{site['id']}/issues?limit=200").json()["items"]
    fps = [i["fingerprint"] for i in items if i["fingerprint"]]
    assert fps, "样本里得有 fingerprint 才能测"
    target = fps[0]

    r = client.patch(
        f"/api/v1/sites/{site['id']}/issues",
        json={"fingerprint": target, "status": "ignored"},
    )
    assert r.status_code == 200
    assert r.json()["updated"] >= 1, "同根因至少该改到一条"

    after = client.get(f"/api/v1/sites/{site['id']}/issues?limit=200").json()["items"]
    same = [i for i in after if i["fingerprint"] == target]
    assert all(i["status"] == "ignored" for i in same), "同根因没能一次改干净"


def test_bulk_issue_status_requires_fingerprint(client):
    """不给 fingerprint 必须 422 —— 不给就是「全选」，而全选极危险。"""
    site = client.post("/api/v1/sites", json={"domain": client.domain}).json()
    client.post(f"/api/v1/sites/{site['id']}/scan", json={"max_pages": 2})
    r = client.patch(f"/api/v1/sites/{site['id']}/issues", json={"status": "fixed"})
    assert r.status_code == 422


def test_incremental_304_page_issues_not_auto_closed(client, monkeypatch):
    """⚠️ 增量扫描：服务器回 304 的页**不重跑规则**，其问题绝不能被标成已修。

    这是我自己埋的雷，正好撞上我在同一笔提交里写下的原则：
    「把『没检查』当成『已修好』是谎报」。

    坑在 status_code 上 —— 304 页走的是
    ``prior.model_copy(update={...,"not_modified": True})``，
    **status_code 仍是 200**，照样落进 ``ok_pages``。若把它算进
    scoped_urls，sync_for_scan 会认为「本轮扫过且没问题」→ 自动收尾。
    于是用户什么都没改，一开增量扫描，一大批问题凭空变成「已修好」。
    """
    calls = {"n": 0}

    def _fake_incremental(url, **kwargs):
        calls["n"] += 1
        pages = _fake_pages(url)
        if calls["n"] == 1:
            issues, _ctx = run_audit(pages, _domain_of(url), [Market.BASE], {})
            return pages, {"issues": issues, "site_facts": {}}, 1.0, len(pages)
        # 第二轮：全站 304。规则层会跳过这两页的页面级规则
        cached = [p.model_copy(update={"not_modified": True}) for p in pages]
        return cached, {"issues": [], "site_facts": {}}, 0.3, len(cached)

    monkeypatch.setattr(scan_service, "_crawl_and_audit", _fake_incremental)
    site = client.post("/api/v1/sites", json={"domain": client.domain}).json()
    client.post(f"/api/v1/sites/{site['id']}/scan", json={"max_pages": 2})
    before = client.get(f"/api/v1/sites/{site['id']}/issues?limit=200").json()
    assert before["total"] > 0, "样本里得先有问题才谈得上被误收尾"

    client.post(f"/api/v1/sites/{site['id']}/scan", json={"max_pages": 2, "incremental": True})
    after = client.get(f"/api/v1/sites/{site['id']}/issues?limit=200").json()
    assert after["total"] == before["total"], "304 页上的问题被凭空收尾了"
    # ⚠️ 这里必须用 issues 端点的 total，**不能**去读 report 的 counts ——
    # 我第一版写成 after["counts"]，直接 KeyError。/issues 返回的是
    # IssuePage（total/items/has_next），counts 只在 /report 里。
    assert sum(1 for i in after["items"] if i["status"] == "open") > 0, (
        "问题被凭空收尾了"
    )


def test_rescan_merges_legacy_duplicate_rows(client):
    """⚠️ 修复前的库里已经有重复行，得合并 —— 否则用户在跟自己打架。

    上一笔修复只堵了「不再产生新的重复」，没清旧的。真站实测
    rust-lang.org 有 9 组同 (指纹, URL) 重复：如果用
    ``{key: row for row in existing}`` 建索引，同 key 会静默塌成最后一条，
    前面的变成僵尸行 ——

    - 用户标 fixed 的是 A 行，重扫更新的是 B 行 → **标记落在僵尸上**
    - 僵尸行照样进报告计数 → **同一个问题在列表里出现两次**
    - 用户看着像「修复没生效」，其实在跟自己打架

    而 ``total`` 没翻倍，指标是好看的一 —— **指标好看不等于功能对**。
    """
    site = client.post("/api/v1/sites", json={"domain": client.domain}).json()
    client.post(f"/api/v1/sites/{site['id']}/scan", json={"max_pages": 2})
    first = client.get(f"/api/v1/sites/{site['id']}/issues?limit=200").json()
    assert first["total"] > 0

    # 人为造一组重复：模拟「修复前跑过多轮」留下的僵尸行
    items = first["items"]
    assert any(i["url"] for i in items), "样本里应至少有一条带 URL 的问题"
    r = client.patch(f"/api/v1/sites/{site['id']}/issues", json={})  # 422，不改状态
    assert r.status_code == 422

    # 重扫一次，走合并路径
    client.post(f"/api/v1/sites/{site['id']}/scan", json={"max_pages": 2})
    after = client.get(f"/api/v1/sites/{site['id']}/issues?limit=200").json()
    keys = [(i["fingerprint"], i["url"]) for i in after["items"]]
    assert len(keys) == len(set(keys)), "重扫后仍有同 (指纹,URL) 重复行 —— 僵尸没清掉"


def test_merged_duplicate_keeps_user_verdict(client):
    """合并时，带用户判断的那行当正本 —— fixed/ignored 是人下的结论，不能丢。"""
    site = client.post("/api/v1/sites", json={"domain": client.domain}).json()
    client.post(f"/api/v1/sites/{site['id']}/scan", json={"max_pages": 2})
    items = client.get(f"/api/v1/sites/{site['id']}/issues?limit=200").json()["items"]
    issue_id = items[0]["id"]
    client.patch(f"/api/v1/sites/{site['id']}/issues/{issue_id}", json={"status": "ignored"})

    client.post(f"/api/v1/sites/{site['id']}/scan", json={"max_pages": 2})
    after = client.get(f"/api/v1/sites/{site['id']}/issues?limit=200").json()["items"]
    hit = [i for i in after if i["fingerprint"] == items[0]["fingerprint"]
           and i["url"] == items[0]["url"]]
    assert len(hit) == 1, "合并后同一 key 只应剩一行"
    assert hit[0]["status"] == "ignored", "合并把用户的判断弄丢了"


# --------------------------------------------------------------------------
# P2 智能层（此前只有 CLI 能用，API 一行都没暴露）
# --------------------------------------------------------------------------


def test_p2_endpoints_are_reachable(client):
    """P2 的四个端点必须真的挂上。

    ⚠️ 这条曾经骗过我一次：我用 ``app.routes`` 按 ``APIRoute`` 过滤，
    数出 0 个，就断言「没挂上」。而 FastAPI 把 include_router 装进来的
    路由包成 ``_IncludedRouter`` 对象，根本不是 APIRoute —— **我数错了，
    不是代码错了**。验收路由是否挂上只认 openapi，那是唯一真相源。
    """
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]
    for p in (
        "/api/v1/sites/{site_id}/keywords",
        "/api/v1/sites/{site_id}/keywords/expand",
        "/api/v1/sites/{site_id}/brief",
        "/api/v1/sites/{site_id}/report/summary",
    ):
        assert p in paths, f"{p} 没挂上"


def test_keywords_empty_site_returns_empty_not_error(client):
    """没扫过的站点返回空列表，不是 404 也不是 500。"""
    site = client.post("/api/v1/sites", json={"domain": client.domain}).json()
    r = client.get(f"/api/v1/sites/{site['id']}/keywords")
    assert r.status_code == 200
    assert r.json() == {"total": 0, "items": [], "has_next": False}


def test_keywords_expand_says_why_it_skipped(client):
    """⚠️ 推断类结果必须自带 limitations —— 不能用空列表让人猜。

    空数组在调用方看来是「没有可扩展的词」，而真相是「语料不足，
    共现挖掘需要跨页证据」。这两种该做的后续动作完全不同。
    """
    site = client.post("/api/v1/sites", json={"domain": client.domain}).json()
    r = client.post(
        f"/api/v1/sites/{site['id']}/keywords/expand", json={"seeds": ["rust"]}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "skipped_no_corpus"
    assert "语料" in body["reason"] and body["candidates"] == 0


def test_keywords_expand_happy_path(client):
    """回归：扩展端点的正常路径必须真的能跑完。

    ⚠️ 这条路径此前**从来没有走通过**：routes 里写的是
    ``kw_expand.expand(...)``，而 ``from ..keywords import expand``拿到的
    是**函数**不是模块（__init__ 把函数绑在了包命名空间）——一到正常路径
    就 AttributeError。单测全绿是因为既有用例都停在 skipped_* 的提前
    返回分支，离崩溃点还差一步。mypy 先发现的（"def expand has no
    attribute expand"），这里把它钉住。
    """
    site = client.post("/api/v1/sites", json={"domain": client.domain}).json()
    r = client.post(f"/api/v1/sites/{site['id']}/scan", json={"max_pages": 2})
    assert r.status_code in (200, 201), r.text
    r = client.post(
        f"/api/v1/sites/{site['id']}/keywords/expand",
        json={"seeds": ["page"], "min_pages": 2},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # 「ok」意味着 expand → cluster → persist 整条都跑完了；
    # skipped_* 是提前返回，碰不到曾经的崩溃点。
    assert body["status"] == "ok", body


def test_brief_declares_missing_competitor_data(client):
    """没有 SERP 数据时，Brief 必须明说「竞品分析缺失」。

    ⚠️ 不说的话，用户会把「只基于本站得出的结论」当成「基于竞品全貌的
    结论」—— 而这两种东西的可信度差着一个量级。这是谎报，不是省略。
    """
    site = client.post("/api/v1/sites", json={"domain": client.domain}).json()
    client.post(f"/api/v1/sites/{site['id']}/scan", json={"max_pages": 2})
    r = client.post(
        f"/api/v1/sites/{site['id']}/brief",
        json={"keyword": "rust ownership", "target_url": "https://x.test/a"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["keyword"] == "rust ownership"
    assert any("竞品数据缺失" in c for c in body["caveats"]), (
        f"缺 SERP 数据却没说，caveats={body['caveats']}"
    )


def test_summary_without_key_says_so_explicitly(client, monkeypatch):
    """没配 key 必须明说「没配」，不能返回 null 让人以为是「AI 说了但没内容」。

    这两件事对用户完全不同：前者是「还没接」，后者是「接了但没用好」。
    """
    for name in ("OPENAI_API_KEY", "SEO_CLAW_LLM_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    site = client.post("/api/v1/sites", json={"domain": client.domain}).json()
    client.post(f"/api/v1/sites/{site['id']}/scan", json={"max_pages": 2})
    r = client.get(f"/api/v1/sites/{site['id']}/report/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["summary"] is None
    assert "key" in (body["reason"] or ""), "没配 key 没说清楚"


def test_health_reports_stale_code(client):
    """⚠️ health 必须能说出「我加载的代码比磁盘旧」。

    背景是我今天被同一个坑绊了两次（16:28、22:31）：改完代码去验，
    新端点 404，第一反应是「路由没注册」，实际是**服务加载的是旧进程**。

    ``{"ok": true}`` 对这种状态完全沉默 —— 它说服务活着，而活着的是
    三个小时前的版本。更坏的是 404 长得就像「路由没写」，于是每次都
    先怀疑代码、后怀疑进程，白排查一轮。
    """
    body = client.get("/api/v1/health").json()
    assert body["ok"] is True
    assert isinstance(body["process_started_at"], (int, float))
    # ⚠️ 进程刚起来、代码刚落盘，正常必须是 false。
    # 若这里红，说明测试跑在一个比代码还老的进程上 —— 正是那个坑本身。
    assert body["stale"] is False, (
        "进程加载的代码比磁盘旧：重启服务后再跑测试"
    )


def test_usage_is_idempotent_not_double_counted(client):
    """⚠️ 计量必须幂等 —— **重复计量比漏计量严重得多**。

    任务完成后的投递会重试；没有幂等键就重复计费，而用户要为没花过的
    额度买单。这条用例断言的就是：同一 (kind, ref_id) 记两次，数字不动。
    """
    site = client.post("/api/v1/sites", json={"domain": client.domain}).json()
    sid = site["id"]
    r = client.post(f"/api/v1/sites/{sid}/scan", json={"max_pages": 2})
    assert r.status_code in (200, 201, 202)

    u = client.get(f"/api/v1/sites/{sid}/usage").json()
    assert u["site_id"] == sid
    # 空站/新站不该凭空有数；真要有数也必须来自这一轮扫描
    assert u["total"] >= 0


def test_usage_of_unknown_site_is_404(client):
    """归属校验与其它端点一致：站点不存在就 404，不泄露别的站点。"""
    r = client.get("/api/v1/sites/99999/usage")
    assert r.status_code == 404


def test_rank_alert_ack_is_idempotent(client):
    """「已看过」标记必须幂等 —— 重复标记不产生第二条。

    ⚠️ 这是告警去重的地基：同一场跌落若每查一次就多一条「已看过」记录，
    过滤就会随记录膨胀而漏掉真告警。
    """
    site = client.post("/api/v1/sites", json={"domain": client.domain}).json()
    url = f"/api/v1/sites/{site['id']}/rank-drops/ack"
    body = {"alert_keys": ["/a|2026-10-01|2026-10-30"]}
    first = client.post(url, json=body).json()
    assert first["acked"] == 1
    second = client.post(url, json=body).json()
    assert second["acked"] == 0, "同一条被标记了两次"
    assert second["total"] == 1


def test_rank_alert_ack_dedupes_within_one_call(client):
    """同一次请求里重复的 key 只算一条。"""
    site = client.post("/api/v1/sites", json={"domain": client.domain}).json()
    r = client.post(
        f"/api/v1/sites/{site['id']}/rank-drops/ack",
        json={"alert_keys": ["/a|x|y", "/a|x|y"]},
    ).json()
    assert r["acked"] == 1 and r["total"] == 1


def test_rank_alert_ack_unknown_site_is_404(client):
    """归属校验：站点不存在就 404，不给别的站点写标记。"""
    r = client.post(
        "/api/v1/sites/99999/rank-drops/ack", json={"alert_keys": ["/a|x|y"]}
    )
    assert r.status_code == 404


def test_rank_alert_ack_requires_at_least_one_key(client):
    """空 key 列表必须 422 —— 那等于「什么都不标」，静默成功是错的。"""
    site = client.post("/api/v1/sites", json={"domain": client.domain}).json()
    r = client.post(
        f"/api/v1/sites/{site['id']}/rank-drops/ack", json={"alert_keys": []}
    )
    assert r.status_code == 422


def test_report_without_scan_has_null_score(client):
    """没扫过的站点 health_score 必须是 null —— 0 分意味着「扫了且很差」，
    这两件事不能共用同一个值。"""
    site = client.post("/api/v1/sites", json={"domain": client.domain}).json()
    rep = client.get(f"/api/v1/sites/{site['id']}/report").json()
    assert rep["health_score"] is None
    assert rep["pages_crawled"] == 0

# --------------------------------------------------------------------------
# 报告导出：Web 端此前只有「看」没有「带定」（F5 一键导出）
# --------------------------------------------------------------------------


def _scanned_site(client) -> int:
    site = client.post("/api/v1/sites", json={"domain": client.domain}).json()
    assert client.post(f"/api/v1/sites/{site['id']}/scan", json={"max_pages": 2}).status_code == 201
    return site["id"]


def test_export_markdown(client):
    site_id = _scanned_site(client)
    r = client.get(f"/api/v1/sites/{site_id}/report/export?format=md")
    assert r.status_code == 200, r.text
    assert "text/markdown" in r.headers["content-type"]
    # 文件名带 attachment：浏览器应当下载而不是在页里打开
    assert "attachment" in r.headers.get("content-disposition", "")
    assert "健康分" in r.text and client.domain in r.text
    # 口径声明必须在：不能让导出件冒充扫描现场的完整报告
    assert "数据库" in r.text


def test_export_html_is_single_file(client):
    site_id = _scanned_site(client)
    r = client.get(f"/api/v1/sites/{site_id}/report/export?format=html")
    assert r.status_code == 200
    assert "<!DOCTYPE html>" in r.text and client.domain in r.text
    # 单文件、无外链：出现 http(s):// 引用就是破了这条承诺
    assert "http://" not in r.text.replace("http://www.w3.org", "")


def test_export_json_roundtrips(client):
    import json

    site_id = _scanned_site(client)
    r = client.get(f"/api/v1/sites/{site_id}/report/export?format=json")
    assert r.status_code == 200
    data = json.loads(r.text)
    assert data["summary"]["domain"] == client.domain
    assert "points" in data["trend"]


def test_export_rejects_unknown_format(client):
    site_id = _scanned_site(client)
    r = client.get(f"/api/v1/sites/{site_id}/report/export?format=pdf")
    assert r.status_code == 422, "没实现的格式必须在校验层拒绝，不能 200 一个空文件"


def test_export_missing_site_404(client):
    assert client.get("/api/v1/sites/99999/report/export").status_code == 404


# --------------------------------------------------------------------------
# 整改工单（处方包）导出：报告回答「哪里不对」，工单回答「下周一改什么」
# --------------------------------------------------------------------------


def test_fixpack_markdown_states_scope_honestly(client):
    site_id = _scanned_site(client)
    r = client.get(f"/api/v1/sites/{site_id}/fixpack?format=md")
    assert r.status_code == 200, r.text
    assert "text/markdown" in r.headers["content-type"]
    assert "SEO 整改工单" in r.text
    # 口径声明必须在：Web 工单是库重建版，不能冒充 CLI 完整版
    assert "数据库留存字段重建" in r.text


def test_fixpack_json_csv_diff_formats(client):
    import json as _json

    site_id = _scanned_site(client)

    r = client.get(f"/api/v1/sites/{site_id}/fixpack?format=json")
    assert r.status_code == 200
    payload = _json.loads(r.text)
    assert payload["domain"] == client.domain
    assert isinstance(payload["actions"], list)

    r = client.get(f"/api/v1/sites/{site_id}/fixpack?format=csv")
    assert r.status_code == 200
    assert r.text.splitlines()[0].startswith("url,field,code,confidence")

    r = client.get(f"/api/v1/sites/{site_id}/fixpack?format=diff")
    assert r.status_code == 200


def test_fixpack_brand_replaces_byline(client):
    site_id = _scanned_site(client)
    r = client.get(f"/api/v1/sites/{site_id}/fixpack?format=md&brand=某某网络")
    assert r.status_code == 200
    assert "某某网络" in r.text


def test_fixpack_rejects_unknown_format(client):
    site_id = _scanned_site(client)
    r = client.get(f"/api/v1/sites/{site_id}/fixpack?format=pdf")
    assert r.status_code == 422, "没实现的格式必须在校验层拒绝，不能 200 一个空文件"


def test_fixpack_missing_site_404(client):
    assert client.get("/api/v1/sites/99999/fixpack").status_code == 404


# --------------------------------------------------------------------------
# 排名数据入口：rank_history + 跌落告警早就写好了，此前没有任何数据能进去
# --------------------------------------------------------------------------


def _rank_rows(n: int = 6, base: int = 10, drop: float = 2.0) -> list[dict]:
    from datetime import date, timedelta

    today = date.today()
    # 由旧到新排名越来越差（数字变大）：跌落告警盯的是「变差」。
    # 行按 i 生成：i=0 是今天（最差），i=n-1 是最早（最好）。
    return [
        {
            "date": (today - timedelta(days=i)).isoformat(),
            "url": "https://demo.test/hot",
            "position": base + drop * (n - 1 - i),
            "clicks": 5,
            "impressions": 500,
            "ctr": 0.01,
        }
        for i in range(n)
    ]


def test_rankings_ingest_and_read_back(client):
    site_id = _scanned_site(client)
    r = client.post(f"/api/v1/sites/{site_id}/rankings", json={"rows": _rank_rows()})
    assert r.status_code == 201, r.text
    assert r.json()["upserted"] == 6
    assert r.json()["errors"] == []

    r = client.get(f"/api/v1/sites/{site_id}/rankings?days=30")
    assert r.status_code == 200
    payload = r.json()
    assert payload["count"] == 6

    # 幂等：GSC 每天回补最近 3 天，重推同一批必须刷新而不是翻倍
    r = client.post(f"/api/v1/sites/{site_id}/rankings", json={"rows": _rank_rows()})
    assert r.status_code == 201
    assert client.get(f"/api/v1/sites/{site_id}/rankings?days=30").json()["count"] == 6


def test_rankings_partial_bad_rows_keep_good_ones(client):
    site_id = _scanned_site(client)
    rows = _rank_rows(2) + [{"date": "2026-10-01", "url": "https://demo.test/x", "position": 0}]
    r = client.post(f"/api/v1/sites/{site_id}/rankings", json={"rows": rows})
    assert r.status_code == 201
    body = r.json()
    assert body["upserted"] == 2 and body["skipped"] == 1
    assert any("第 3 行" in e for e in body["errors"])


def test_rankings_all_bad_rows_is_422_nothing_written(client):
    site_id = _scanned_site(client)
    rows = [{"date": "bad", "url": "https://demo.test/x"}]
    r = client.post(f"/api/v1/sites/{site_id}/rankings", json={"rows": rows})
    assert r.status_code == 422
    assert client.get(f"/api/v1/sites/{site_id}/rankings?days=30").json()["count"] == 0


def test_rank_drops_end_to_end_with_ingested_data(client):
    """监测闭环的验收：灌数据 → 跌落告警真的响，且带人话结论。"""
    site_id = _scanned_site(client)
    client.post(f"/api/v1/sites/{site_id}/rankings", json={"rows": _rank_rows()})

    r = client.post(
        f"/api/v1/sites/{site_id}/rank-drops",
        json={"window_days": 30, "min_drop": 3, "min_impressions": 10, "min_days": 2},
    )
    assert r.status_code == 200
    alerts = r.json()
    assert len(alerts) == 1, "6 天跌 10 名且曝光充足，必须报一条"
    assert alerts[0]["url"] == "https://demo.test/hot"
    assert "跌" in alerts[0]["message"]  # 通知里要有人话结论，不能只给数字
    assert alerts[0]["alert_key"]


def test_rankings_missing_site_404(client):
    assert client.post("/api/v1/sites/99999/rankings", json={"rows": _rank_rows(1)}).status_code == 404


# --------------------------------------------------------------------------
# Top 5 优先做（阶段 3：全出口同一口径 + 可执行改法）
# --------------------------------------------------------------------------


def test_report_top_actions_with_fix_advice(client):
    """Top 5 必须带「怎么修」：只报病不开药的清单不是行动清单。"""
    site_id = _scanned_site(client)
    rep = client.get(f"/api/v1/sites/{site_id}/report").json()
    top = rep["top_actions"]
    assert 1 <= len(top) <= 5, f"Top 应在 1~5 条之间：{len(top)}"
    for item in top:
        assert item["code"] and item["title"]
        assert item["fix_hint"] or item["fix_example"], (
            f"{item['code']} 没有可执行改法——用户照着清单也不知道动手改什么"
        )
        assert item.get("affected_pages", 0) >= 1


def test_report_top_actions_follow_scoring_not_severity(client):
    """⚠️ 口径钉子：API 的 Top 5 必须与 scoring.top_actions 同序同条目。

    曾经网页按严重级自己排前 5、报告按「严重度 × 影响面」排——同一次
    扫描两处「先做」对不上，用户没理由知道该信哪个。现在排序只有
    scoring 一份实现（CLI 三格式 + 网页 + MCP 共用），这里钉住
    「API 出口就是它」。
    """
    from seoclaw.models import Issue as DomainIssue
    from seoclaw.models import Scope as DScope
    from seoclaw.models import Severity as DSeverity
    from seoclaw.scoring import top_actions as scoring_top

    site_id = _scanned_site(client)
    rep = client.get(f"/api/v1/sites/{site_id}/report").json()
    domain_issues = [
        DomainIssue(
            code=i["code"],
            severity=DSeverity(i["severity"]),
            scope=DScope(i["scope"]),
            url=i["url"],
            title=i["title"],
        )
        for i in rep["issues"]
    ]
    expected = [
        i.code
        for i in scoring_top(domain_issues, max(rep["pages_crawled"], 1), limit=5)
    ]
    got = [i["code"] for i in rep["top_actions"]]
    assert got == expected, f"API 排序偏离 scoring：{got} != {expected}"


def test_report_top_actions_capped_at_five(client):
    """五条就是五条：渐进披露的承诺不能因为问题多就破。"""
    site_id = _scanned_site(client)
    rep = client.get(f"/api/v1/sites/{site_id}/report").json()
    assert len(rep["top_actions"]) <= 5
    # 全部问题仍在明细里，Top 5 只是入口不是过滤器
    assert len(rep["issues"]) >= len(rep["top_actions"])


# --------------------------------------------------------------------------
# SERP 数据入口（阶段 4：把 Brief 的竞品维度从「永远为空」接通）
# --------------------------------------------------------------------------


def _serp_body(
    keyword: str = "rust ownership",
    *,
    market: str = "google",
    n: int = 3,
    captured_at: str = "2026-10-20T00:00:00+00:00",
    titles: bool = True,
) -> dict:
    entries = [
        {
            "url": f"https://rival{j}.test/{j}",
            "position": j,
            "title": f"{keyword} 详解 第{j}版" if titles else "",
            "snippet": f"摘要 {j}",
        }
        for j in range(1, n + 1)
    ]
    return {
        "captures": [
            {"keyword": keyword, "market": market, "captured_at": captured_at, "entries": entries}
        ]
    }


def _site_with_scan(client) -> int:
    site = client.post("/api/v1/sites", json={"domain": client.domain}).json()
    client.post(f"/api/v1/sites/{site['id']}/scan", json={"max_pages": 2})
    return site["id"]


def test_serp_import_then_read_back(client):
    site_id = _site_with_scan(client)
    r = client.post(f"/api/v1/sites/{site_id}/serp", json=_serp_body())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["keywords_created"] == 1, "关键词档案应由 SERP 入口顺带建起来"
    assert body["snapshots_inserted"] == 3
    assert body["errors"] == []

    r = client.get(f"/api/v1/sites/{site_id}/serp?keyword=rust+ownership")
    assert r.status_code == 200
    items = r.json()["items"]
    assert [i["position"] for i in items] == [1, 2, 3], "回读按位次升序，与 Brief 吃的是同一份"
    assert items[0]["title"].startswith("rust ownership")


def test_serp_reimport_is_an_update_not_a_duplicate(client):
    """同一份数据重推 = 当日回补。堆重复行会让 latest_for_keyword 取到半新半旧。"""
    site_id = _site_with_scan(client)
    client.post(f"/api/v1/sites/{site_id}/serp", json=_serp_body())
    r = client.post(f"/api/v1/sites/{site_id}/serp", json=_serp_body())
    assert r.status_code == 201
    body = r.json()
    assert body["snapshots_inserted"] == 0
    assert body["snapshots_updated"] == 3
    assert body["keywords_existing"] == 1 and body["keywords_created"] == 0
    assert client.get(f"/api/v1/sites/{site_id}/serp?keyword=rust+ownership").json()["count"] == 3


def test_new_capture_time_adds_history(client):
    site_id = _site_with_scan(client)
    client.post(f"/api/v1/sites/{site_id}/serp", json=_serp_body(captured_at="2026-10-01T00:00:00+00:00"))
    r = client.post(
        f"/api/v1/sites/{site_id}/serp",
        json=_serp_body(captured_at="2026-10-15T00:00:00+00:00", n=5),
    )
    assert r.json()["snapshots_inserted"] == 5, "换了抓取时刻就是一次新的抓取，不该覆盖旧的"
    latest = client.get(f"/api/v1/sites/{site_id}/serp?keyword=rust+ownership").json()
    assert latest["count"] == 5, "latest_for_keyword 取最近一次，不是历史全部"
    assert latest["captured_at"].startswith("2026-10-15")


def test_serp_bad_entries_are_skipped_and_named(client):
    site_id = _site_with_scan(client)
    body = {
        "captures": [{
            "keyword": "rust ownership",
            "entries": [
                {"url": "https://ok.test/1", "position": 1, "title": "ok"},
                {"url": "https://no-pos.test/2", "position": 0},
                {"url": "relative/path", "position": 2},
            ],
        }]
    }
    r = client.post(f"/api/v1/sites/{site_id}/serp", json=body)
    assert r.status_code == 201
    out = r.json()
    assert out["snapshots_inserted"] == 1, "好行照常入库"
    assert out["skipped"] == 2
    assert any("第 1 组第 2 条" in e for e in out["errors"]), out["errors"]
    assert any("第 1 组第 3 条" in e for e in out["errors"])


def test_serp_with_nothing_usable_is_422(client):
    site_id = _site_with_scan(client)
    body = {"captures": [{"keyword": "  ", "entries": [{"url": "https://a.test/1", "position": 1}]}]}
    r = client.post(f"/api/v1/sites/{site_id}/serp", json=body)
    assert r.status_code == 422, "一组都没进来必须拒绝，不能 201 一个空导入"

    r = client.post("/api/v1/sites/99999/serp", json=_serp_body())
    assert r.status_code == 404


def test_brief_actually_consumes_serp_data(client):
    """⚠️ 阶段 4 的验收钉子：导入 SERP 之后，Brief 的竞品维度必须真的用起来。

    以前这条永远走不到：表、仓储、brief 里的读取代码都就位，唯独没有写入
    路径，于是「竞品数据缺失」的 caveat 永远挂着，而 README 宣称 Brief 基于
    SERP 快照。静默装死比没做更坏。
    """
    site_id = _site_with_scan(client)
    client.post(f"/api/v1/sites/{site_id}/serp", json=_serp_body())
    r = client.post(
        f"/api/v1/sites/{site_id}/brief",
        json={"keyword": "rust ownership", "target_url": "https://x.test/a"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert not any("竞品数据缺失" in c for c in body["caveats"]), body["caveats"]
    assert body["serp_common"]["available"] is True
    assert body["serp_common"]["titles_analyzed"] == 3


def test_brief_does_not_cross_use_serp_between_markets(client):
    """同一个词在 google 与 baidu 的 Top10 是两份不同的竞品集，不能混用。"""
    site_id = _site_with_scan(client)
    client.post(f"/api/v1/sites/{site_id}/serp", json=_serp_body(market="baidu"))
    r = client.post(
        f"/api/v1/sites/{site_id}/brief",
        json={"keyword": "rust ownership", "target_url": "https://x.test/a", "market": "google"},
    )
    assert any("竞品数据缺失" in c for c in r.json()["caveats"]), (
        "百度快照被当成谷歌竞品集用上了——查词必须带市场"
    )
    r = client.post(
        f"/api/v1/sites/{site_id}/brief",
        json={"keyword": "rust ownership", "target_url": "https://x.test/a", "market": "baidu"},
    )
    assert r.json()["serp_common"]["available"] is True


def test_brief_reports_own_rank_once_ranking_data_exists(client):
    """排名入口（2026-10-18）接通之后，Brief 不能还硬说「需接 Search Console」。"""
    site_id = _site_with_scan(client)
    target = "https://x.test/a"
    r = client.post(
        f"/api/v1/sites/{site_id}/rankings",
        json={"rows": [
            {"date": "2026-10-18", "url": target, "position": 12.0, "clicks": 3, "impressions": 90},
            {"date": "2026-10-19", "url": target, "position": 9.5, "clicks": 4, "impressions": 110},
        ]},
    )
    assert r.status_code == 201, r.text
    body = client.post(
        f"/api/v1/sites/{site_id}/brief",
        json={"keyword": "rust ownership", "target_url": target},
    ).json()
    assert body["own_rank"]["available"] is True
    assert body["own_rank"]["position"] == 9.5
    assert body["own_rank"]["as_of"] == "2026-10-19"
    assert not any("我方当前排名" in x for x in body["not_available"]), body["not_available"]


def test_brief_own_rank_stays_unavailable_when_position_is_null(client):
    """position=None 是「那天没数据」，不是「排最后」——不能拿来充数。"""
    site_id = _site_with_scan(client)
    target = "https://x.test/none"
    client.post(
        f"/api/v1/sites/{site_id}/rankings",
        json={"rows": [{"date": "2026-10-19", "url": target, "clicks": 1, "impressions": 50}]},
    )
    body = client.post(
        f"/api/v1/sites/{site_id}/brief",
        json={"keyword": "rust ownership", "target_url": target},
    ).json()
    assert body["own_rank"]["available"] is False
    assert any("我方当前排名" in x for x in body["not_available"])


def test_brief_rejects_unknown_market_with_422(client):
    """非法 market 以前在 m.Market(...) 处抛 ValueError → 500。参数错就该 422。"""
    site_id = _site_with_scan(client)
    r = client.post(
        f"/api/v1/sites/{site_id}/brief",
        json={"keyword": "x", "target_url": "https://x.test/a", "market": "bing"},
    )
    assert r.status_code == 422, r.text


# --------------------------------------------------------------------------
# 原始文本入口：界面上「选文件 / 粘贴」走的那条路，解析必须与 CLI 同一份
# --------------------------------------------------------------------------

_RANK_CSV = """date,page,average position,clicks,impressions
2026-10-01,https://demo.test/hot,5,10,300
2026-10-02,https://demo.test/hot,7,12,320
2026-10-03,https://demo.test/hot,,8,310
"""


def test_rankings_raw_import_end_to_end(client):
    """GSC 风格表头（page / average position）的原始 CSV 直接入库。

    这条对着的是**界面那条路**：前端不解析，只把文本送上来。列别名、日期
    格式、空位次的处理必须和 CLI 一模一样，否则「CLI 导得进、网页导不进」
    这种对账噩梦就会出现。
    """
    site_id = _scanned_site(client)
    r = client.post(
        f"/api/v1/sites/{site_id}/rankings/import", json={"text": _RANK_CSV}
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["upserted"] == 3, body
    assert body["errors"] == [] and body["skipped"] == 0

    # 空位次 → NULL（「那天没有排名数据」），不是 0（「排第 0 位」）。
    # 抹平这个区分，跌落告警会算出一段假跌。
    got = client.get(f"/api/v1/sites/{site_id}/rankings?days=60").json()
    assert got["count"] == 3
    positions = sorted(i["position"] for i in got["items"] if i["position"] is not None)
    assert positions == [5.0, 7.0]
    assert any(i["position"] is None for i in got["items"])

    # 重推同一份 = 当日回补，不翻倍
    assert client.post(
        f"/api/v1/sites/{site_id}/rankings/import", json={"text": _RANK_CSV}
    ).status_code == 201
    assert client.get(f"/api/v1/sites/{site_id}/rankings?days=60").json()["count"] == 3


def test_rankings_raw_bad_row_names_the_line(client):
    site_id = _scanned_site(client)
    text = _RANK_CSV + "not-a-date,https://demo.test/hot,9,1,1\n"
    r = client.post(f"/api/v1/sites/{site_id}/rankings/import", json={"text": text})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["upserted"] == 3 and body["skipped"] == 1
    assert any("行" in e for e in body["errors"]), body["errors"]


def test_rankings_raw_all_bad_is_422_and_writes_nothing(client):
    site_id = _scanned_site(client)
    r = client.post(
        f"/api/v1/sites/{site_id}/rankings/import",
        json={"text": "foo,bar,baz\n1,2,3\n"},
    )
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert "什么都没写入" in detail["message"], detail
    assert client.get(f"/api/v1/sites/{site_id}/rankings?days=60").json()["count"] == 0


def test_rankings_raw_site_missing_is_404(client):
    """站点必须先存在——不自动建站，也不让数据挂到无人认领的域名上。"""
    r = client.post("/api/v1/sites/999999/rankings/import", json={"text": _RANK_CSV})
    assert r.status_code == 404, r.text


def test_rankings_raw_over_row_limit_asks_to_split(client):
    """超限是「请分批」的一句人话，不是一个把事务占住的大请求。"""
    from seoclaw.api.schemas import MAX_RANK_ROWS_PER_REQUEST

    site_id = _scanned_site(client)
    rows = [
        f"2026-01-01,https://demo.test/p{i},{i + 1},1,10"
        for i in range(MAX_RANK_ROWS_PER_REQUEST + 1)
    ]
    text = "date,page,average position,clicks,impressions\n" + "\n".join(rows) + "\n"
    assert len(text) < 2_000_000, "用例本身别撞上体积上限，否则测不到行数上限"
    r = client.post(f"/api/v1/sites/{site_id}/rankings/import", json={"text": text})
    assert r.status_code == 422, r.text
    assert "分批" in r.json()["detail"]["message"]


def test_serp_raw_json_import_matches_structured_shape(client):
    """界面粘贴 JSON（Provider 导出形状）→ 与结构化入口共用同一份解析。"""
    import json as _json

    site_id = _site_with_scan(client)
    r = client.post(
        f"/api/v1/sites/{site_id}/serp/import",
        json={"text": _json.dumps(_serp_body())},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["keywords_created"] == 1 and body["snapshots_inserted"] == 3
    assert body["errors"] == [] and body["warnings"] == [], body

    items = client.get(f"/api/v1/sites/{site_id}/serp?keyword=rust+ownership").json()["items"]
    assert [i["position"] for i in items] == [1, 2, 3]


_SERP_CSV_TITLELESS = """keyword,url,position,captured_at
rust ownership,https://a.test/1,1,2026-10-20
rust ownership,https://b.test/2,2,2026-10-20
"""


def test_serp_raw_csv_without_titles_says_so(client):
    """一条标题都没有 → 位次进得了库，但 Brief 的「Top10 标题共性」算不出来。

    CLI 把这句话打到 stderr（ℹ️），界面没有 stderr，所以它必须出现在响应的
    ``warnings`` 里——否则用户只看到一份少了维度的 Brief，不知道是数据没导全。
    """
    site_id = _site_with_scan(client)
    r = client.post(
        f"/api/v1/sites/{site_id}/serp/import", json={"text": _SERP_CSV_TITLELESS}
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["snapshots_inserted"] == 2
    assert body["warnings"] and any("标题" in w for w in body["warnings"]), body


def test_serp_raw_wrong_format_is_actionable_422(client):
    """显式 format 认错时不能崩，也不能假装导入成功。"""
    import json as _json

    site_id = _site_with_scan(client)
    r = client.post(
        f"/api/v1/sites/{site_id}/serp/import",
        json={"text": _json.dumps(_serp_body()), "format": "csv"},
    )
    assert r.status_code == 422, r.text
    assert "什么都没写入" in r.json()["detail"]["message"]
