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
import io
from typing import Any, Callable, Coroutine

import pytest

from seoclaw.db import models as m
from seoclaw.db.session import create_engine_from_url
from seoclaw.models import Issue, Market, Page, Severity


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
    from seoclaw.persist import get_or_create_site, persist_scan

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
    from seoclaw.db.models import JobStatus
    from seoclaw.persist import get_or_create_site, persist_scan

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
    from seoclaw.persist import get_or_create_site

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
    from seoclaw.persist import get_or_create_site, persist_scan

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

    from seoclaw.db import session as sess_mod

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
    from seoclaw.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["scan", "https://demo.test/"])
    assert args.db is None
    args2 = parser.parse_args(["scan", "https://demo.test/", "--db", "x.db"])
    assert args2.db == "x.db"


def test_serp_import_cli_end_to_end(tmp_path, capsys):
    """⚠️ CLI 那条薄接线得有一个人踩过的用例。

    解析层（`test_serpdata.py`）与落库层（`test_db.py`）各自都绿，但中间这段
    「读文件 → 判格式 → 按域名找站点 → 打印归一说明」此前只人肉跑过。
    它偏偏是用户真正敲的那一行：格式判断写反、站点匹配不上、归一说明漏打印，
    上面两层再正确也到不了用户手里。

    这里用真文件 + 真临时库（不用 :memory:：命令内部自己起事件循环和引擎，
    内存库跨循环不可见）。
    """
    from argparse import Namespace

    from seoclaw.cli import cmd_serp_import
    from seoclaw.db import session as sess_mod
    from seoclaw.db.session import create_engine_from_url
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    db = tmp_path / "seo.db"
    (tmp_path / "serp.csv").write_text(
        "keyword,url,position,title,snippet,market,captured_at\n"
        "seo 工具,https://competitor.test/a,1,竞品 A,介绍,baidu,2026-10-20T08:00:00+00:00\n"
        "seo 工具,https://b.test/2,2,竞品 B,,baidu,2026-10-20T08:00:00+00:00\n"
        "seo 工具,https://bad.test/3,abc,坏位次,,baidu,2026-10-20T08:00:00+00:00\n"
        "seo 工具,https://n.test/4,4,,,,\n",
        encoding="utf-8",
    )

    url = "sqlite+aiosqlite:///" + db.as_posix()

    async def _seed() -> None:
        eng = create_engine_from_url(url)
        async with eng.begin() as conn:
            await conn.run_sync(m.Base.metadata.create_all)
        factory = async_sessionmaker(
            bind=eng, class_=AsyncSession, expire_on_commit=False
        )
        async with factory() as sess:
            # 库里只有 demo.test，命令却要按 www.demo.test 找——域名归一
            # 靠 get_by_domain，这条也一并钉住。
            sess.add(m.Site(domain="demo.test", markets=["base", "baidu"]))
            await sess.commit()
        await eng.dispose()

    asyncio.run(_seed())

    args = Namespace(
        file=str(tmp_path / "serp.csv"), db=str(db), site="www.demo.test",
        format=None, captured_at=None,
    )
    assert cmd_serp_import(args) == 0
    first = capsys.readouterr().err
    # 坏行报行号；两次抓取三条结果；两个市场各建一条词档
    assert "第 4 行跳过" in first, first
    assert "新增 3" in first and "关键词新建 2" in first, first
    # 没给抓取时间的那组必须被点名——否则用户不知道跨天重跑会变成「新历史」
    assert "没有抓取时间" in first and "不是更新" in first, first

    assert cmd_serp_import(args) == 0
    second = capsys.readouterr().err
    assert "更新 3" in second and "新增 0" in second, second
    assert "关键词新建 0" in second, second

    # 站点不在库里：退出码非 0，且告诉用户下一步做什么
    missing = Namespace(**{**vars(args), "site": "nosuch.test"})
    assert cmd_serp_import(missing) == 1
    third = capsys.readouterr().err
    assert "不在库里" in third and "seoclaw scan" in third, third

    # 收尾：命令内部按 URL 建了**全局缓存**的引擎，它的连接绑的是刚才那个
    # 已经关闭的 loop。显式 dispose 一次，别把这条连接留给下个用例。
    # （实测本文件那条 aiosqlite 「There is no current event loop」
    # DeprecationWarning 是既有的，与本条无关——`-k "not serp_import"` 照样出。）
    async def _cleanup() -> None:
        await sess_mod.dispose_engine()

    asyncio.run(_cleanup())

# ---------------------------------------------------------------------------
# 命令级冒烟：rank-import / rules / argparse 派发
# ---------------------------------------------------------------------------
#
# 为什么单列这一组：解析层（test_rankdata.py / test_serpdata.py）和落库层
# （test_db.py）各自都绿，但「读文件 → 认列名别名 → 推断域名 → 按域名找
# 站点 → 打印跳过行数」这段中间层此前只人肉跑过。它是用户真正敲的那一行，
# 也正是最容易写错的一段（阶段 4 的两处输出缺陷就是这么发现的）。


