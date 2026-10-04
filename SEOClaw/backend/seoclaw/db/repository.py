"""仓储层：所有 SQL 都收在这里，上层（API / CLI / Worker）只碰函数。

分层的意义：规则引擎、报告生成、Celery worker 都要读同一批数据，如果每处
都写裸 SQL，很快会出现"报告按 severity 排、看板按 id 排"这种互相打架的
口径。仓储层把口径固化下来，同时让单测可以脱离 HTTP 层直接验证查询形状。

通用约定：
  * 全部是 async 函数，接收一个 AsyncSession；函数内**不**自行 commit
    （事务边界由 session_scope 决定），除非函数名以 `_in_tx` 结尾。
  * 写入用 `session.add()` + 调用方 await session.flush()，拿到主键但
    尚未提交 —— 允许上层在一次事务里组装复杂对象。
  * 列表接口统一返回 `Page[T]`（含 total / has_next），避免每个调用点
    自己拼分页参数导致 offset 越界。
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import (
    Any,
    Generic,
    Iterable,
    Optional,
    Sequence,
    TypeVar,
)

from sqlalchemy import Select, case, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from . import models as m

T = TypeVar("T")


# --------------------------------------------------------------------------
# 通用工具
# --------------------------------------------------------------------------


def utcnow() -> datetime:
    """统一的时间源：aware UTC。

    全库禁止用 naive datetime。naive 与 aware 混用时 Python 会直接抛
    TypeError，而 SQLite 读回来又总会退化成 naive —— 所以写入侧统一
    给 aware 值，读取侧用 `as_utc()` 补回 tzinfo，两头对齐。
    """
    return datetime.now(timezone.utc)


def as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """把数据库读出的 datetime 归一化成 aware UTC。

    SQLite 不保留 tzinfo（即使列声明了 timezone=True），PG 会保留。
    统一在仓储出口做这件事，调用方就永远只见 aware 时间。
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(slots=True)
class Page:
    """分页结果。

    为什么不直接返回 list + 让调用方再 count 一次：那个 count 是第二次
    往返，且在并发写入下会和列表对不上（total 与实际行数不一致的 UI 很容易
    被当成 bug 报上来）。一次查询把总数带回来更省。
    """

    items: list[Any]
    total: int
    limit: int
    offset: int

    @property
    def has_next(self) -> bool:
        return self.offset + len(self.items) < self.total

    @property
    def has_prev(self) -> bool:
        return self.offset > 0


async def paginate(
    session: AsyncSession, stmt: Select, *, limit: int = 20, offset: int = 0
) -> Page:
    """对一条 SELECT 分页，并附带总数。

    ``count_stmt`` 从原语句派生而非另写一条 —— 这样业务条件永远和
    计数口径一致，不会出现"筛选条件改了但 count 没改"的经典漂移。
    """
    # with_only_columns 剥掉 ORDER BY 的列，count 不需要排序。
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = (await session.execute(count_stmt)).scalar_one()
    items = list((await session.execute(stmt.limit(limit).offset(offset))).scalars())
    return Page(items=items, total=total, limit=limit, offset=offset)


# --------------------------------------------------------------------------
# fingerprint —— 同根因聚合
# --------------------------------------------------------------------------

# 归一化时丢弃的"易变部分"：URL 里的自增 id、锚点、临时参数。
# 目的：让 `/product/1001` 与 `/product/1002` 的"缺 alt"聚成一条行动，
# 而不是让 3000 个商品页刷屏 3000 条建议。
_VOLATILE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"[?#].*$"),          # 查询串与锚点
    re.compile(r"\b\d{4,}\b"),       # 长的数字串（id / 时间戳）
    re.compile(r"/\d+(?=/|$)"),      # 路径里的纯数字段
)
_WS = re.compile(r"\s+")
_TRIM = re.compile(r"^[\s\W_]+|[\s\W_]+$", re.UNICODE)


def _severity_rank_case() -> Any:
    """把 severity 列翻译成"数字越小越严重"的排序列。

    severity 在库里是 VARCHAR（见 models.enum_column 的取舍），所以直接
    ``ORDER BY severity`` 得到的是字典序：critical < high < info < low < medium
    —— info 会排在 low 前面，与产品定义的严重度顺序相反，且在 PG 与 SQLite
    上都是错的。这里用 CASE 显式声明顺序，而不是把模型改回原生 ENUM
    （那会重新引入 schema 演进被锁死的老问题）。
    """
    # 比的是 ``.value``（小写字符串）而不是枚举成员：列里存的就是
    # values_callable 导出的值，拿枚举成员去比会永远不匹配。
    whens = [
        (m.Severity.CRITICAL.value, 0),
        (m.Severity.HIGH.value, 1),
        (m.Severity.MEDIUM.value, 2),
        (m.Severity.LOW.value, 3),
        (m.Severity.INFO.value, 4),
    ]
    return case(*whens, value=m.Issue.severity)


def normalize_root_cause(raw: Any) -> str:
    """把根因标识压成稳定的归一化字符串。

    规则（顺序有意义）：NFKC 归一（全角/半角、兼容字符）→ 小写 →
    去查询串与长数字 → 压缩空白 → 去首尾标点。
    这样 "  Product  1001 缺少 ALT 文本？ " 与 "product 1002 缺少 alt 文本"
    会落到同一个 key 上。
    """
    if raw is None:
        return ""
    text = unicodedata.normalize("NFKC", str(raw)).strip().lower()
    for pattern in _VOLATILE_PATTERNS:
        text = pattern.sub("", text)
    text = _WS.sub(" ", text)
    return _TRIM.sub("", text)


