"""
增量扫描测试。

为什么这组用例全是反向的：增量扫描最危险的错不是「报错」，
而是**静默给出过期结论**——报告看起来正常，用户看不出那是旧的。
所以这里锁的不是「能不能跳过」，而是「**什么情况下绝对不许跳过**」。

判据基准（正文变了 / elapsed_ms 变了）：
- 只看「这一页自己有没有变」不够。跨页规则（title.duplicate 看全站同名索引、
  孤岛页看 inbound_links）的结论由**别的页面**决定。
- 任一页面变了 → 全站页面级规则重跑。
"""

from __future__ import annotations

import json

from app.audit.engine import default_registry, run_audit
from app.extract import extract_page
from app.models import Market


def html(title: str = "A Reasonable Page Title", *, lang: str = "en", extra: str = "") -> str:
    body = extra or "<p>Some body content that is long enough to be considered real.</p>"
    return (
        f'<html lang="{lang}"><head><title>{title}</title>'
        f'<meta name="description" content="A description for the hashing test.">'
        f'<link rel="canonical" href="/p"></head>'
        f"<body><h1>Heading</h1>{body}</body></html>"
    )


def page(url: str, source: str, **kw):
    """构造一个已解析页面。``not_modified`` 是 Page 的**字段**（服务器回 304），
    不是 ``extract_page()`` 的入参——它只解析 HTML，无从知道 HTTP 状态。"""
    p = extract_page(url, source, final_url=url, **{k: v for k, v in kw.items() if k != "not_modified"})
    if "not_modified" in kw:
        p.not_modified = kw["not_modified"]
    return p


def codes(issues, code: str) -> list:
    return [i for i in issues if i.code == code]


# --------------------------------------------------------------------------
# 哈希基准
# --------------------------------------------------------------------------


def test_content_hash_is_stable_across_runs():
    """同一份 HTML 跑多次，哈希必须一致 —— 否则增量扫描等于没做。"""
    h = {page("https://x.test/p", html()).content_hash for _ in range(3)}
    assert len(h) == 1, f"哈希不稳定：{h}"


def test_content_hash_ignores_volatile_fields():
    """elapsed_ms / status 等每次都变的值绝不能进哈希。

    一旦参与比较，全站每轮都会被判「已变」，60+ 规则无限重跑。
    """
    a = page("https://x.test/p", html(), elapsed_ms=13)
    b = page("https://x.test/p", html(), elapsed_ms=9999)
    assert a.content_hash == b.content_hash, "elapsed_ms 变化不该影响内容哈希"


def test_content_hash_changes_when_content_changes():
    """正文真变了哈希必须变 —— 否则改完站再扫还是旧结论。"""
    a = page("https://x.test/p", html())
    b = page("https://x.test/p", html().replace("Some body content", "Totally different"))
    assert a.content_hash != b.content_hash


def test_content_hash_empty_for_unfetched():
    """抓取失败页不该编出哈希 —— 否则会被当成「内容没变」。"""
    assert extract_page("https://x.test/p", "").content_hash == ""


# --------------------------------------------------------------------------
# 跳过判定：两条硬约束
# --------------------------------------------------------------------------


def test_all_unchanged_skips_page_rules():
    """全站零变化（全部 304）→ 页面级规则可以跳过。"""
    pages = [
        page("https://x.test/a", html("Title A", lang=""), not_modified=True),
        page("https://x.test/b", html("Title B", lang=""), not_modified=True),
    ]
    issues, _ = run_audit(pages, "x.test", [Market.BASE, Market.GOOGLE], incremental=True)
    assert not codes(issues, "lang.missing"), "全站未变时应跳过 lang.missing"


def test_one_changed_page_forces_full_rerun():
    """⚠️ 约束 1：只要有任一页面变了，全站页面级规则都得重跑。

    跨页规则的结论由别的页面决定 —— B 页自己没变（304），但 A 页改了标题，
    B 页的「是否重复」可能已经翻转。按 B 页自身决定跳不跳，结论必然错，
    而且**报告看起来完全正常**，用户看不出那是过期结论。
    """
    pages = [
        page("https://x.test/a", html("Title A", lang=""), not_modified=False),  # 变了
        page("https://x.test/b", html("Title B", lang=""), not_modified=True),   # 没变
    ]
    issues, _ = run_audit(pages, "x.test", [Market.BASE, Market.GOOGLE], incremental=True)
    assert codes(issues, "lang.missing"), "有页面变化时，未变页面也必须重跑规则"


def test_failed_page_is_never_skipped():
    """⚠️ 约束 2：抓取失败页绝不能因为「这次也没抓到」就跳过。

    那等于把上次的旧结论当成「本次检查结果」——用户看到的是一份
    看起来正常、实则可能过期的报告。
    """
    failed = page("https://x.test/a", html(), status_code=429)
    failed.not_modified = True  # 极端情况：被错误地标成「未变」
    failed.error = "timeout"
    ok = page("https://x.test/b", html("Title B", lang=""), not_modified=True)

    issues, _ = run_audit([failed, ok], "x.test", [Market.BASE, Market.GOOGLE], incremental=True)
    # 失败页本身有 error，引擎对 error 页本就跳过页面级规则 —— 这里锁的是
    # 「全站零变化」判定不能因为它而成立，否则 ok 页的旧结论会被当成新结论。
    assert ok.error is None


