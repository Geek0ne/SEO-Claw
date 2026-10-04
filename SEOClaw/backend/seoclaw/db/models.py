"""SQLAlchemy 2.0 ORM 模型 —— 全库表结构的唯一真相源。

设计取舍说明（为什么这么设计，而不是照抄 REQUIREMENTS 第 6 节的字段列表）：

1. **枚举用 `native_enum=False` 的 VARCHAR + CHECK，而不是 PG 原生 ENUM。**
   PG 原生 ENUM 增删值要走 `ALTER TYPE`，Alembic autogenerate 识别不了，
   一旦要加一个 severity 就会卡住发布；而 VARCHAR+CHECK 在 PG 和 SQLite 上
   行为完全一致 —— 这让整层可以在没有 PG 的机器上跑单测（见 tests/test_db.py）。

2. **JSON 字段用 `JSON.with_variant(JSONB, "postgresql")`。**
   生产 PG 上拿 JSONB（二进制存储、可用 GIN 索引），SQLite 测试时自动退回
   通用 JSON 包装器。同一份模型两处可用，避免为了测试引入方言分支。

3. **所有业务表都带 `site_id` 并对 site 配 `ON DELETE CASCADE`。**
   站点是这个产品的租户边界：删一个站点应当连带删掉它的抓取结果和问题，
   而残留孤儿行会污染跨站聚合统计。CASCADE 放在数据库层而不是应用层，
   是因为 CLI / Worker / 未来 API 三条写入路径都可能绕过应用层。

4. **URL 统一以 TEXT 存，不做长度截断。**
   截断过的 URL 无法反查原页，等于制造不可修复的数据损坏；PG 的 TOAST
   对长字符串透明。

5. **`fetched_at` / `captured_at` 等业务时间用带时区 datetime，`created_at`
   用 `func.now()` 服务端默认值。**
   抓取时间一定是显式传入的（爬虫知道自己的时刻），而"行被创建的时间"
   交给数据库更可靠 —— 应用服务器时钟漂移不会污染审计字段。
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

# 统一 JSON 类型：PG 上用 JSONB，其它方言（含测试用 SQLite）用通用 JSON。
JSONType = JSON().with_variant(JSONB(), "postgresql")


def enum_column(py_enum: type[enum.Enum], name: str) -> Enum:
    """构造跨方言可用的枚举列（VARCHAR + CHECK 约束）。

    直接用 ``py_enum`` 作为列类型时 SQLAlchemy 默认建 PG 原生 ENUM，
    那条路会锁死 schema 演进；这里强制降级为带 CHECK 的字符串。
    """
    return Enum(
        py_enum,
        name=name,
        native_enum=False,
        length=32,
        validate_strings=True,
        values_callable=lambda e: [m.value for m in e],
    )


# --------------------------------------------------------------------------
# 枚举 —— 与 seoclaw.models（Pydantic 领域模型）保持同名同值
# --------------------------------------------------------------------------


class Market(str, enum.Enum):
    """搜索引擎生态 / 目标市场。规则包按此路由。"""

    BASE = "base"
    GOOGLE = "google"
    BAIDU = "baidu"
    CNH_ECO = "cnh_eco"


class Severity(str, enum.Enum):
    """严重度，数字越小越严重（排序用 rank，见 repository）。"""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class Scope(str, enum.Enum):
    """规则作用域：单页可判 / 需要全站数据。"""

    PAGE = "page"
    SITE = "site"


class IssueStatus(str, enum.Enum):
    """问题生命周期。扫描是幂等的：问题本身长期存在，状态独立演进。"""

    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    FIXED = "fixed"
    IGNORED = "ignored"
    FALSE_POSITIVE = "false_positive"


class JobStatus(str, enum.Enum):
    """抓取任务状态。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Intent(str, enum.Enum):
    """搜索意图。内容 Brief 的页型由它决定。"""

    INFORMATIONAL = "informational"
    NAVIGATIONAL = "navigational"
    COMMERCIAL = "commercial"
    TRANSACTIONAL = "transactional"


class SuggestionType(str, enum.Enum):
    """建议类型 —— 决定"应用"时改什么字段。"""

    TITLE = "title"
    META_DESCRIPTION = "meta_description"
    H1 = "h1"
    CONTENT = "content"
    FAQ = "faq"
    CTA = "cta"
    INTERNAL_LINK = "internal_link"
    SCHEMA = "schema"
    REDIRECT = "redirect"


