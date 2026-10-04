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
from seoclaw.models import Market, Page, SiteReport


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
    assert client.get("/api/v1/health").json() == {"ok": True}


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


def test_report_without_scan_has_null_score(client):
    """没扫过的站点 health_score 必须是 null —— 0 分意味着「扫了且很差」，
    这两件事不能共用同一个值。"""
    site = client.post("/api/v1/sites", json={"domain": client.domain}).json()
    rep = client.get(f"/api/v1/sites/{site['id']}/report").json()
    assert rep["health_score"] is None
    assert rep["pages_crawled"] == 0