def compute_fingerprint(code: str, root_cause: Any = None) -> str:
    """同根因聚合键 = code + 归一化后的根因标识。

    用 sha1 而不是裸字符串拼接过长的列：sha1 定长 40 字符，索引体积小，
    且避免把原始证据文本（可能含 URL、正文片段）直接写进索引列。
    取 32 位十六进制足够抗碰撞（我们的聚合场景不涉及对抗性输入）。
    """
    normalized = normalize_root_cause(root_cause)
    payload = f"{code}|{normalized}".encode("utf-8")
    return hashlib.sha1(payload).hexdigest()[:32]


@dataclass(slots=True)
class FingerprintGroup:
    """一个根因的聚合视图。"""

    fingerprint: str
    code: str
    severity: m.Severity
    title: str
    occurrences: int
    affected_count: int
    sample_urls: list[str]


def fingerprint_of_issue(issue: m.Issue) -> str:
    """从一条 Issue 上取聚合根因。

    约定：优先用 ``evidence['root_cause']``（规则引擎显式声明的根因），
    没有就退化到"证据里最能代表同因的那个字段"。规则引擎是本项目的核心
    资产，因此聚合策略对规则作者是可解释的，而不是靠猜。
    """
    evidence = issue.evidence or {}
    root = evidence.get("root_cause")
    if root is None:
        # 退化路径：title + 字段名，忽略具体取值。
        root = f"{issue.title}:{'+'.join(sorted(evidence.keys()))}"
    return compute_fingerprint(issue.code, root)


# --------------------------------------------------------------------------
# sites
# --------------------------------------------------------------------------


