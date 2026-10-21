"""sites 表：托管定时复扫三列

Revision ID: 0008_site_scan_schedule
Revises: 0007_scan_tasks
Create Date: 2026-10-20

## 为什么需要这一版（改造阶段 2b：定时扫描调度）

阶段 2a 把「用户提交的体检」落成了持久队列（scan_tasks），但**复扫**还是
一锤子买卖：用户想「每周看一次这个站」，只能每周自己来点一次。托管
定时复扫补的就是这件事——站点声明一个间隔，调度器到期自动入队。

## 三列的分工

- ``scan_interval_s``：复扫间隔（秒）。NULL = 未开启托管。
- ``next_scan_at``：下次到期时间。**调度器只认这一列**——到期就入队，
  然后把这一列推到下个周期。认领是 CAS（WHERE next_scan_at <= now），
  多进程下同站点只会有一个调度实例抢到。
- ``schedule_params``：执行参数快照（url/markets/max_pages/…）。定格在
  开启托管的那一刻，不实时读站点设置——「当初约好的复扫」不该随后续
  改动漂移。

## ⚠️ SQLite 三个坑（0001/0003/0005 踩过、0006/0007 总结过，继续避开）

- ``sa.func.now()`` 而非 ``sa.text("now()")``
- ``sa.Integer()`` 主键而非裸 ``sa.BigInteger()``
- 新增 NOT NULL 列带 server_default —— 本次三列全是 nullable，
  不需要 server_default（模型侧也不写，两边才不会漂移）。
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0008_site_scan_schedule"
down_revision = "0007_scan_tasks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sites", sa.Column("scan_interval_s", sa.Integer(), nullable=True))
    op.add_column(
        "sites", sa.Column("next_scan_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("sites", sa.Column("schedule_params", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("sites", "schedule_params")
    op.drop_column("sites", "next_scan_at")
    op.drop_column("sites", "scan_interval_s")