def _seed_site(url: str, domain: str = "demo.test") -> None:
    """建表 + 塞一个站点。单独一个 loop，跑完就 dispose。"""
    from seoclaw.db.session import create_engine_from_url

    async def _go() -> None:
        eng = create_engine_from_url(url)
        async with eng.begin() as conn:
            await conn.run_sync(m.Base.metadata.create_all)
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        factory = async_sessionmaker(bind=eng, class_=AsyncSession, expire_on_commit=False)
        async with factory() as sess:
            sess.add(m.Site(domain=domain))
            await sess.commit()
        await eng.dispose()

    asyncio.run(_go())


def _count_rank_rows(db_path) -> tuple:
    """用 stdlib sqlite3 读回行数——绕开 aiosqlite 的「连接绑 loop」。

    命令内部自己起事件循环并缓存全局引擎，测试这边再拿同一个 URL 去查，
    查到的可能是绑在已关闭 loop 上的连接。读文件是外部视角，反而干净。
    """
    import sqlite3

    con = sqlite3.connect(str(db_path))
    try:
        return con.execute(
            "select count(*), coalesce(sum(case when position is null then 1 else 0 end), 0) "
            "from rank_history"
        ).fetchone()
    finally:
        con.close()


def test_rank_import_cli_end_to_end(tmp_path, capsys):
    """日级排名导入：认别名、坏行报号、幂等、留空位次不被当成 0。"""
    from argparse import Namespace

    from seoclaw.cli import cmd_rank_import

    csv_path = tmp_path / "rank.csv"
    # 表头故意用 GSC 风格的别名（page / average position），列序也与文档相反：
    # 别名映射与列序无关这条得钉住。第 4 行日期格式坏 → 跳过并报行号。
    csv_path.write_text(
        "date,page,average position,impressions,clicks\n"
        "2026-10-19,https://www.demo.test/,3.5,100,10\n"
        "2026-10-20,https://www.demo.test/guide,,50,2\n"
        "20/10/2026,https://www.demo.test/x,4,10,1\n",
        encoding="utf-8",
    )
    db = tmp_path / "seo.db"
    _seed_site("sqlite+aiosqlite:///" + db.as_posix())

    args = Namespace(csv=str(csv_path), db=str(db), site=None)
    assert cmd_rank_import(args) == 0
    out = capsys.readouterr().err
    assert "第 4 行跳过" in out, out
    assert "已导入 2 行日级数据" in out and "跳过 1 行" in out, out
    # 没给 --site 时按 URL 里出现最多的 host（剥 www.）推断
    assert "demo.test" in out, out

    total, nulls = _count_rank_rows(db)
    assert (total, nulls) == (2, 1), f"落库 {total} 行 / 空位次 {nulls} 行"

    # 重跑同一份文件：唯一键是 (site, url, date)，不该长出第三行
    assert cmd_rank_import(args) == 0
    capsys.readouterr()
    assert _count_rank_rows(db) == (2, 1), "重复导入长出了第二份"

    # 站点不在库里：非 0 退出 + 下一步做什么
    missing = Namespace(**{**vars(args), "site": "nosuch.test"})
    assert cmd_rank_import(missing) == 1
    err = capsys.readouterr().err
    assert "不在库里" in err and "seoclaw scan" in err, err

    from seoclaw.db import session as sess_mod

    async def _cleanup() -> None:
        await sess_mod.dispose_engine()

    asyncio.run(_cleanup())


def test_rank_import_cannot_infer_domain_says_so(tmp_path, capsys):
    """推不出域名时明确让用户给 --site，而不是默默灌进一个空站点。

    触发条件用 `https://`（有协议、没主机）：`row_from_fields` 只要求
    完整地址前缀，所以这行能进 rows，但 `urlparse().netloc` 是空的——
    这正是畸形导出会让推断失手的形状。
    """
    from argparse import Namespace

    from seoclaw.cli import cmd_rank_import

    csv_path = tmp_path / "nohost.csv"
    csv_path.write_text(
        "date,url,position\n2026-10-19,https://,3\n", encoding="utf-8"
    )
    db = tmp_path / "seo.db"
    _seed_site("sqlite+aiosqlite:///" + db.as_posix())

    assert cmd_rank_import(Namespace(csv=str(csv_path), db=str(db), site=None)) == 1
    err = capsys.readouterr().err
    assert "推断不出站点域名" in err and "--site" in err, err
    assert _count_rank_rows(db) == (0, 0), "推不出域名却写了库"

    from seoclaw.db import session as sess_mod

    async def _cleanup() -> None:
        await sess_mod.dispose_engine()

    asyncio.run(_cleanup())