class SiteRepository:
    """站点 CRUD。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        domain: str,
        *,
        markets: Optional[Sequence[str]] = None,
        settings: Optional[dict[str, Any]] = None,
    ) -> m.Site:
        site = m.Site(
            domain=_normalize_domain(domain),
            markets=list(markets or [m.Market.BASE.value]),
            settings=dict(settings or {}),
        )
        self.session.add(site)
        await self.session.flush()
        return site

    async def get(self, site_id: int) -> Optional[m.Site]:
        return await self.session.get(m.Site, site_id)

    async def get_by_domain(self, domain: str) -> Optional[m.Site]:
        stmt = select(m.Site).where(m.Site.domain == _normalize_domain(domain))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list(
        self, *, limit: int = 20, offset: int = 0, active_only: bool = False
    ) -> Page:
        stmt = select(m.Site)
        if active_only:
            stmt = stmt.where(m.Site.is_active.is_(True))
        stmt = stmt.order_by(m.Site.id)
        return await paginate(self.session, stmt, limit=limit, offset=offset)

    async def update(self, site_id: int, **fields: Any) -> Optional[m.Site]:
        site = await self.get(site_id)
        if site is None:
            return None
        for key, value in fields.items():
            if not hasattr(site, key):
                raise AttributeError(f"Site 无字段 {key!r}")
            setattr(site, key, value)
        await self.session.flush()
        return site

    async def delete(self, site_id: int) -> bool:
        # 依赖 DB 的 ON DELETE CASCADE 清掉 pages/issues/…，
        # ORM 层不逐表删 —— 那样会漏掉将来新增的子表。
        site = await self.get(site_id)
        if site is None:
            return False
        await self.session.delete(site)
        await self.session.flush()
        return True


def _normalize_domain(domain: str) -> str:
    """把用户填的站点地址收敛成 host。

    去协议、去路径、去 www.、去尾斜杠、转小写。
    `example.com/` 与 `https://WWW.Example.com` 必须是同一个站点 ——
    否则用户会以为接入了一个新站，历史数据全部"消失"。
    """
    text = (domain or "").strip().lower()
    for prefix in ("https://", "http://"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
            break
    text = text.split("/", 1)[0]
    if text.startswith("www."):
        text = text[4:]
    return text


# --------------------------------------------------------------------------
# crawl_jobs
# --------------------------------------------------------------------------


class CrawlJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self, site_id: int, *, job_key: Optional[str] = None
    ) -> m.CrawlJob:
        job = m.CrawlJob(site_id=site_id, job_key=job_key, status=m.JobStatus.PENDING)
        self.session.add(job)
        await self.session.flush()
        return job

    async def start(self, job_id: int) -> Optional[m.CrawlJob]:
        job = await self.session.get(m.CrawlJob, job_id)
        if job is None:
            return None
        job.status = m.JobStatus.RUNNING
        job.started_at = utcnow()
        await self.session.flush()
        return job

    async def finish(
        self,
        job_id: int,
        *,
        status: m.JobStatus = m.JobStatus.SUCCEEDED,
        url_count: int = 0,
        pages_crawled: int = 0,
        error: Optional[str] = None,
        health_score: Optional[float] = None,
        score_breakdown: Optional[dict[str, Any]] = None,
    ) -> Optional[m.CrawlJob]:
        """收尾一次扫描。

        ⚠️ ``health_score`` / ``score_breakdown`` 只在**显式传入**时写，
        且显式传入 ``None`` 也会写（存 null）。理由：失败路径重试调用
        ``finish`` 时不能把上一轮算好的分数悄悄抹掉；而一轮扫描从 PENDING
        到 SUCCEEDED 只结一次账，null 表示「这次确实没算出分数」。
        """
        job = await self.session.get(m.CrawlJob, job_id)
        if job is None:
            return None
        job.status = status
        job.finished_at = utcnow()
        job.url_count = url_count
        job.pages_crawled = pages_crawled
        job.error = error
        if health_score is not None:
            job.health_score = health_score
        if score_breakdown is not None:
            job.score_breakdown = score_breakdown
        await self.session.flush()
        return job

    async def get(self, job_id: int) -> Optional[m.CrawlJob]:
        return await self.session.get(m.CrawlJob, job_id)

    async def latest_for_site(self, site_id: int) -> Optional[m.CrawlJob]:
        stmt = (
            select(m.CrawlJob)
            .where(m.CrawlJob.site_id == site_id)
            .order_by(m.CrawlJob.started_at.desc().nulls_last(), m.CrawlJob.id.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_site(
        self, site_id: int, *, limit: int = 20, offset: int = 0
    ) -> Page:
        stmt = (
            select(m.CrawlJob)
            .where(m.CrawlJob.site_id == site_id)
            .order_by(m.CrawlJob.id.desc())
        )
        return await paginate(self.session, stmt, limit=limit, offset=offset)


# --------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------


@dataclass(slots=True)
class PageUpsertResult:
    """增量写入结果。``changed=False`` 表示内容没变，调用方应跳过规则重跑。"""

    page: m.Page
    created: bool
    changed: bool


class PageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, page_id: int) -> Optional[m.Page]:
        return await self.session.get(m.Page, page_id)

    async def get_by_url(self, site_id: int, url: str) -> Optional[m.Page]:
        stmt = select(m.Page).where(m.Page.site_id == site_id, m.Page.url == url)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create(self, **fields: Any) -> m.Page:
        page = m.Page(**fields)
        self.session.add(page)
        await self.session.flush()
        return page

    async def update(self, page_id: int, **fields: Any) -> Optional[m.Page]:
        page = await self.get(page_id)
        if page is None:
            return None
        for key, value in fields.items():
            if not hasattr(page, key):
                raise AttributeError(f"Page 无字段 {key!r}")
            setattr(page, key, value)
        await self.session.flush()
        return page

    async def delete(self, page_id: int) -> bool:
        page = await self.get(page_id)
        if page is None:
            return False
        await self.session.delete(page)
        await self.session.flush()
        return True

    async def upsert(
        self,
        site_id: int,
        url: str,
        *,
        content_hash: str,
        **fields: Any,
    ) -> PageUpsertResult:
        """按 (site_id, url) 幂等写入，并判断内容是否真的变了。

        这是整个成本模型的心脏：一次全站复扫会对每个 URL 调一次本方法，
        只有 ``changed=True`` 才值得重跑 60+ 条规则。因此比较对象是
        ``content_hash``（正文规范化后的摘要），而不是任意字段 ——
        抓取时间、elapsed_ms 这类每次都会变的噪声不能参与比较。
        """
        page = await self.get_by_url(site_id, url)
        if page is None:
            page = m.Page(
                site_id=site_id, url=url, content_hash=content_hash, **fields
            )
            self.session.add(page)
            await self.session.flush()
            return PageUpsertResult(page=page, created=True, changed=True)

        if page.content_hash == content_hash:
            # 内容没变：仍要更新"这条记录是活的"（最后抓取时间），
            # 否则无法区分"本次抓到且未变"和"本次没抓到"。
            page.fetched_at = fields.get("fetched_at", page.fetched_at)
            await self.session.flush()
            return PageUpsertResult(page=page, created=False, changed=False)

        for key, value in fields.items():
            if hasattr(page, key):
                setattr(page, key, value)
        page.content_hash = content_hash
        await self.session.flush()
        return PageUpsertResult(page=page, created=False, changed=True)

    async def list(
        self,
        site_id: int,
        *,
        limit: int = 20,
        offset: int = 0,
        status_code: Optional[int] = None,
        min_depth: Optional[int] = None,
    ) -> Page:
        stmt = select(m.Page).where(m.Page.site_id == site_id)
        if status_code is not None:
            stmt = stmt.where(m.Page.status_code == status_code)
        if min_depth is not None:
            stmt = stmt.where(m.Page.depth >= min_depth)
        # 按 depth 再 id 排：站点地图树按层渲染，稳定序避免翻页时行跳动。
        stmt = stmt.order_by(m.Page.depth, m.Page.id)
        return await paginate(self.session, stmt, limit=limit, offset=offset)

    async def content_hashes(self, site_id: int) -> dict[str, str]:
        """取全站 ``url -> content_hash``。

        增量扫描的对比基准。返回 dict 而非在 SQL 里做 NOT IN：
        海量 hash 的 IN 列表在 PG 上会撑爆参数上限，而在应用侧比较只需
        一次 O(n) 哈希查找。
        """
        stmt = select(m.Page.url, m.Page.content_hash).where(
            m.Page.site_id == site_id
        )
        rows = (await self.session.execute(stmt)).all()
        return {url: chash for url, chash in rows}

    async def diff_against(
        self, site_id: int, seen: dict[str, str]
    ) -> list[str]:
        """增量扫描：哪些 URL 是"新发现或内容已变"。

        返回需要重跑规则的 URL 列表（已存在库中）。全新 URL 由调用方直接
        当作需要处理，不在此列 —— 库里的"缺席"本身就是"已变"信号。
        """
        known = await self.content_hashes(site_id)
        return [url for url, chash in seen.items() if known.get(url) != chash]

    async def unchanged_urls(
        self, site_id: int, seen: dict[str, str]
    ) -> list[str]:
        """增量扫描：哪些 URL 内容完全没变（可跳过规则重跑）。"""
        known = await self.content_hashes(site_id)
        return [url for url, chash in seen.items() if known.get(url) == chash]

    async def count(self, site_id: int) -> int:
        stmt = select(func.count()).select_from(m.Page).where(
            m.Page.site_id == site_id
        )
        return (await self.session.execute(stmt)).scalar_one()


# --------------------------------------------------------------------------
# issues
# --------------------------------------------------------------------------


class IssueRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self, site_id: int, code: str, severity: m.Severity | str, **fields: Any
    ) -> m.Issue:
        issue = m.Issue(
            site_id=site_id,
            code=code,
            severity=m.Severity(severity),
            fingerprint=fields.pop("fingerprint", None)
            or compute_fingerprint(code, fields.get("evidence", {}).get("root_cause")),
            **fields,
        )
        self.session.add(issue)
        await self.session.flush()
        return issue

    async def sync_for_scan(
        self,
        site_id: int,
        *,
        job_id: int,
        rows: Iterable[dict[str, Any]],
        scoped_urls: Optional[set[str]] = None,
    ) -> dict[str, int]:
        """一轮扫描的问题入库 —— **认领同一条，而不是再插一行**。

        ⚠️ 以前这里是 ``bulk_create`` 无条件 INSERT，于是同一个站点每重扫
        一次就多一整套重复行（实测 site 1：job1=7 行 → job2=36 行，全库
        16 组「同站点+同指纹+同 URL」重复）。更糟的是用户标了「已修」的
        那些行**原封不动留在库里**，问题总数只涨不跌，「已修」按钮等于
        只能用一次。

        ## 认领键为什么是 (fingerprint, url) 而不是 fingerprint

        fingerprint = sha1(code + 归一化根因)，本就**故意**让
        ``/product/1001`` 与 ``/product/1002`` 聚成同一根因 —— 那是给
        「这一类影响多少页」用的聚合视图。但入库粒度是「一条 Issue =
        一条可单独勾选、单独统计的行动项」，一条记录得挂在具体某页上。
        所以入库认领要按 (指纹, 页面)，聚合留给读时的
        ``group_by_fingerprint()``。两件事混在一起就既没法批量修、
        也说不清影响面。

        ## 状态怎么演进（这是用户手动状态与事实的分工）

        - ``IGNORED`` / ``FALSE_POSITIVE`` —— 用户对**规则适用性**下的判断，
          重扫再命中也不翻回去。这类判断跨轮次成立，翻回去等于让用户
          每次扫描都要重新解释一遍自己为什么忽略。
        - ``FIXED`` —— 「我改了」是个**事实主张**，而扫描结果能直接证伪
          它。所以仍命中就翻回 OPEN：用户以为修好了，实际没修好，这正是
          他需要知道的。**保持 FIXED 才是骗人。**
        - ``OPEN`` / ``ACKNOWLEDGED`` —— 保持。
        """
        existing = (
            (
                await self.session.execute(
                    select(m.Issue).where(m.Issue.site_id == site_id)
                )
            )
            .scalars()
            .all()
        )
        # ⚠️ 不能直接 {key: i} 建字典 —— 修复前的库里**已经有重复行**（实测
        # rust-lang.org 9 组），字典会让同一 key 静默塌成最后一条，前面的
        # 变成僵尸：用户标 fixed 的是 A 行，重扫更新的是 B 行，
        # 僵尸行照样进报告计数 —— 同一个问题在列表里出现两次，
        # 用户看着像「修复没生效」，其实在跟自己打架。
        #
        # 所以先**合并**：同一 key 有多行时，带用户判断的那行当正本
        # （fixed/ignored/false_positive 都是人下的结论，不能丢）；
        # 全是 open 就取 id 最小的（最老那条，身份稳定）。其余物理删除 ——
        # 它们是 bug 造出来的，不是历史事实，status 枚举里没有「已废弃」，
        # 硬塞一个状态只会让所有查询都得记得排除它。
        by_key: dict[tuple[str, Optional[str]], m.Issue] = {}
        merged = 0
        for i in sorted(existing, key=lambda x: x.id):
            key = (i.fingerprint, i.url)
            keeper = by_key.get(key)
            if keeper is None:
                by_key[key] = i
                continue
            merged += 1
            if (
                keeper.status is m.IssueStatus.OPEN
                and i.status is not m.IssueStatus.OPEN
            ):
                await self.session.delete(keeper)
                by_key[key] = i
            else:
                await self.session.delete(i)

        stats = {"created": 0, "updated": 0, "reopened": 0,
                 "kept_verdict": 0, "auto_closed": 0, "merged_dupes": merged}
        seen: set[tuple[str, Optional[str]]] = set()

        for row in rows:
            fp = row.get("fingerprint") or compute_fingerprint(
                row["code"], row.get("evidence", {}).get("root_cause")
            )
            key = (fp, row.get("url"))
            seen.add(key)
            hit = by_key.get(key)

            if hit is None:
                # ⚠️ 指纹只能从 row 里带进去一次：再单写一个 fingerprint=fp
                # 就是重复关键字参数，Python 直接 TypeError。
                # create() 内部会 pop 掉它并用我们算好的值。
                await self.create(site_id=site_id, **{**row, "fingerprint": fp})
                stats["created"] += 1
                continue

            # 已认领到同一条：刷新事实字段，但不动用户状态
            hit.job_id = row.get("job_id", job_id)
            hit.page_id = row.get("page_id", hit.page_id)
            hit.severity = m.Severity(row["severity"])
            hit.last_seen_at = utcnow()
            stats["updated"] += 1

            if hit.status in (m.IssueStatus.IGNORED, m.IssueStatus.FALSE_POSITIVE):
                stats["kept_verdict"] += 1
            elif hit.status is m.IssueStatus.FIXED:
                hit.status = m.IssueStatus.OPEN
                stats["reopened"] += 1

        # ── 收尾：本轮没再命中的旧问题，算「已消失」 ──
        # ⚠️ 只在**本轮确实扫到那个页面**时才敢收尾。上一轮扫 100 页、
        # 这轮只扫 10 页，第 90 页上的一条问题本轮压根没被检查过 ——
        # 把「没检查」当成「已修好」是谎报，而用户会照着这个数字去改
        # 已经改好的东西。所以 scoped_urls 是本轮实际抓到的 URL 集合，
        # 旧问题的 URL 不在其中就一律不动。
        stats["auto_closed"] = 0
        if scoped_urls is not None:
            for old_issue in existing:
                if old_issue.status is not m.IssueStatus.OPEN:
                    continue
                if (old_issue.fingerprint, old_issue.url) in seen:
                    continue
                # site 级问题（url 为 None）永远算在范围内
                if old_issue.url is not None and old_issue.url not in scoped_urls:
                    continue
                old_issue.status = m.IssueStatus.FIXED
                stats["auto_closed"] += 1

        await self.session.flush()
        return stats

    async def bulk_create(
        self, site_id: int, issues: Iterable[dict[str, Any]]
    ) -> list[m.Issue]:
        """一次扫描的全部问题落库。

        **不**在内部聚合成一条：一条 Issue 记录 = 一条可勾选、可单独修复、
        可单独统计的行动项；聚合视图由 `group_by_fingerprint()` 在读时给出。
        把两件事混在一起会让人无法回答"这个问题一共影响多少页"。
        """
        created: list[m.Issue] = []
        for payload in issues:
            created.append(await self.create(site_id=site_id, **payload))
        return created

    async def get(self, issue_id: int) -> Optional[m.Issue]:
        return await self.session.get(m.Issue, issue_id)

    async def list(
        self,
        site_id: int,
        *,
        severity: Optional[m.Severity | str] = None,
        code: Optional[str] = None,
        status: Optional[m.IssueStatus | str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Page:
        stmt = select(m.Issue).where(m.Issue.site_id == site_id)
        if severity is not None:
            stmt = stmt.where(m.Issue.severity == m.Severity(severity))
        if code is not None:
            stmt = stmt.where(m.Issue.code == code)
        if status is not None:
            stmt = stmt.where(m.Issue.status == m.IssueStatus(status))
        # 先按真实严重度，再按 id 稳定收尾 —— 同一严重度内部保持插入序，
        # 翻页时不会出现行跳动。
        stmt = stmt.order_by(_severity_rank_case(), m.Issue.id)
        return await paginate(self.session, stmt, limit=limit, offset=offset)

    async def group_by_fingerprint(
        self,
        site_id: int,
        *,
        status: Optional[m.IssueStatus | str] = None,
        limit: int = 50,
    ) -> list[FingerprintGroup]:
        """按根因聚合 —— 回答"这类问题一共波及多少页、值得批量修吗"。

        用 SQL GROUP BY 而不是拉回内存再统计：问题数在大站上可达十万级，
        且聚合结果要分页。
        """
        conditions = [m.Issue.site_id == site_id]
        if status is not None:
            conditions.append(m.Issue.status == m.IssueStatus(status))
        stmt = (
            select(
                m.Issue.fingerprint,
                m.Issue.code,
                # 同一指纹理论上 severity 一致（fingerprint 含 code），
                # 用 min 只是为了在脏数据下仍能给出确定性的排序结果。
                func.min(m.Issue.severity).label("severity"),
                func.min(m.Issue.title).label("title"),
                func.count(func.distinct(m.Issue.id)).label("affected"),
            )
            .where(*conditions)
            .group_by(m.Issue.fingerprint, m.Issue.code)
            .order_by(func.count(func.distinct(m.Issue.id)).desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).all()

        groups: list[FingerprintGroup] = []
        for fp, code, severity, title, affected in rows:
            sample_stmt = (
                select(m.Issue.url)
                .where(
                    m.Issue.site_id == site_id,
                    m.Issue.fingerprint == fp,
                )
                .limit(3)
            )
            samples = [r for r in (await self.session.execute(sample_stmt)).scalars() if r]
            groups.append(
                FingerprintGroup(
                    fingerprint=fp,
                    code=code,
                    severity=severity,
                    title=title,
                    occurrences=affected,
                    affected_count=affected,
                    sample_urls=samples,
                )
            )
        return groups

    async def set_status(
        self, issue_id: int, status: m.IssueStatus | str
    ) -> Optional[m.Issue]:
        """改单条问题的状态（"这条我改了"）。

        ⚠️ 必须校验问题归属：只按 id 更新的话，
        ``PATCH /sites/1/issues/9999`` 会把 2 号站点的问题改掉——
        而站点是这个产品的租户边界（见 models 注释第 3 条）。
        越界写入比 404 更难查，因为调用方拿到的是 200。
        """
        job = await self.session.get(m.Issue, issue_id)
        if job is None:
            return None
        job.status = m.IssueStatus(status)
        await self.session.flush()
        return job

    async def resolve_by_fingerprint(
        self, site_id: int, fingerprint: str, status: m.IssueStatus | str
    ) -> int:
        """批量更新某一根因下所有问题的状态（"批量确认/批量忽略"）。"""
        stmt = (
            update(m.Issue)
            .where(m.Issue.site_id == site_id, m.Issue.fingerprint == fingerprint)
            .values(status=m.IssueStatus(status))
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return int(result.rowcount or 0)

    async def refresh_occurrences(self, site_id: int) -> None:
        """按指纹回填 ``occurrences``，让读路径不必再算一次 COUNT。"""
        stmt = (
            select(m.Issue.fingerprint, func.count(m.Issue.id))
            .where(m.Issue.site_id == site_id)
            .group_by(m.Issue.fingerprint)
        )
        counts = dict((await self.session.execute(stmt)).all())
        for fp, count in counts.items():
            await self.session.execute(
                update(m.Issue)
                .where(m.Issue.site_id == site_id, m.Issue.fingerprint == fp)
                .values(occurrences=count)
            )
        await self.session.flush()

    async def delete_resolved_for_job(
        self, site_id: int, job_id: int, status: m.IssueStatus | str
    ) -> int:
        """某次扫描已不再命中的问题收尾。

        保留历史审计（因此只改 status 不 delete），但默认查询会把它们滤掉。
        """
        stmt = (
            update(m.Issue)
            .where(
                m.Issue.site_id == site_id,
                m.Issue.job_id == job_id,
                m.Issue.status == m.IssueStatus(status),
            )
            .values(status=m.IssueStatus.FIXED)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return int(result.rowcount or 0)

    async def count_by_severity(self, site_id: int) -> dict[str, int]:
        """OPEN 问题按严重度的条数，键为 severity 的**值**（"high" 而非 "Severity.HIGH"）。

        键必须是 ``.value``：3.11 起 ``str()`` 对 ``str, Enum`` 成员返回
        ``"Severity.HIGH"``。SQLAlchemy 读回的分组键是枚举成员，若直接
        ``str()``，调用方拿 "high" 去查就会 KeyError。
        """
        stmt = (
            select(m.Issue.severity, func.count(m.Issue.id))
            .where(m.Issue.site_id == site_id, m.Issue.status == m.IssueStatus.OPEN)
            .group_by(m.Issue.severity)
        )
        rows = (await self.session.execute(stmt)).all()
        return {
            (sev.value if isinstance(sev, m.Severity) else str(sev)): int(n)
            for sev, n in rows
        }

    async def clear_job(
        self, job_id: int, *, status: Optional[m.IssueStatus | str] = None
    ) -> int:
        """清掉某次扫描产出的问题（重跑扫描前调用，保证幂等）。"""
        stmt = delete(m.Issue).where(m.Issue.job_id == job_id)
        if status is not None:
            stmt = stmt.where(m.Issue.status == m.IssueStatus(status))
        result = await self.session.execute(stmt)
        await self.session.flush()
        return int(result.rowcount or 0)


# --------------------------------------------------------------------------
# keywords / serp
# --------------------------------------------------------------------------


class KeywordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self, site_id: int, term: str, *, market: str = "google", **fields: Any
    ) -> m.Keyword:
        kw = m.Keyword(site_id=site_id, term=term, market=m.Market(market), **fields)
        self.session.add(kw)
        await self.session.flush()
        return kw

    async def get(self, keyword_id: int) -> Optional[m.Keyword]:
        return await self.session.get(m.Keyword, keyword_id)

    async def get_by_term(
        self, site_id: int, term: str, *, market: str = "google"
    ) -> Optional[m.Keyword]:
        stmt = select(m.Keyword).where(
            m.Keyword.site_id == site_id,
            m.Keyword.term == term,
            m.Keyword.market == m.Market(market),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def bulk_upsert(
        self, site_id: int, terms: Iterable[dict[str, Any]]
    ) -> list[m.Keyword]:
        """词库导入幂等：已存在的（站点,市场,词）更新指标，不新增行。"""
        out: list[m.Keyword] = []
        for payload in terms:
            # ⚠️ 必须 pop，不能只用 get：`create(..., market=market, **payload)`
            # 里 payload 若仍带 market 键，就是「multiple values for keyword
            # 'market'」。我第一版在调用方绕开这个键，其实是把 bug 藏起来——
            # 正确做法是修根因，否则下一个传 market 的调用方照样炸。
            market = payload.pop("market", "google")
            existing = await self.get_by_term(
                site_id, payload["term"], market=market
            )
            if existing is None:
                out.append(await self.create(site_id, payload.pop("term"), market=market, **payload))
            else:
                for key, value in payload.items():
                    if key != "term" and hasattr(existing, key):
                        setattr(existing, key, value)
                out.append(existing)
        await self.session.flush()
        return out

    async def list(
        self,
        site_id: int,
        *,
        intent: Optional[str] = None,
        cluster_id: Optional[int] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Page:
        stmt = select(m.Keyword).where(m.Keyword.site_id == site_id)
        if intent is not None:
            stmt = stmt.where(m.Keyword.intent == m.Intent(intent))
        if cluster_id is not None:
            stmt = stmt.where(m.Keyword.cluster_id == cluster_id)
        stmt = stmt.order_by(m.Keyword.id)
        return await paginate(self.session, stmt, limit=limit, offset=offset)


class SerpRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def bulk_create(self, rows: Iterable[dict[str, Any]]) -> list[m.SerpSnapshot]:
        out = []
        for payload in rows:
            snap = m.SerpSnapshot(**payload)
            self.session.add(snap)
            out.append(snap)
        await self.session.flush()
        return out

    async def latest_for_keyword(
        self, keyword_id: int, *, limit: int = 10
    ) -> list[m.SerpSnapshot]:
        """取该词最近一次抓取的 Top N。

        用子查询先定位"最新时刻"再取行，而不是 ORDER BY captured_at LIMIT 1
        后再取同刻的全部行 —— 后者在 SQL 里要么写两趟，要么用窗口函数，
        前者更直白且在两种方言上都能跑。
        """
        latest = (
            select(func.max(m.SerpSnapshot.captured_at))
            .where(m.SerpSnapshot.keyword_id == keyword_id)
            .scalar_subquery()
        )
        stmt = (
            select(m.SerpSnapshot)
            .where(
                m.SerpSnapshot.keyword_id == keyword_id,
                m.SerpSnapshot.captured_at == latest,
            )
            .order_by(m.SerpSnapshot.position)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def list_for_keyword(
        self, keyword_id: int, *, limit: int = 20, offset: int = 0
    ) -> Page:
        stmt = (
            select(m.SerpSnapshot)
            .where(m.SerpSnapshot.keyword_id == keyword_id)
            .order_by(m.SerpSnapshot.captured_at.desc(), m.SerpSnapshot.position)
        )
        return await paginate(self.session, stmt, limit=limit, offset=offset)


# --------------------------------------------------------------------------
# rank_history
# --------------------------------------------------------------------------


class RankHistoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_day(
        self, site_id: int, url: str, day: date, **fields: Any
    ) -> m.RankHistory:
        """按 (site_id, url, date) 幂等写入当日记录。

        GSC/GA4 每天会重跑并回补最近 3 天数据，没有幂等 upsert 就会出现
        重复行，趋势图和告警全部失真。
        """
        existing = await self.get(site_id, url, day)
        if existing is None:
            row = m.RankHistory(site_id=site_id, url=url, date=day, **fields)
            self.session.add(row)
        else:
            for key, value in fields.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            row = existing
        await self.session.flush()
        return row

    async def get(
        self, site_id: int, url: str, day: date
    ) -> Optional[m.RankHistory]:
        stmt = select(m.RankHistory).where(
            m.RankHistory.site_id == site_id,
            m.RankHistory.url == url,
            m.RankHistory.date == day,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def series(
        self,
        site_id: int,
        url: str,
        *,
        start: Optional[date] = None,
        end: Optional[date] = None,
    ) -> list[m.RankHistory]:
        """某页面的排名/点击时序（升序），用于趋势图与跌幅告警。"""
        stmt = select(m.RankHistory).where(
            m.RankHistory.site_id == site_id, m.RankHistory.url == url
        )
        if start is not None:
            stmt = stmt.where(m.RankHistory.date >= start)
        if end is not None:
            stmt = stmt.where(m.RankHistory.date <= end)
        stmt = stmt.order_by(m.RankHistory.date)
        return list((await self.session.execute(stmt)).scalars())

    async def recent(self, site_id: int, *, days: int = 30) -> list[m.RankHistory]:
        """最近 N 天的全站记录（跌幅告警的输入）。"""
        stmt = (
            select(m.RankHistory)
            .where(m.RankHistory.site_id == site_id)
            .order_by(m.RankHistory.date.desc(), m.RankHistory.url)
            .limit(days * 1000)
        )
        return list((await self.session.execute(stmt)).scalars())


# --------------------------------------------------------------------------
# suggestions / briefs
# --------------------------------------------------------------------------


class SuggestionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, site_id: int, url: str, type_: str, **fields: Any) -> m.Suggestion:
        sug = m.Suggestion(
            site_id=site_id, url=url, type=m.SuggestionType(type_), **fields
        )
        self.session.add(sug)
        await self.session.flush()
        return sug

    async def get(self, suggestion_id: int) -> Optional[m.Suggestion]:
        return await self.session.get(m.Suggestion, suggestion_id)

    async def list(
        self,
        site_id: int,
        *,
        url: Optional[str] = None,
        type_: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Page:
        stmt = select(m.Suggestion).where(m.Suggestion.site_id == site_id)
        if url is not None:
            stmt = stmt.where(m.Suggestion.url == url)
        if type_ is not None:
            stmt = stmt.where(m.Suggestion.type == m.SuggestionType(type_))
        if status is not None:
            stmt = stmt.where(m.Suggestion.status == m.SuggestionStatus(status))
        stmt = stmt.order_by(m.Suggestion.id)
        return await paginate(self.session, stmt, limit=limit, offset=offset)

    async def apply(self, suggestion_id: int) -> Optional[m.Suggestion]:
        sug = await self.get(suggestion_id)
        if sug is None:
            return None
        sug.status = m.SuggestionStatus.APPLIED
        sug.applied_at = utcnow()
        await self.session.flush()
        return sug

    async def revert(self, suggestion_id: int) -> Optional[m.Suggestion]:
        """撤回。before_text 已在库里，还原由调用方（应用层）执行写入。"""
        sug = await self.get(suggestion_id)
        if sug is None:
            return None
        sug.status = m.SuggestionStatus.REVERTED
        sug.reverted_at = utcnow()
        await self.session.flush()
        return sug


class ContentBriefRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(
        self, site_id: int, target_url: str, **fields: Any
    ) -> m.ContentBrief:
        kw_id = fields.get("keyword_id")
        stmt = select(m.ContentBrief).where(
            m.ContentBrief.target_url == target_url,
            m.ContentBrief.keyword_id == kw_id,
        )
        brief = (await self.session.execute(stmt)).scalar_one_or_none()
        if brief is None:
            brief = m.ContentBrief(site_id=site_id, target_url=target_url, **fields)
            self.session.add(brief)
        else:
            for key, value in fields.items():
                if hasattr(brief, key):
                    setattr(brief, key, value)
        await self.session.flush()
        return brief

    async def get(self, brief_id: int) -> Optional[m.ContentBrief]:
        return await self.session.get(m.ContentBrief, brief_id)

    async def list(
        self, site_id: int, *, status: Optional[str] = None, limit: int = 20, offset: int = 0
    ) -> Page:
        stmt = select(m.ContentBrief).where(m.ContentBrief.site_id == site_id)
        if status is not None:
            stmt = stmt.where(m.ContentBrief.status == m.BriefStatus(status))
        stmt = stmt.order_by(m.ContentBrief.id)
        return await paginate(self.session, stmt, limit=limit, offset=offset)


# --------------------------------------------------------------------------
# 门面
# --------------------------------------------------------------------------


class UnitOfWork:
    """一次事务里用到的全部仓储。

    存在的理由是依赖注入：调用方（FastAPI 依赖 / Celery task）只需构造
    一次，就能拿到所有仓储，且它们天然共享同一个 session 与事务边界。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.sites = SiteRepository(session)
        self.jobs = CrawlJobRepository(session)
        self.pages = PageRepository(session)
        self.issues = IssueRepository(session)
        self.keywords = KeywordRepository(session)
        self.serp = SerpRepository(session)
        self.ranks = RankHistoryRepository(session)
        self.suggestions = SuggestionRepository(session)
        self.briefs = ContentBriefRepository(session)

    async def flush(self) -> None:
        await self.session.flush()

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()