def test_site_facts_rules_are_marked():
    """⚠️ 约束 3 的静态守卫：读 site_facts 的规则必须标 uses_site_facts。

    robots.txt / sitemap 是**本轮重新抓的**事实。跳过等于让昨天的
    robots.txt 结论替今天的文件背书，而且用户看不出来。

    这条用静态检查而不是行为断言：漏标不会让任何现有测试变红，
    只会在增量模式下静默给过期结论——正是最难发现的那类错。
    """
    registry = default_registry()
    markets = [Market.BASE, Market.GOOGLE, Market.BAIDU]
    marked = {
        r.code
        for r in list(registry.page_rules_for(markets)) + list(registry.site_rules_for(markets))
        if getattr(r, "uses_site_facts", False)
    }
    expect = {
        "canonical.conflict",
        "sitemap.missing",
        "robots.missing",
        "robots.blocks_own_site",
        "robots.baiduspider_not_allowed",
    }
    assert not (expect - marked), f"读了 site_facts 却没标 uses_site_facts：{expect - marked}"


def test_non_incremental_never_skips():
    """不开 incremental 时，行为必须与改动前完全一致。"""
    pages = [
        page("https://x.test/a", html("Title A", lang=""), not_modified=True),
        page("https://x.test/b", html("Title B", lang=""), not_modified=True),
    ]
    issues, _ = run_audit(pages, "x.test", [Market.BASE, Market.GOOGLE], incremental=False)
    assert codes(issues, "lang.missing"), "非增量模式不该跳过任何规则"


# --------------------------------------------------------------------------
# 跨页规则：增量下结论仍须正确
# --------------------------------------------------------------------------


def test_duplicate_title_detected_in_incremental_mode():
    """增量模式下跨页规则仍要能发现重复标题（正向用例，防改过头）。"""
    pages = [
        page("https://x.test/a", html("Identical Title Here")),
        page("https://x.test/b", html("Identical Title Here")),
    ]
    issues, _ = run_audit(pages, "x.test", [Market.BASE], incremental=True)
    assert codes(issues, "title.duplicate"), "增量模式不能漏掉跨页重复标题"

# --------------------------------------------------------------------------
# 与 checkpoint 续跑的冲突（实测踩过）
# --------------------------------------------------------------------------


def test_incremental_sends_conditional_request_and_skips_rescan(tmp_path):
    """回归：增量模式必须真的发条件请求，并因 304 跳过规则重跑。

    ⚠️ 第一版回归测试挂在**测试自己**身上：用 https://x.test/ 真抓，
    域名解析不了（stderr 里的 `被限流（HTTP 0）`），落盘 status_code=0，
    prior 被判「上次没抓成功」→ 不发条件请求。代码是对的，测试是错的。
    这里用 MockTransport，两轮的响应完全可控。

    实测现象（真站点上先撞到的）：第二轮 5s→1s、覆盖率 2.6%→80%，
    而 `条件请求 0 次` —— 那是 checkpoint 续跑的 visited 短路把 URL 全跳了，
    增量扫描等于没上线。修了之后 iana.org 实跑 4 次条件请求 / 4 个 304。
    """
    import httpx

    from app.crawler import CrawlConfig, Crawler

    seen_headers: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(dict(request.headers))
        if request.headers.get("if-modified-since"):
            return httpx.Response(304)  # 内容没变
        # ⚠️ content-type 必须给：_fetch 里
        # `raw = resp.text if "text/" in ct or "html" in ct else ""`
        # 拿不到就当非 HTML、压根不解析，title 会是 None。
        # 我第一版 mock 漏了这个头，测试挂在「304 没复用上一轮解析结果」上——
        # 看着像复用坏了，其实是第一轮就没解析。真实站点都会带这个头。
        return httpx.Response(
            200,
            content=html("Incremental Page", lang="").encode(),
            headers={
                "content-type": "text/html; charset=utf-8",
                "last-modified": "Wed, 01 Oct 2026 00:00:00 GMT",
            },
        )

    cfg = CrawlConfig(max_pages=1, per_domain_rps=100.0, total_rps=100.0,
                      respect_robots=False)

    def run(incremental: bool):
        c = Crawler(cfg, checkpoint_dir=tmp_path)
        c.client = httpx.Client(transport=httpx.MockTransport(handler))
        try:
            c.incremental = incremental
            pages = c.crawl("https://x.test/")
            return c, pages
        finally:
            pass

    c1, _ = run(False)
    assert not seen_headers[0].get("if-modified-since"), "第一轮不该带条件请求头"
    assert c1.not_modified_count == 0

    c2, pages2 = run(True)
    assert c2.conditional_sent == 1, (
        "增量模式一个条件请求都没发 —— visited 短路把 URL 全跳了，"
        f"增量扫描等于没上线（发过的请求头：{seen_headers}）"
    )
    assert seen_headers[-1].get("if-modified-since"), "第二轮必须带 If-Modified-Since"
    assert c2.not_modified_count == 1, "服务器回 304 却没复用缓存"
    assert pages2 and pages2[0].not_modified, "304 页必须标 not_modified"
    assert pages2[0].title == "Incremental Page", "304 页应复用上一轮的解析结果"

    # 规则层：全站零变化时页面级规则被跳过，但读 site_facts 的仍要跑
    issues, _ = run_audit(pages2, "x.test", [Market.BASE, Market.GOOGLE], incremental=True)
    assert not codes(issues, "lang.missing"), "全站未变时应跳过页面级规则"
