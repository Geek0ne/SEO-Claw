"""初始 schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-29

覆盖 REQUIREMENTS 第 6 节的 9 张核心表，外加 issues.fingerprint（同根因聚合）
与 pages.content_hash（增量扫描判定）两个非需求列表但必需的字段。
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

# JSON 字段：PG 上用 JSONB，其它方言用通用 JSON。
# 与 models.JSONType 同构 —— 迁移必须和应用模型产出同样的库结构，
# 否则"迁移建的库"和"create_all 建的库"会分叉。
JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

# 枚举一律 native_enum=False：VARCHAR + CHECK，而非 PG 原生 ENUM。
# 原因见 models.enum_column 的注释 —— 原生 ENUM 无法被 Alembic 安全演进。
MARKET = sa.Enum(
    "base", "google", "baidu", "cnh_eco", name="market", native_enum=False, length=32
)
SEVERITY = sa.Enum(
    "critical", "high", "medium", "low", "info", name="severity", native_enum=False, length=32
)
SCOPE = sa.Enum("page", "site", name="scope", native_enum=False, length=32)
ISSUE_STATUS = sa.Enum(
    "open",
    "acknowledged",
    "fixed",
    "ignored",
    "false_positive",
    name="issue_status",
    native_enum=False,
    length=32,
)
JOB_STATUS = sa.Enum(
    "pending",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    name="job_status",
    native_enum=False,
    length=32,
)
INTENT = sa.Enum(
    "informational",
    "navigational",
    "commercial",
    "transactional",
    name="intent",
    native_enum=False,
    length=32,
)
SUGGESTION_TYPE = sa.Enum(
    "title",
    "meta_description",
    "h1",
    "content",
    "faq",
    "cta",
    "internal_link",
    "schema",
    "redirect",
    name="suggestion_type",
    native_enum=False,
    length=32,
)
BRIEF_STATUS = sa.Enum(
    "draft",
    "approved",
    "rejected",
    "published",
    name="brief_status",
    native_enum=False,
    length=32,
)
SUGGESTION_STATUS = sa.Enum(
    "draft", "applied", "reverted", name="suggestion_status", native_enum=False, length=32
)


def upgrade() -> None:
    # ------------------------------------------------------------------
    # sites —— 租户边界，其余表的外键都指向它
    # ------------------------------------------------------------------
    op.create_table(
        "sites",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("markets", JSONType, nullable=False),
        sa.Column("settings", JSONType, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("domain"),
    )

    # ------------------------------------------------------------------
    # crawl_jobs
    # ------------------------------------------------------------------
    op.create_table(
        "crawl_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("job_key", sa.String(length=120), nullable=True),
        sa.Column("status", JOB_STATUS, nullable=False),
        sa.Column("url_count", sa.Integer(), nullable=False),
        sa.Column("pages_crawled", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crawl_jobs_site_id", "crawl_jobs", ["site_id"])
    op.create_index("ix_crawl_jobs_site_status_started", "crawl_jobs", ["site_id", "status", "started_at"])

    # ------------------------------------------------------------------
    # pages
    # ------------------------------------------------------------------
    op.create_table(
        "pages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("final_url", sa.Text(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("discovered_from", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("meta_desc", sa.Text(), nullable=True),
        sa.Column("canonical", sa.Text(), nullable=True),
        sa.Column("robots_meta", sa.String(length=128), nullable=True),
        sa.Column("h1", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False),
        # rendered_hash 与 content_hash 分开：前者识别 JS 渲染不一致/cloaking，
        # 后者驱动增量扫描。两者变化时该重跑的规则集合不同。
        sa.Column("rendered_hash", sa.String(length=64), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("links_json", JSONType, nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snapshot_uri", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # 需求硬约束，同时是并发写入的幂等保证
        sa.UniqueConstraint("site_id", "url", name="uq_pages_site_url"),
    )
    op.create_index("ix_pages_site_id", "pages", ["site_id"])
    op.create_index("ix_pages_site_content_hash", "pages", ["site_id", "content_hash"])
    op.create_index("ix_pages_site_depth", "pages", ["site_id", "depth"])
    op.create_index("ix_pages_site_status", "pages", ["site_id", "status_code"])

    # ------------------------------------------------------------------
    # keywords
    # ------------------------------------------------------------------
    op.create_table(
        "keywords",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("term", sa.Text(), nullable=False),
        sa.Column("market", MARKET, nullable=False),
        sa.Column("volume", sa.Integer(), nullable=True),
        sa.Column("difficulty", sa.Float(), nullable=True),
        sa.Column("cpc", sa.Float(), nullable=True),
        sa.Column("intent", INTENT, nullable=True),
        sa.Column("cluster_id", sa.Integer(), nullable=True),
        sa.Column("is_tracked", sa.Boolean(), nullable=False),
        sa.Column("tracked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # 同一站点同一市场下词不重复；跨市场允许重复（SERP 与意图不同）
        sa.UniqueConstraint("site_id", "market", "term", name="uq_keywords_site_market_term"),
    )
    op.create_index("ix_keywords_site_id", "keywords", ["site_id"])
    op.create_index("ix_keywords_site_intent", "keywords", ["site_id", "intent"])
    op.create_index("ix_keywords_site_cluster", "keywords", ["site_id", "cluster_id"])

    # ------------------------------------------------------------------
    # issues
    # ------------------------------------------------------------------
    op.create_table(
        "issues",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("page_id", sa.Integer(), nullable=True),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("severity", SEVERITY, nullable=False),
        sa.Column("market", MARKET, nullable=False),
        sa.Column("scope", SCOPE, nullable=False),
        sa.Column("status", ISSUE_STATUS, nullable=False),
        # 需求外补充：code + 归一化根因的 sha1。缺失时报告无法把
        # "3000 个商品页缺 alt"聚成一条可批量执行的行动。
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("impact", sa.Text(), nullable=False),
        sa.Column("fix_hint", sa.Text(), nullable=False),
        sa.Column("fix_example", sa.Text(), nullable=True),
        sa.Column("evidence", JSONType, nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("occurrences", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["page_id"], ["pages.id"], ondelete="CASCADE"),
        # job_id 用 SET NULL：即使任务记录被清理，问题的历史证据也要留存
        sa.ForeignKeyConstraint(["job_id"], ["crawl_jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_issues_site_id", "issues", ["site_id"])
    op.create_index("ix_issues_page_id", "issues", ["page_id"])
    op.create_index("ix_issues_job_id", "issues", ["job_id"])
    op.create_index("ix_issues_site_severity_code", "issues", ["site_id", "severity", "code"])
    op.create_index("ix_issues_site_fingerprint", "issues", ["site_id", "fingerprint"])
    op.create_index("ix_issues_site_status_severity", "issues", ["site_id", "status", "severity"])

    # ------------------------------------------------------------------
    # serp_snapshots
    # ------------------------------------------------------------------
    op.create_table(
        "serp_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("keyword_id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("market", MARKET, nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("features", JSONType, nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["keyword_id"], ["keywords.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # 同一次抓取里一个 URL 只占一个位置 → 重跑 SERP 抓取是幂等 upsert
        sa.UniqueConstraint("keyword_id", "captured_at", "url", name="uq_serp_kw_time_url"),
    )
    op.create_index("ix_serp_snapshots_site_id", "serp_snapshots", ["site_id"])
    op.create_index("ix_serp_keyword_captured", "serp_snapshots", ["keyword_id", "captured_at"])

    # ------------------------------------------------------------------
    # content_briefs
    # ------------------------------------------------------------------
    op.create_table(
        "content_briefs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("target_url", sa.Text(), nullable=False),
        sa.Column("keyword_id", sa.Integer(), nullable=True),
        sa.Column("market", MARKET, nullable=False),
        sa.Column("status", BRIEF_STATUS, nullable=False),
        sa.Column("title_candidates", JSONType, nullable=False),
        sa.Column("brief", JSONType, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["keyword_id"], ["keywords.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("target_url", "keyword_id", name="uq_brief_target_keyword"),
    )
    op.create_index("ix_content_briefs_site_id", "content_briefs", ["site_id"])
    op.create_index("ix_content_briefs_keyword_id", "content_briefs", ["keyword_id"])
    op.create_index("ix_briefs_site_status", "content_briefs", ["site_id", "status"])

    # ------------------------------------------------------------------
    # suggestions
    # ------------------------------------------------------------------
    op.create_table(
        "suggestions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("issue_id", sa.Integer(), nullable=True),
        sa.Column("type", SUGGESTION_TYPE, nullable=False),
        # before_text 必存：产品原则"可回滚"要求撤回时能还原现场
        sa.Column("before_text", sa.Text(), nullable=False),
        sa.Column("after_text", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("status", SUGGESTION_STATUS, nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["issue_id"], ["issues.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # 不单独给 site_id 建索引：ix_suggestions_site_url 与
    # ix_suggestions_site_type_status 都以 site_id 打头，已经覆盖了
    # "按站点取全部建议"这一查询，再加一个是纯粹的写放大。
    op.create_index("ix_suggestions_issue_id", "suggestions", ["issue_id"])
    op.create_index("ix_suggestions_site_url", "suggestions", ["site_id", "url"])
    op.create_index("ix_suggestions_site_type_status", "suggestions", ["site_id", "type", "status"])

    # ------------------------------------------------------------------
    # rank_history
    # ------------------------------------------------------------------
    op.create_table(
        "rank_history",
        # BigInteger：这张表按 站点×URL×天 增长，是全库最快的。
        # 32 位 int 在中等规模站点上就会溢出，所以必须是 64 位。
        #
        # with_variant 是必需的：SQLite 只有把主键列声明成 "INTEGER"（而不是
        # BIGINT）才会把它当作 rowid 的别名并自动赋值。写成裸 sa.BigInteger()
        # 时 SQLite 建出的是 BIGINT PRIMARY KEY，插入时不给 id 就直接报
        # "NOT NULL constraint failed" —— 而 create_all 走的是另一条渲染路径
        # （自动降级为 INTEGER），两者行为不一致，迁移建出来的库会比 ORM
        # 建出来的库少一个能用的主键。
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer, "sqlite"),
            nullable=False,
        ),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("keyword_id", sa.Integer(), nullable=True),
        # Date 而非 DateTime：数据源本身按天出数，且唯一键需要消除时区差异
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("position", sa.Float(), nullable=True),
        sa.Column("clicks", sa.Integer(), nullable=False),
        sa.Column("impressions", sa.Integer(), nullable=False),
        sa.Column("ctr", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["keyword_id"], ["keywords.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        # 需求硬约束：一页一天一条汇总记录
        sa.UniqueConstraint("site_id", "url", "date", name="uq_rank_site_url_date"),
    )
    op.create_index("ix_rank_site_date", "rank_history", ["site_id", "date"])
    op.create_index("ix_rank_site_keyword_date", "rank_history", ["site_id", "keyword_id", "date"])


def downgrade() -> None:
    # 反向顺序：先删引用方再删被引用方，否则 FK 约束会让 drop 失败。
    op.drop_index("ix_rank_site_keyword_date", table_name="rank_history")
    op.drop_index("ix_rank_site_date", table_name="rank_history")
    op.drop_table("rank_history")

    op.drop_index("ix_suggestions_site_type_status", table_name="suggestions")
    op.drop_index("ix_suggestions_site_url", table_name="suggestions")
    op.drop_index("ix_suggestions_issue_id", table_name="suggestions")
    op.drop_table("suggestions")

    op.drop_index("ix_briefs_site_status", table_name="content_briefs")
    op.drop_index("ix_content_briefs_keyword_id", table_name="content_briefs")
    op.drop_index("ix_content_briefs_site_id", table_name="content_briefs")
    op.drop_table("content_briefs")

    op.drop_index("ix_serp_keyword_captured", table_name="serp_snapshots")
    op.drop_index("ix_serp_snapshots_site_id", table_name="serp_snapshots")
    op.drop_table("serp_snapshots")

    op.drop_index("ix_issues_site_status_severity", table_name="issues")
    op.drop_index("ix_issues_site_fingerprint", table_name="issues")
    op.drop_index("ix_issues_site_severity_code", table_name="issues")
    op.drop_index("ix_issues_job_id", table_name="issues")
    op.drop_index("ix_issues_page_id", table_name="issues")
    op.drop_index("ix_issues_site_id", table_name="issues")
    op.drop_table("issues")

    op.drop_index("ix_keywords_site_cluster", table_name="keywords")
    op.drop_index("ix_keywords_site_intent", table_name="keywords")
    op.drop_index("ix_keywords_site_id", table_name="keywords")
    op.drop_table("keywords")

    op.drop_index("ix_pages_site_status", table_name="pages")
    op.drop_index("ix_pages_site_depth", table_name="pages")
    op.drop_index("ix_pages_site_content_hash", table_name="pages")
    op.drop_index("ix_pages_site_id", table_name="pages")
    op.drop_table("pages")

    op.drop_index("ix_crawl_jobs_site_status_started", table_name="crawl_jobs")
    op.drop_index("ix_crawl_jobs_site_id", table_name="crawl_jobs")
    op.drop_table("crawl_jobs")

    op.drop_table("sites")
