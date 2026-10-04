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


def test_report_without_scan_has_null_score(client):
    """没扫过的站点 health_score 必须是 null —— 0 分意味着「扫了且很差」，
    这两件事不能共用同一个值。"""
    site = client.post("/api/v1/sites", json={"domain": client.domain}).json()
    rep = client.get(f"/api/v1/sites/{site['id']}/report").json()
    assert rep["health_score"] is None
    assert rep["pages_crawled"] == 0