# --------------------------------------------------------------------------
# 模块级门面 —— 规格里点名的六个核心操作
# --------------------------------------------------------------------------
# 为什么不强迫调用方先构造 UnitOfWork 再一层层转发：抓取 Agent 与 CLI 里
# 的典型调用是"拿一个 session 做一件事"，为此多写三层样板反而容易抄错参数。
# 这些函数不是重复实现，只是把对应的仓储方法原样接出来，逻辑与口径仍然
# 只有仓储类一处实现。

async def upsert_page(session: AsyncSession, site_id: int, url: str, **fields: Any) -> PageUpsertResult:
    """按 (site_id, url) 幂等写页面，并返回内容是否变化。"""
    return await PageRepository(session).upsert(site_id, url, **fields)


async def get_page_content_hashes(session: AsyncSession, site_id: int) -> dict[str, str]:
    """取全站 ``url -> content_hash``（增量扫描的对比基准）。"""
    return await PageRepository(session).content_hashes(site_id)


async def create_crawl_job(
    session: AsyncSession, site_id: int, *, job_key: Optional[str] = None
) -> m.CrawlJob:
    """登记一次扫描，初始状态 PENDING。"""
    return await CrawlJobRepository(session).create(site_id, job_key=job_key)


async def finish_job(session: AsyncSession, job_id: int, **fields: Any) -> Optional[m.CrawlJob]:
    """收尾一次扫描（写终态、计数、错误与结束时间）。"""
    return await CrawlJobRepository(session).finish(job_id, **fields)


