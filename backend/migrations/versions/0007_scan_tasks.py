"""scan_tasks 表 —— Web 体检任务的持久队列

Revision ID: 0007_scan_tasks
Revises: 0006_api_keys_and_site_verification
Create Date: 2026-10-18

## 为什么需要这一版

任务状态此前活在 ``web/__init__.py`` 的进程内存里（``_TASKS`` 字典 +
``_INFLIGHT`` 计数）：进程一重启任务全丢、多 worker 互相看不见、
被杀的进程留下永远 running 的僵局。商业化上多 worker 部署是必须的，
先把「用户提交的活儿」落库，队列、恢复、并发计数全都有了落脚点。

## ⚠️ SQLite 三个坑（0001/0003/0005 踩过、0006 总结过，继续避开）

- ``sa.func.now()`` 而非 ``sa.text("now()")``
- ``sa.Integer()`` 主键而非裸 ``sa.BigInteger()``
- 新增 NOT NULL 列带 server_default

CHECK 约束跟随 enum_column 的口径：状态是 VARCHAR + CHECK，
不做原生 ENUM（schema 演进会被锁死）。
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0007_scan_tasks"
down_revision = "0006_api_keys_and_site_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scan_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "site_id",
            sa.Integer(),
            sa.ForeignKey("sites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("markets", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("max_pages", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("max_depth", sa.Integer(), nullable=False, server_default="6"),
        sa.Column(
            "respect_robots", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("render_js", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'done', 'failed')",
            name="ck_scan_tasks_status",
        ),
    )
    op.create_index(
        "ix_scan_tasks_status_created", "scan_tasks", ["status", "created_at"]
    )
    op.create_index("ix_scan_tasks_site_id", "scan_tasks", ["site_id"])


def downgrade() -> None:
    op.drop_index("ix_scan_tasks_site_id", table_name="scan_tasks")
    op.drop_index("ix_scan_tasks_status_created", table_name="scan_tasks")
    op.drop_table("scan_tasks")
