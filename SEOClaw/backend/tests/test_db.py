"""持久化层测试。

用 SQLite + aiosqlite 内存库跑，不依赖真实 PG —— 理由：CI 里每次起一个 PG
容器太慢，而这些用例验证的是**查询形状与业务口径**（分页、聚合、幂等），
不是 PG 特有的行为。PG 特有的部分（JSONB、并发冲突）留给集成测试。

不依赖 pytest-asyncio：每个用例用同一个 event loop 驱动协程，理由是少一个
插件依赖就能少一类"CI 上装不上"的失败。

**为什么必须共用一个 event loop**：早期版本每次调用都 `asyncio.run()`，
也就是每个协程一个新 loop。asyncpg/aiosqlite 的连接是绑定在创建它的 loop
上的，换 loop 之后同一条连接的可见状态会失真 —— 表现为"刚插入的行，下一个
协程 SELECT 不到"，进而被误判成唯一约束冲突。踩过这个坑，这里固定为
「一个用例 = 一个 loop」。
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Coroutine

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import models as m
from app.db.repository import (
    UnitOfWork,
    compute_fingerprint,
    normalize_root_cause,
)
from app.db.session import (
    create_engine_from_url,
    session_scope,
    to_async_url,
    to_sync_url,
)


@pytest.fixture
def loop():
    """一个用例一个 event loop，用例结束即关闭。"""
    new_loop = asyncio.new_event_loop()
    try:
        yield new_loop
    finally:
        new_loop.close()


@pytest.fixture
def acall(loop) -> Callable[[Coroutine[Any, Any, Any]], Any]:
    """在用例专属的 event loop 上驱动协程。"""

    def _acall(coro: Coroutine[Any, Any, Any]) -> Any:
        return loop.run_until_complete(coro)

    return _acall


@pytest.fixture
def engine(acall, loop):
    """每个用例一个全新的内存库。

    不用裸 ``sqlite:///:memory:`` 的默认池 —— 那会让每条连接都是一个
    独立的空库，表刚建好就没了。session.py 里的 StaticPool 才是关键。
    """
    url = "sqlite+aiosqlite:///:memory:"
    eng = create_engine_from_url(url)

    async def _setup() -> None:
        async with eng.begin() as conn:
            await conn.run_sync(m.Base.metadata.create_all)

    acall(_setup())
    try:
        yield eng
    finally:
        acall(eng.dispose())


@pytest.fixture
def session(acall, engine) -> AsyncSession:
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
    sess = factory()
    try:
        yield sess
    finally:
        acall(sess.close())


@pytest.fixture
def uow(session) -> UnitOfWork:
    return UnitOfWork(session)


# --------------------------------------------------------------------------
# 工具函数
# --------------------------------------------------------------------------


async def seed_site(session: AsyncSession, domain: str = "example.com") -> m.Site:
    return await UnitOfWork(session).sites.create(domain, markets=["base", "google"])


def h(text: str) -> str:
    """造一个稳定的假 content_hash。"""
    import hashlib

    return hashlib.sha256(text.encode()).hexdigest()


# --------------------------------------------------------------------------
# URL / 工具
# --------------------------------------------------------------------------


def test_url_conversion_roundtrip() -> None:
    """迁移用同步 URL，应用用 async URL，必须指向同一个库。"""
    async_url = "postgresql+asyncpg://u:p@h:5432/db"
    assert to_sync_url(async_url) == "postgresql+psycopg2://u:p@h:5432/db"
    assert to_sync_url("sqlite+aiosqlite:///./x.db") == "sqlite:///./x.db"
    assert to_sync_url("postgresql://h/db") == "postgresql://h/db"  # 非 async 原样返回
    assert to_async_url("sqlite:///./x.db") == "sqlite+aiosqlite:///./x.db"


def test_normalize_root_cause_strips_volatile_parts() -> None:
    """URL 里的 id / 查询串 / 全角差异都不应制造出不同的根因。"""
    assert normalize_root_cause("Product 1001 缺少 ALT") == normalize_root_cause(
        "product 1002 缺少 alt"
    )
    # 全角/半角与大小写归一
    assert normalize_root_cause("ＡＬＴ") == "alt"
    assert normalize_root_cause(None) == ""


# --------------------------------------------------------------------------
# 站点 CRUD
# --------------------------------------------------------------------------


def test_site_crud(acall, uow: UnitOfWork) -> None:
    """站点创建 / 读取 / 更新 / 删除。"""
    site = acall(uow.sites.create("https://WWW.Example.com/shop/"))
    # 域名必须被规范化，否则用户换个写法就"接入了一个新站"
    assert site.domain == "example.com"
    assert site.id is not None

    assert acall(uow.sites.get(site.id)).domain == "example.com"
    assert acall(uow.sites.get_by_domain("example.com")).id == site.id

    updated = acall(uow.sites.update(site.id, is_active=False))
    assert updated is not None and updated.is_active is False

    assert acall(uow.sites.delete(site.id)) is True
    assert acall(uow.sites.get(site.id)) is None
    assert acall(uow.sites.delete(site.id)) is False


def test_site_cascade_deletes_children(acall, uow: UnitOfWork, session: AsyncSession) -> None:
    """删站点要连带清掉 pages / issues —— 租户边界由数据库保证。"""
    site = acall(seed_site(session))
    acall(uow.pages.create(site_id=site.id, url="https://example.com/", content_hash=h("a")))
    acall(uow.issues.create(site_id=site.id, code="title.missing", severity="high", url="/"))
    acall(session.commit())  # 先落盘，确保下面统计的是真实行

    acall(uow.sites.delete(site.id))
    acall(session.commit())

    from sqlalchemy import func, select

    assert acall(session.execute(select(func.count()).select_from(m.Page))).scalar_one() == 0
    assert acall(session.execute(select(func.count()).select_from(m.Issue))).scalar_one() == 0


# --------------------------------------------------------------------------
# 分页
# --------------------------------------------------------------------------


def test_pagination(acall, uow: UnitOfWork, session: AsyncSession) -> None:
    """分页要同时给出 items / total / has_next，且 total 与筛选口径一致。"""
    site = acall(seed_site(session))
    for i in range(5):
        acall(
            uow.pages.create(
                site_id=site.id,
                url=f"https://example.com/p{i}",
                content_hash=h(f"p{i}"),
                depth=i,
            )
        )

    first = acall(uow.pages.list(site.id, limit=2, offset=0))
    assert first.total == 5
    assert len(first.items) == 2
    assert first.has_next is True and first.has_prev is False

    last = acall(uow.pages.list(site.id, limit=2, offset=4))
    assert len(last.items) == 1
    assert last.has_next is False and last.has_prev is True

    # 筛选后的 total 必须跟着变（count 与 list 同源）
    filtered = acall(uow.pages.list(site.id, min_depth=3, limit=10))
    assert filtered.total == 2
    assert all(p.depth >= 3 for p in filtered.items)


# --------------------------------------------------------------------------
# content_hash 增量判定
# --------------------------------------------------------------------------


def test_upsert_detects_content_change(acall, uow: UnitOfWork, session: AsyncSession) -> None:
    """增量扫描的核心：只有 content_hash 变了才需要重跑规则。"""
    site = acall(seed_site(session))
    url = "https://example.com/product/1"

    first = acall(uow.pages.upsert(site.id, url, content_hash=h("v1"), text="v1"))
    assert first.created is True and first.changed is True

    # 内容没变 → 不该触发 60+ 规则重跑
    again = acall(uow.pages.upsert(site.id, url, content_hash=h("v1"), text="v1"))
    assert again.created is False and again.changed is False
    assert again.page.id == first.page.id  # 没有产生新行

    # 只有抓取时间这类噪声变化，不算内容变化
    noise = acall(uow.pages.upsert(site.id, url, content_hash=h("v1"), text="v1", depth=3))
    assert noise.changed is False

    changed = acall(uow.pages.upsert(site.id, url, content_hash=h("v2"), text="v2"))
    assert changed.changed is True and changed.page.content_hash == h("v2")


def test_incremental_diff(acall, uow: UnitOfWork, session: AsyncSession) -> None:
    """diff_against / unchanged_urls 把"要处理"和"可跳过"分开。"""
    site = acall(seed_site(session))
    for name in ("a", "b"):
        acall(
            uow.pages.create(
                site_id=site.id, url=f"https://example.com/{name}", content_hash=h(name)
            )
        )

    seen = {
        "https://example.com/a": h("a"),   # 没变
        "https://example.com/b": h("b2"),  # 变了
        "https://example.com/c": h("c"),   # 新页面
    }
    to_process = acall(uow.pages.diff_against(site.id, seen))
    assert "https://example.com/a" not in to_process
    assert "https://example.com/b" in to_process
    assert "https://example.com/c" in to_process  # 库中缺席 = 需要处理

    assert acall(uow.pages.unchanged_urls(site.id, seen)) == ["https://example.com/a"]
    assert acall(uow.pages.count(site.id)) == 2


def test_pages_site_url_unique(acall, uow: UnitOfWork, session: AsyncSession) -> None:
    """(site_id, url) 唯一是并发抓取的去重保证，必须在 DB 层生效。"""
    from sqlalchemy.exc import IntegrityError

    site = acall(seed_site(session))
    acall(uow.pages.create(site_id=site.id, url="https://example.com/x", content_hash=h("1")))
    with pytest.raises(IntegrityError):
        acall(
            uow.pages.create(
                site_id=site.id, url="https://example.com/x", content_hash=h("2")
            )
        )
    acall(session.rollback())


# --------------------------------------------------------------------------
# issues 与 fingerprint 聚合
# --------------------------------------------------------------------------


def test_fingerprint_aggregation(acall, uow: UnitOfWork, session: AsyncSession) -> None:
    """3000 个商品页缺 alt，应聚成 1 条批量行动，而不是 3000 条噪音。"""
    site = acall(seed_site(session))
    root = "img.alt.missing:商品主图缺少 alt 文本"
    for i in range(3):
        acall(
            uow.issues.create(
                site_id=site.id,
                code="img.alt.missing",
                severity="high",
                url=f"https://example.com/product/{1000 + i}",
                title="图片缺少 alt",
                evidence={"root_cause": root, "img": f"/img/{i}.jpg"},
                fingerprint=compute_fingerprint("img.alt.missing", root),
            )
        )
    # 另一类问题，不应被并进来
    acall(
        uow.issues.create(
            site_id=site.id,
            code="title.dup",
            severity="medium",
            url="https://example.com/",
            title="标题重复",
            evidence={"root_cause": "title.dup:首页标题重复"},
            fingerprint=compute_fingerprint("title.dup", "title.dup:首页标题重复"),
        )
    )

    groups = acall(uow.issues.group_by_fingerprint(site.id))
    by_code = {g.code: g for g in groups}
    assert set(by_code) == {"img.alt.missing", "title.dup"}
    assert by_code["img.alt.missing"].affected_count == 3
    assert by_code["title.dup"].affected_count == 1
    assert len(by_code["img.alt.missing"].sample_urls) == 3
    # 按影响面降序排，最该批量修的排最前
    assert groups[0].code == "img.alt.missing"


def test_fingerprint_ignores_ids_in_root_cause(uow: UnitOfWork, session: AsyncSession) -> None:
    """根因文本里带商品 id 时，聚合键应保持一致。"""
    a = compute_fingerprint("img.alt.missing", "product 1001 缺少 ALT")
    b = compute_fingerprint("img.alt.missing", "Product 1002 缺少 alt")
    assert a == b


def test_issue_filtering_and_status(acall, uow: UnitOfWork, session: AsyncSession) -> None:
    """按 severity / status 过滤 + 批量改状态。"""
    site = acall(seed_site(session))
    crit = acall(
        uow.issues.create(
            site_id=site.id, code="a", severity="critical", url="/a",
            fingerprint=compute_fingerprint("a", "x"),
        )
    )
    acall(
        uow.issues.create(
            site_id=site.id, code="b", severity="low", url="/b",
            fingerprint=compute_fingerprint("b", "y"),
        )
    )

    crit_only = acall(uow.issues.list(site.id, severity="critical"))
    assert crit_only.total == 1 and crit_only.items[0].id == crit.id

    assert acall(uow.issues.count_by_severity(site.id)) == {"critical": 1, "low": 1}

    n = acall(uow.issues.resolve_by_fingerprint(site.id, crit.fingerprint, "acknowledged"))
    assert n == 1
    acall(session.commit())
    assert acall(uow.issues.list(site.id, status="open")).total == 1


# --------------------------------------------------------------------------
# 抓取任务
# --------------------------------------------------------------------------


def test_crawl_job_lifecycle(acall, uow: UnitOfWork, session: AsyncSession) -> None:
    """任务状态流转，且能取到"最近一次"扫描。"""
    site = acall(seed_site(session))
    job = acall(uow.jobs.create(site.id, job_key="site-2026-09-29"))
    assert job.status == m.JobStatus.PENDING

    acall(uow.jobs.start(job.id))
    assert acall(uow.jobs.get(job.id)).status == m.JobStatus.RUNNING

    acall(uow.jobs.finish(job.id, url_count=100, pages_crawled=80))
    done = acall(uow.jobs.get(job.id))
    assert done.status == m.JobStatus.SUCCEEDED and done.url_count == 100
    assert done.duration_seconds is not None and done.duration_seconds >= 0

    latest = acall(uow.jobs.latest_for_site(site.id))
    assert latest.id == job.id


# --------------------------------------------------------------------------
# 关键词 / SERP / 排名
# --------------------------------------------------------------------------


def test_keyword_and_serp(acall, uow: UnitOfWork, session: AsyncSession) -> None:
    """词库幂等导入 + SERP 快照取最近一次。"""
    site = acall(seed_site(session))
    acall(uow.keywords.bulk_upsert(site.id, [{"term": "seo 工具", "volume": 100}]))
    kw = acall(uow.keywords.get_by_term(site.id, "seo 工具", market="google"))
    assert kw is not None and kw.volume == 100

    # 同词同市场重复导入 → 更新而非新增
    acall(uow.keywords.bulk_upsert(site.id, [{"term": "seo 工具", "volume": 120}]))
    assert acall(uow.keywords.list(site.id)).total == 1
    assert acall(uow.keywords.get(kw.id)).volume == 120

    acall(
        uow.serp.bulk_create(
            [
                {
                    "keyword_id": kw.id, "site_id": site.id, "position": 1,
                    "url": "https://a.com/", "title": "A",
                    "captured_at": _dt(2026, 9, 1),
                },
                {
                    "keyword_id": kw.id, "site_id": site.id, "position": 2,
                    "url": "https://b.com/", "title": "B",
                    "captured_at": _dt(2026, 9, 1),
                },
            ]
        )
    )
    latest = acall(uow.serp.latest_for_keyword(kw.id))
    assert [s.position for s in latest] == [1, 2]


def test_rank_history_upsert_is_idempotent(acall, uow: UnitOfWork, session: AsyncSession) -> None:
    """GSC/GA4 每天回补近 3 天数据，重复写入必须幂等，否则趋势图失真。"""
    site = acall(seed_site(session))
    day = date(2026, 9, 28)
    acall(uow.ranks.upsert_day(site.id, "https://example.com/", day, clicks=10, impressions=100))
    row = acall(uow.ranks.upsert_day(site.id, "https://example.com/", day, clicks=12, impressions=110))
    assert row.clicks == 12

    series = acall(uow.ranks.series(site.id, "https://example.com/"))
    assert len(series) == 1 and series[0].clicks == 12

    # 补齐 day-2 / day-1 / day 三个日期。day 已存在，upsert 覆盖而非新增 ——
    # 恰好又一次验证了幂等：无论导入多少次，(site, url, date) 永远只有一行。
    for d in range(3):
        acall(
            uow.ranks.upsert_day(
                site.id, "https://example.com/", day - timedelta(days=d), clicks=d
            )
        )
    series = acall(uow.ranks.series(site.id, "https://example.com/"))
    assert len(series) == 3  # 不是 4 行：day 被覆盖而非追加
    # 趋势图按日期升序读，顺序错了画出来就是锯齿
    assert [r.date for r in series] == [day - timedelta(days=2), day - timedelta(days=1), day]
    assert [r.clicks for r in series] == [2, 1, 0]


# --------------------------------------------------------------------------
# 建议 / Brief
# --------------------------------------------------------------------------


def test_suggestion_apply_and_revert(acall, uow: UnitOfWork, session: AsyncSession) -> None:
    """建议的采纳/撤回时间戳 —— 北极星指标"被采纳的建议数"的来源。"""
    site = acall(seed_site(session))
    sug = acall(
        uow.suggestions.create(
            site.id, "https://example.com/", "title",
            before_text="旧标题", after_text="新标题",
        )
    )
    assert sug.status == m.SuggestionStatus.DRAFT
    # before_text 必须落库：撤回时靠它还原现场
    assert sug.before_text == "旧标题"

    acall(uow.suggestions.apply(sug.id))
    applied = acall(uow.suggestions.get(sug.id))
    assert applied.status == m.SuggestionStatus.APPLIED and applied.applied_at is not None

    acall(uow.suggestions.revert(sug.id))
    reverted = acall(uow.suggestions.get(sug.id))
    assert reverted.status == m.SuggestionStatus.REVERTED and reverted.reverted_at is not None


def test_brief_upsert(acall, uow: UnitOfWork, session: AsyncSession) -> None:
    """同一 URL + 目标词重跑生成 Brief，应更新而不是产生第二份草稿。"""
    site = acall(seed_site(session))
    first = acall(uow.briefs.upsert(site.id, "https://example.com/blog/x", brief={"v": 1}))
    second = acall(
        uow.briefs.upsert(
            site.id, "https://example.com/blog/x", brief={"v": 2},
            status=m.BriefStatus.APPROVED,
        )
    )
    assert first.id == second.id
    assert acall(uow.briefs.list(site.id)).total == 1
    assert acall(uow.briefs.get(first.id)).brief == {"v": 2}


# --------------------------------------------------------------------------
# 表结构约束（防止后续迁移把需求硬约束改掉）
# --------------------------------------------------------------------------


def test_required_tables_and_unique_constraints() -> None:
    """需求第 6 节的 9 张表 + 三条硬约束，必须长期存在。"""
    tables = set(m.Base.metadata.tables)
    assert {
        "sites", "crawl_jobs", "pages", "issues", "keywords",
        "serp_snapshots", "content_briefs", "suggestions", "rank_history",
    } <= tables

    def unique_cols(table: str) -> set[tuple[str, ...]]:
        md = m.Base.metadata.tables[table]
        return {
            tuple(sorted(c.name for c in uc.columns))
            for uc in md.constraints
            if uc.__class__.__name__ == "UniqueConstraint"
        }

    # 注意：上面统一排序过，比较时也必须用排序后的形式
    assert ("site_id", "url") in unique_cols("pages")
    assert ("date", "site_id", "url") in unique_cols("rank_history")

    issues_idx = {tuple(i.columns.keys()) for i in m.Base.metadata.tables["issues"].indexes}
    assert ("site_id", "severity", "code") in issues_idx

    # 需求外补充的两个字段
    assert "fingerprint" in m.Base.metadata.tables["issues"].columns
    assert "content_hash" in m.Base.metadata.tables["pages"].columns


def _dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# 事务边界
# --------------------------------------------------------------------------


def test_failed_scan_rolls_back_everything(acall, uow: UnitOfWork, session: AsyncSession) -> None:
    """半途失败的扫描必须一行都不留。

    抓取 Agent 跑几十分钟。若中途超时却留下半套数据，报告会基于"只抓到
    一半的站点"给出看起来完全正常的结论 —— 那比直接失败危险得多，因为它
    不会报错，只会给出一个错误的健康分。
    """
    from sqlalchemy import func, select

    site = acall(seed_site(session, "rollback.test"))
    acall(session.commit())  # 先固化 site，单独于后面那个事务
    # 立刻把 id 取成普通 int：rollback 会 expire 掉会话里所有对象，
    # 事后再读 site.id 会触发一次隐式 IO（同步上下文里就是 MissingGreenlet）。
    site_id = site.id

    async def _run_broken_scan() -> None:
        """session_scope 是 asynccontextmanager，必须在协程内进入。"""
        async with session_scope(session):
            await uow.pages.create(
                site_id=site_id, url="https://rollback.test/x", content_hash=h("x")
            )
            await uow.issues.create(
                site_id=site_id,
                code="MISSING_ALT",
                severity="high",
                url="https://rollback.test/x",
            )
            raise RuntimeError("crawler died mid-scan")

    with pytest.raises(RuntimeError):
        acall(_run_broken_scan())

    # 用新会话复核：不能靠 identity map 里的旧对象自我安慰 ——
    # 那些对象在回滚后是过期状态，读它们可能给出看似正确的假象。
    acall(session.rollback())
    pages_left = acall(
        session.execute(
            select(func.count())
            .select_from(m.Page)
            .where(m.Page.site_id == site_id)
        )
    ).scalar_one()
    issues_left = acall(
        session.execute(
            select(func.count())
            .select_from(m.Issue)
            .where(m.Issue.site_id == site_id)
        )
    ).scalar_one()

    assert pages_left == 0
    assert issues_left == 0