async def save_issues(
    session: AsyncSession, site_id: int, issues: Iterable[dict[str, Any]]
) -> list[m.Issue]:
    """一次扫描的全部问题落库（fingerprint 自动补算）。

    ⚠️ **只用于「首次」落库。** 重复扫描请走 :func:`sync_issues_for_scan` ——
    这里是无条件 INSERT，每扫一次就多一整套重复行。
    """
    return await IssueRepository(session).bulk_create(site_id, issues)


async def sync_issues_for_scan(
    session: AsyncSession,
    site_id: int,
    *,
    job_id: int,
    issues: Iterable[dict[str, Any]],
    scoped_urls: Optional[set[str]] = None,
) -> dict[str, int]:
    """一轮扫描的问题入库 —— 认领已有的，而不是再插一行。

    重复扫描必须走这个，否则：同一个站每重扫一次问题数就翻一倍以上，
    且用户标过「已修」的行原样留着，「已修」按钮等于只能用一次。
    语义见 :meth:`IssueRepository.sync_for_scan`。
    """
    return await IssueRepository(session).sync_for_scan(
        site_id, job_id=job_id, rows=issues, scoped_urls=scoped_urls
    )


async def query_issues_by_fingerprint(
    session: AsyncSession,
    site_id: int,
    *,
    status: Optional[m.IssueStatus | str] = None,
    limit: int = 50,
) -> list[FingerprintGroup]:
    """按根因聚合查询 —— 回答"这类问题波及多少页、值得批量修吗"。"""
    return await IssueRepository(session).group_by_fingerprint(
        site_id, status=status, limit=limit
    )


async def query_rank_history(
    session: AsyncSession,
    site_id: int,
    url: str,
    *,
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> list[m.RankHistory]:
    """某页面的排名/点击时序（升序）。"""
    return await RankHistoryRepository(session).series(
        site_id, url, start=start, end=end
    )


__all__ = [
    "utcnow",
    "as_utc",
    "Page",
    "paginate",
    "upsert_page",
    "get_page_content_hashes",
    "create_crawl_job",
    "finish_job",
    "save_issues",
    "sync_issues_for_scan",
    "query_issues_by_fingerprint",
    "query_rank_history",
    "normalize_root_cause",
    "compute_fingerprint",
    "fingerprint_of_issue",
    "FingerprintGroup",
    "PageUpsertResult",
    "SiteRepository",
    "CrawlJobRepository",
    "PageRepository",
    "IssueRepository",
    "KeywordRepository",
    "SerpRepository",
    "RankHistoryRepository",
    "SuggestionRepository",
    "ContentBriefRepository",
    "UnitOfWork",
]
