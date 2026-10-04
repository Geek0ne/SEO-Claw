"""crawl_jobs 补健康分与评分明细

Revision ID: 0002_job_scores
Revises: 0001_initial
Create Date: 2026-10-04

## 为什么需要这一版

`/sites/{id}/report` 的 `_latest_score()` 去读 `job.score_breakdown`，
但 crawl_jobs **压根没有这两列** → 属性不存在 → health_score 恒为 null
→ 前端按「一页都没抓到」渲染。

也就是说：**分数算了、接口也返回了，却从来没存下来。**
这比没实现更坏——接口看着是通的，只是答案恒为空。

## 为什么单独加列而不是每次重算

重算要拿当轮的全部 issue 重跑一遍评分，而 issue 表是**最新快照**：
上一轮的问题已经被这一轮覆盖掉了，算出来的不是那一轮的分数。
分数是历史事实，必须跟产生它的那次扫描一起存。
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_job_scores"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

# 与 models.JSONType 同构：PG 用 JSONB，其它方言退回通用 JSON。
JSONType = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column(
        "crawl_jobs",
        sa.Column("health_score", sa.Float(), nullable=True),
    )
    op.add_column(
        "crawl_jobs",
        sa.Column("score_breakdown", JSONType, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("crawl_jobs", "score_breakdown")
    op.drop_column("crawl_jobs", "health_score")