class BriefStatus(str, enum.Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHED = "published"


class SuggestionStatus(str, enum.Enum):
    DRAFT = "draft"
    APPLIED = "applied"
    REVERTED = "reverted"


# --------------------------------------------------------------------------
# Base
# --------------------------------------------------------------------------


class Base(DeclarativeBase):
    """所有 ORM 类的基类。Alembic autogenerate 以此为 metadata 根。"""


class TimestampMixin:
    """行级审计时间。

    只给"什么时候写进库的"，业务自身的时刻（如 fetched_at）由调用方显式传，
    这样重放一次历史抓取时不会伪造出一个"当时"的 created_at。
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# --------------------------------------------------------------------------
# sites
# --------------------------------------------------------------------------


class Site(Base, TimestampMixin):
    """被接入的站点。租户边界，所有业务表的外键都指向它。"""

    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 存规范化后的 host（去 www、去尾斜杠、小写）。规范化在应用层做，
    # 因为"同一个站"的判定规则（是否跟随 www）属于产品策略而非存储细节。
    domain: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    # 一个站可能同时投 google + baidu（B 端常见双语站），故用数组而非单值。
    # 一站可能同时投 google + baidu（B 端常见双语站），故用数组而非单值。
    markets: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    # 抓取配置（并发数、robots 策略、渲染开关…）整体塞 JSON，
    # 避免每加一个开关就改表结构。
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    pages: Mapped[list["Page"]] = relationship(
        back_populates="site", cascade="all, delete-orphan", passive_deletes=True
    )
    issues: Mapped[list["Issue"]] = relationship(
        back_populates="site", cascade="all, delete-orphan", passive_deletes=True
    )
    jobs: Mapped[list["CrawlJob"]] = relationship(
        back_populates="site", cascade="all, delete-orphan", passive_deletes=True
    )


# --------------------------------------------------------------------------
# crawl_jobs
# --------------------------------------------------------------------------


class CrawlJob(Base, TimestampMixin):
    """一次站点扫描。一次扫描产出一次全量 pages/issues 快照。"""

    __tablename__ = "crawl_jobs"
    __table_args__ = (
        # 运维页面最常见的查询是"这个站点最近几次扫描、状态如何"，
        # 复合索引让 ORDER BY started_at DESC LIMIT n 走索引而不是排序全表。
        Index("ix_crawl_jobs_site_status_started", "site_id", "status", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 幂等键：同一站点同一时间的重复触发（同 cron 重入）由此去重，
    # 避免"两份相同的问题"让统计翻倍。
    job_key: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    status: Mapped[JobStatus] = mapped_column(
        enum_column(JobStatus, "job_status"), default=JobStatus.PENDING, nullable=False
    )
    # 只有 page 级规则能发现的页面/已发现 URL 数，url_count 是两者之和。
    url_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pages_crawled: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── 本次扫描的健康分与评分明细 ──
    # ⚠️ 这两列以前不存在，于是 `/sites/{id}/report` 的 `_latest_score()`
    # 去读 `job.score_breakdown` 永远读不到 → health_score 恒为 null →
    # 前端按「一页都没抓到」渲染。**分数算了、显示了，却根本没存。**
    # 这是「查出来的结论没有落库」，比没实现更坏：接口看着是通的。
    health_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    score_breakdown: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONType, nullable=True
    )

    site: Mapped[Site] = relationship(back_populates="jobs")

    @property
    def duration_seconds(self) -> Optional[float]:
        if not self.started_at or not self.finished_at:
            return None
        return (self.finished_at - self.started_at).total_seconds()


# --------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------


class Page(Base, TimestampMixin):
    """一个 URL 的最新抓取结果。同一 URL 只保留"当前"这一行。"""

    __tablename__ = "pages"
    __table_args__ = (
        # 需求硬约束：pages(site_id, url) 唯一。
        # 这不只是数据约束，更是并发约束 —— 两个抓取 worker 同时写同一 URL
        # 时，后写的会因唯一冲突失败而不是静默产生两行重复页面。
        UniqueConstraint("site_id", "url", name="uq_pages_site_url"),
        # 增量扫描的核心查询：某站点里 content_hash 不在本次集合中的页面
        # （即内容变了或新发现的）。hash 定长且区分度高，先按 site_id 收窄
        # 再让 DB 做 hash 过滤，比把整站页面拉回内存比较便宜得多。
        Index("ix_pages_site_content_hash", "site_id", "content_hash"),
        # 站点地图树按 depth 展开，是 P0 功能的高频查询。
        Index("ix_pages_site_depth", "site_id", "depth"),
        # 健康分里要算"多少比例的页面是 4xx/5xx"，这是全量聚合而非点查，
        # 因此只保留 (site_id, status_code) 供 GROUP BY 走索引。
        Index("ix_pages_site_status", "site_id", "status_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    final_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status_code: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    depth: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    discovered_from: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta_desc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    canonical: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    robots_meta: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    h1: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 正文。存正文（而非只存 hash）是因为产品承诺"任何结论都能点开看证据"，
    # 报告与建议生成都要回看原文；只存对象存储 URI 会让离线导出变成网络依赖。
    text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # 渲染后 DOM 的 hash：用于识别"JS 渲染前后内容不一致/cloaking 风险"。
    # 独立于 content_hash，因为两者变化时影响的规则集合不同。
    rendered_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # 规范化正文的 hash：增量扫描的判定依据。变了才重跑规则，
    # 这是本项目最重要的成本闸门（60+ 规则 × 10w URL）。
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    links_json: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )

    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 页面 HTML 快照在 S3/MinIO 的位置；正文已在库里，这个 URI 用于
    # "点开看当时的完整 HTML" 这类取证需求。
    snapshot_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    site: Mapped[Site] = relationship(back_populates="pages")
    issues: Mapped[list["Issue"]] = relationship(
        back_populates="page", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def is_ok(self) -> bool:
        return 200 <= self.status_code < 300


# --------------------------------------------------------------------------
# issues
# --------------------------------------------------------------------------


class Issue(Base, TimestampMixin):
    """一条 SEO 问题。产品的信任机制：每条都必须带可验证的证据。"""

    __tablename__ = "issues"
    __table_args__ = (
        # 需求硬约束：issues(site_id, severity, code)。
        # 这正是"行动清单"页的查询形状 —— 按严重度分组看某类问题有几条。
        Index("ix_issues_site_severity_code", "site_id", "severity", "code"),
        # 同根因聚合查询（同一模板问题波及多少页面），走 fingerprint 索引。
        Index("ix_issues_site_fingerprint", "site_id", "fingerprint"),
        # 未处理问题看板：按站点取 open，按严重度排序。
        Index("ix_issues_site_status_severity", "site_id", "status", "severity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 命中的页面。url 允许为空 —— site 级规则（如全站 title 重复）没有
    # 单一归属页面；此时归到站点首页，避免这些规则在页面上"凭空消失"。
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 指回 pages.id，让"问题 → 页面当前抓取结果"可以走主键点查而不是
    # 每次用长 URL 文本匹配（文本匹配还可能因 URL 规范化差异失配）。
    page_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("pages.id", ondelete="CASCADE"), nullable=True, index=True
    )
    job_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("crawl_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    code: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[Severity] = mapped_column(
        enum_column(Severity, "severity"), nullable=False
    )
    market: Mapped[Market] = mapped_column(
        enum_column(Market, "market"), default=Market.BASE, nullable=False
    )
    scope: Mapped[Scope] = mapped_column(
        enum_column(Scope, "scope"), default=Scope.PAGE, nullable=False
    )
    status: Mapped[IssueStatus] = mapped_column(
        enum_column(IssueStatus, "issue_status"),
        default=IssueStatus.OPEN,
        nullable=False,
    )

    # 同根因聚合键 = code + 归一化后的根因标识。
    # 例：200 个商品页都缺 alt，且缺失模式一致 → 聚成 1 条"批量修 alt"行动，
    # 而不是 200 条噪音。归一化逻辑见 repository.compute_fingerprint。
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    title: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    impact: Mapped[str] = mapped_column(Text, default="", nullable=False)
    fix_hint: Mapped[str] = mapped_column(Text, default="", nullable=False)
    fix_example: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 支撑结论的原始数据（命中元素、期望值、实际值…）。JSON 而非多张子表，
    # 因为各规则的证据形状差异极大且只随规则演进。
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )

    # 跨扫描周期的"持续时间"：规则引擎据此判断问题是否新引入。
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # 同一指纹下受影响页面数：每次扫描重算，供"批量修复价值"排序用。
    occurrences: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    site: Mapped[Site] = relationship(back_populates="issues")
    page: Mapped[Optional[Page]] = relationship(back_populates="issues")
    suggestions: Mapped[list["Suggestion"]] = relationship(back_populates="issue")


# --------------------------------------------------------------------------
# keywords
# --------------------------------------------------------------------------


class Keyword(Base, TimestampMixin):
    """站点跟踪的关键词。"""

    __tablename__ = "keywords"
    __table_args__ = (
        # 同一站点 + 同一市场下词不重复：不同市场（google/baidu）搜同一个词
        # 意图与 SERP 完全不同，必须能并存。
        UniqueConstraint("site_id", "market", "term", name="uq_keywords_site_market_term"),
        # 内容缺口分析按意图切片统计。
        Index("ix_keywords_site_intent", "site_id", "intent"),
        # 聚类结果按 cluster_id 查成员。
        Index("ix_keywords_site_cluster", "site_id", "cluster_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    term: Mapped[str] = mapped_column(Text, nullable=False)
    market: Mapped[Market] = mapped_column(
        enum_column(Market, "market"), default=Market.GOOGLE, nullable=False
    )
    # volume/difficulty 来自外部 Provider，缺失是常态（长尾词），
    # 因此可空而不是用 0 冒充"搜索量真的是 0"。
    volume: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    difficulty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cpc: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    intent: Mapped[Optional[Intent]] = mapped_column(
        enum_column(Intent, "intent"), nullable=True
    )
    cluster_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # 我方是否有页面在竞争这个词。False 的词 = 内容缺口。
    is_tracked: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    tracked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    serp_snapshots: Mapped[list["SerpSnapshot"]] = relationship(
        back_populates="keyword", cascade="all, delete-orphan", passive_deletes=True
    )


# --------------------------------------------------------------------------
# serp_snapshots
# --------------------------------------------------------------------------


class SerpSnapshot(Base):
    """某关键词在某次抓取时刻的 Top10 快照。竞品对比的原始依据。"""

    __tablename__ = "serp_snapshots"
    __table_args__ = (
        # 同一关键词同一次抓取里，一个 URL 只会占一个位置；唯一约束让
        # 重跑 SERP 抓取变成幂等 upsert，而不是堆重复行。
        UniqueConstraint("keyword_id", "captured_at", "url", name="uq_serp_kw_time_url"),
        # 竞品识别按 SERP 重合度算，必须按关键词+时间倒序取快照。
        Index("ix_serp_keyword_captured", "keyword_id", "captured_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keyword_id: Mapped[int] = mapped_column(
        ForeignKey("keywords.id", ondelete="CASCADE"), nullable=False
    )
    # 冗余 site_id：跨关键词的竞品分析要按站点过滤，省掉一次 join。
    site_id: Mapped[int] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    market: Mapped[Market] = mapped_column(
        enum_column(Market, "market"), default=Market.GOOGLE, nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, default="", nullable=False)
    snippet: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # SERP 富结果类型（购物/视频/问答…）与页面类型，逐位记录。
    features: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    keyword: Mapped[Keyword] = relationship(back_populates="serp_snapshots")


# --------------------------------------------------------------------------
# content_briefs
# --------------------------------------------------------------------------


class ContentBrief(Base, TimestampMixin):
    """AI 生成的内容 Brief。brief_json 承载完整结构化正文。"""

    __tablename__ = "content_briefs"
    __table_args__ = (
        # 一个 URL + 一个目标词 = 一份 Brief。重跑生成时按此 upsert，
        # 避免内容日历里同一格出现多份草稿。
        UniqueConstraint(
            "target_url", "keyword_id", name="uq_brief_target_keyword"
        ),
        Index("ix_briefs_site_status", "site_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # brief 的归属 URL 可以是"待新建的 URL"（内容缺口场景），
    # 所以它不是 pages 的外键。
    target_url: Mapped[str] = mapped_column(Text, nullable=False)
    keyword_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("keywords.id", ondelete="SET NULL"), nullable=True, index=True
    )
    market: Mapped[Market] = mapped_column(
        enum_column(Market, "market"), default=Market.GOOGLE, nullable=False
    )
    status: Mapped[BriefStatus] = mapped_column(
        enum_column(BriefStatus, "brief_status"),
        default=BriefStatus.DRAFT,
        nullable=False,
    )
    title_candidates: Mapped[list[Any]] = mapped_column(
        JSONType, default=list, nullable=False
    )
    brief: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )

    keyword: Mapped[Optional[Keyword]] = relationship()


# --------------------------------------------------------------------------
# suggestions
# --------------------------------------------------------------------------


class Suggestion(Base, TimestampMixin):
    """可直接落地的优化建议。产品的北极星指标就建立在"被采纳"之上。"""

    __tablename__ = "suggestions"
    __table_args__ = (
        # "某页面上所有待应用建议"——应用动作与撤回动作都以此定位。
        Index("ix_suggestions_site_url", "site_id", "url"),
        Index("ix_suggestions_site_type_status", "site_id", "type", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    issue_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"), nullable=True, index=True
    )
    type: Mapped[SuggestionType] = mapped_column(
        enum_column(SuggestionType, "suggestion_type"), nullable=False
    )
    # before_text 必须落库：撤回/回滚时需要它还原现场（产品原则"可回滚"）。
    before_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    after_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    rationale: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[SuggestionStatus] = mapped_column(
        enum_column(SuggestionStatus, "suggestion_status"),
        default=SuggestionStatus.DRAFT,
        nullable=False,
    )
    applied_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reverted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    issue: Mapped[Optional[Issue]] = relationship(back_populates="suggestions")


# --------------------------------------------------------------------------
# rank_history
# --------------------------------------------------------------------------


class UsageEvent(Base):
    """一次计量事件（**追加写，不更新**）。

    ⚠️ 为什么不在站点行上放几列就地累加：计数被就地累加时，任何一次重试或
    回滚都会让数字对不上，而且事后无法自证。追加写可以随时 SUM() 重算，
    也能回答「上个月到底跑了多少」—— 计费的数字必须能被复算。

    ⚠️ 唯一约束 (kind, ref_id) 是**幂等键**：任务完成后的投递会重试，
    没有它就重复计量。**重复计量比漏计量严重得多** —— 用户要为没花过的
    额度买单。

    ⚠️ ``at`` 用 ``server_default=func.now()``（与本文件其它表一致），
    不用 Python 侧 default —— 后者在 ORM 层就得算好时间，与 DB 时间可能
    不一致，事后对账会对不上。上一版我就是图省事写了
    ``default=utcnow``，而本模块根本没有 utcnow，一导入就 NameError。
    """

    __tablename__ = "usage_events"
    __table_args__ = (
        UniqueConstraint("kind", "ref_id", name="uq_usage_kind_ref"),
        Index("ix_usage_site_at", "site_id", "at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: pages_crawled / scan_run / llm_tokens ...
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    #: 幂等键：对应记录的 id（如 crawl_job.id）。同 kind 下必须唯一。
    ref_id: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RankHistory(Base):
    """日级排名/点击/曝光时序。后续可整体迁到 TimescaleDB hypertable。"""

    __tablename__ = "rank_history"
    __table_args__ = (
        # 需求硬约束：rank_history(site_id, url, date) 唯一。
        # 语义是"一个页面一天一条汇总记录"：告警、趋势图、页面级对比都按
        # (url, date) 定位，重复导入 GSC/GA4 数据时靠它做幂等 upsert。
        # 注意 keyword_id 在此为"该日主要来源词"的角色，不参与唯一键；
        # 若后续要一词一行，需另建 rank_history_by_keyword 表而非改本约束。
        UniqueConstraint("site_id", "url", "date", name="uq_rank_site_url_date"),
        # 跌幅告警的查询形状：某站点最近 N 天的所有记录按时间倒序。
        Index("ix_rank_site_date", "site_id", "date"),
        # 词维度趋势图。
        Index("ix_rank_site_keyword_date", "site_id", "keyword_id", "date"),
    )

    # 用 BigInteger：这张表是全库增长最快的（站点数 × URL 数 × 天），
    # 32 位 int 在中等规模站点上就会溢出。
    #
    # ⚠️ with_variant 是必须的：SQLite 的自增主键只认「INTEGER PRIMARY KEY」，
    # BIGINT 会被当成普通列，插入时 id 直接是 NULL。
    # 这个坑在线上（PostgreSQL）不暴露，一上 SQLite 测试就炸——
    # 所以测试用 SQLite 是有价值的，它能提前暴露方言差异。
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    site_id: Mapped[int] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    keyword_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("keywords.id", ondelete="SET NULL"), nullable=True
    )
    # Date 而非 DateTime：GSC/GA4 本身按天出数，且按天唯一约束需要
    # 消除"同一时间戳带不带时区"的差异。
    date: Mapped[Any] = mapped_column(Date, nullable=False)
    position: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    clicks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    impressions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # CTR 落库而非实时算：GSC 的 ctr 定义（clicks/impressions）分母口径
    # 与实时数据源可能不同，存下来才能保证趋势可复现。
    ctr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


__all__ = [
    "Base",
    "TimestampMixin",
    "JSONType",
    "Market",
    "Severity",
    "Scope",
    "IssueStatus",
    "JobStatus",
    "Intent",
    "SuggestionType",
    "BriefStatus",
    "SuggestionStatus",
    "Site",
    "CrawlJob",
    "Page",
    "Issue",
    "Keyword",
    "SerpSnapshot",
    "ContentBrief",
    "Suggestion",
    "RankHistory",
    "UsageEvent",
]
