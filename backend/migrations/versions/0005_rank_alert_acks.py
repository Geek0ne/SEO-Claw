"""新增 rank_alert_acks（排名告警的「已看过」标记）

Revision ID: 0005_rank_alert_acks
Revises: 0004_dedupe_issues
Create Date: 2026-10-04

## 为什么需要这一版

31fb7bb 加的告警能算出「哪些 URL 跌了」，但**没有「已看过」的概念** ——
同一场跌落（同一 URL、同一对起止日）在往后每一次查询里都会被重新算出来、
重新报一次。而告警一多就不叫告警了：用户会开始整体忽略，于是真正该看的
那次也一起被忽略。

## 「已看过」必须由用户动作驱动

不能查询时顺手自动标记：自动标记意味着「我算了但没人看」也算看过，
那这声告警等于没发过。所以这是一张只由显式 ack 写入的表。
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0005_rank_alert_acks"
down_revision = "0004_dedupe_issues"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rank_alert_acks",
        # ⚠️ sa.Integer() 而非裸 sa.BigInteger()：SQLite 只把
        # INTEGER PRIMARY KEY 当 rowid 别名（0001 踩过）。
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("alert_key", sa.String(length=200), nullable=False),
        # ⚠️ sa.func.now() 而非 sa.text("now()")：SQLite 没有 now() 函数，
        # 写成字符串会建出插入即报 OperationalError 的表（0001 也踩过）。
        sa.Column(
            "acked_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("site_id", "alert_key", name="uq_alert_ack"),
    )
    op.create_index("ix_alert_ack_site", "rank_alert_acks", ["site_id"])
    op.create_index("ix_rank_alert_acks_site_id", "rank_alert_acks", ["site_id"])


def downgrade() -> None:
    op.drop_index("ix_rank_alert_acks_site_id", table_name="rank_alert_acks")
    op.drop_index("ix_alert_ack_site", table_name="rank_alert_acks")
    op.drop_table("rank_alert_acks")
