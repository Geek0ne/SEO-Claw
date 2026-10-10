"""新增 usage_events（计量事件表）

Revision ID: 0003_usage_events
Revises: 0002_job_scores
Create Date: 2026-10-04

## 为什么需要这一版

计费与额度里，唯一不依赖「定价方案」的那半是**计量**。而计量数字不能
就地累加在站点行上：任何一次重试或回滚都会让数字对不上，事后也无法自证。
追加写可以随时 SUM() 重算，也能回答「上个月到底跑了多少」——
**计费的数字必须能被复算**。

## 两处刻意为之

1. **唯一约束 (kind, ref_id) 是幂等键。** 任务完成后的投递会重试，
   没有它就重复计量 —— 重复计量比漏计量严重得多：用户要为没花过的额度买单。

2. **``at`` 用 ``sa.func.now()`` 而不是 ``sa.text("now()")``。**
   SQLite 没有 now() 函数，写成字符串会建出一个**插入即报
   OperationalError** 的表 —— 而那正是本项目 0001 迁移踩过的坑，
   当时是逐条 insert 验证出来的，不是看 diff 文本。
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_usage_events"
down_revision = "0002_job_scores"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usage_events",
        sa.Column("id", sa.Integer(), nullable=False),
        # ⚠️ 用 sa.Integer() 而不是裸 sa.BigInteger()：SQLite 只把
        # INTEGER PRIMARY KEY 当 rowid 别名，写 BIGINT 会建出插入即报
        # NOT NULL constraint failed 的表（0001 踩过）。
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("ref_id", sa.String(length=64), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("kind", "ref_id", name="uq_usage_kind_ref"),
    )
    op.create_index("ix_usage_site_at", "usage_events", ["site_id", "at"])
    op.create_index("ix_usage_events_site_id", "usage_events", ["site_id"])


def downgrade() -> None:
    op.drop_index("ix_usage_events_site_id", table_name="usage_events")
    op.drop_index("ix_usage_site_at", table_name="usage_events")
    op.drop_table("usage_events")