def test_rules_cli_shows_every_registered_rule(capsys):
    """`seoclaw rules` 必须列出**已加载的全部规则**，且 geo 只说明不列。

    踩过的坑是清单写死：某个包的规则已注册却在列表里看不见，用户以为
    没生效（cnh_eco）。这里按注册表实况逐条比对，写死/漏市场都会红。
    实验包 geo 反过来：它不进默认注册表，所以既不能出现在清单里，
    又必须在末尾说明「默认不加载、怎么启用」——否则用户不知道它存在。
    """
    from argparse import Namespace

    from seoclaw.audit.engine import default_registry
    from seoclaw.cli import cmd_rules
    from seoclaw.models import Market

    reg = default_registry()
    rules = reg.page_rules_for(list(Market)) + reg.site_rules_for(list(Market))
    assert rules, "注册表里一条规则都没有，这条测试就白跑了"

    assert cmd_rules(Namespace()) == 0
    out = capsys.readouterr().out
    missing = [r.code for r in rules if r.code not in out]
    assert not missing, f"已注册但列表里看不见：{missing}"

    assert "默认不加载" in out and "geo" in out, out
    for geo_code in (
        "geo.no_question_headings",
        "geo.no_outbound_references",
        "geo.flat_structure",
        "geo.faq_structure_mismatch",
    ):
        assert geo_code not in out, f"实验包 geo 的规则混进了默认清单：{geo_code}"


def test_cli_main_dispatches_subcommands(tmp_path, capsys):
    """argparse 那层的默认值要和命令函数对得上。

    `main([...])` 走的是用户敲的那串参数：--format/--captured-at 不给时
    落成什么，完全由 parser 决定；命令函数的行为已经在上面几条用例里钉过，
    这里补的是「参数名/默认值写错，命令收到 None 之外的东西」这一类错。
    """
    from seoclaw.cli import main

    assert main(["rules"]) == 0
    assert "页面级" in capsys.readouterr().out

    # 缺 --db（必填）→ argparse 自己以 SystemExit(2) 结束，不该走到命令体里
    with pytest.raises(SystemExit) as boom:
        main(["rank-import", str(tmp_path / "nope.csv")])
    assert boom.value.code == 2


# ---------------------------------------------------------------------------
# 入口层的「读文件」错误处理：拼错路径不该长得像程序崩了
# ---------------------------------------------------------------------------


def test_cli_import_missing_file_is_not_a_traceback(tmp_path, capsys):
    """文件不存在 → 一句人话 + 退出码 1，而不是 traceback。

    这是入口层最常见的用户错误（路径打错、文件挪了地方）。`cmd_*` 里
    裸奔的 `Path.read_text()` 会抛 FileNotFoundError，被 argparse 之外的
    地方接住就是整屏栈——用户读不出「哪个路径错了」。
    """
    from argparse import Namespace

    from seoclaw.cli import cmd_rank_import, cmd_serp_import

    ghost = str(tmp_path / "nope.csv")
    db = str(tmp_path / "seo.db")

    assert cmd_rank_import(Namespace(csv=ghost, db=db, site=None)) == 1
    err = capsys.readouterr().err
    assert "文件不存在" in err and "nope.csv" in err, err
    assert "Traceback" not in err, err

    assert cmd_serp_import(
        Namespace(file=ghost, db=db, site="demo.test", format=None, captured_at=None)
    ) == 1
    err = capsys.readouterr().err
    assert "文件不存在" in err, err
    assert "Traceback" not in err, err


def test_cli_import_directory_says_so(tmp_path, capsys):
    """把目录当文件给：说清「那是个目录」，别抛栈。"""
    from argparse import Namespace

    from seoclaw.cli import cmd_rank_import

    assert cmd_rank_import(
        Namespace(csv=str(tmp_path), db=str(tmp_path / "seo.db"), site=None)
    ) == 1
    err = capsys.readouterr().err
    assert "那是个目录" in err and "Traceback" not in err, err


def test_cli_import_binary_file_says_so(tmp_path, capsys):
    """UTF-8 解不了的二进制：提示「请导出 UTF-8」，而不是 UnicodeDecodeError 栈。"""
    from argparse import Namespace

    from seoclaw.cli import cmd_rank_import

    bin_path = tmp_path / "utf16.csv"
    bin_path.write_bytes(b"\xff\xfe\x00d\x00a\x00t\x00e")
    assert cmd_rank_import(
        Namespace(csv=str(bin_path), db=str(tmp_path / "seo.db"), site=None)
    ) == 1
    err = capsys.readouterr().err
    assert "不像文本文件" in err and "UTF-8" in err, err
    assert "Traceback" not in err, err


def test_cli_import_reads_stdin(tmp_path, capsys):
    """`-` 是标准输入，不是一个名叫 `-` 的文件。"""
    import sys
    from argparse import Namespace

    from seoclaw.cli import cmd_rank_import

    db = tmp_path / "seo.db"
    _seed_site("sqlite+aiosqlite:///" + db.as_posix())
    monkey_stdin = io.StringIO(
        "date,url,position\n"
        "2026-10-19,https://www.demo.test/,3.5\n"
        "2026-10-20,https://www.demo.test/guide,2\n"
    )
    old = sys.stdin
    sys.stdin = monkey_stdin
    try:
        assert cmd_rank_import(Namespace(csv="-", db=str(db), site="demo.test")) == 0
    finally:
        sys.stdin = old
    err = capsys.readouterr().err
    assert "已导入 2 行日级数据" in err, err
    assert _count_rank_rows(db) == (2, 0), _count_rank_rows(db)

    from seoclaw.db import session as sess_mod

    async def _cleanup() -> None:
        await sess_mod.dispose_engine()

    asyncio.run(_cleanup())
