"""清理历史重复 issue 行

Revision ID: 0004_dedupe_issues
Revises: 0003_usage_events
Create Date: 2026-10-04

## 为什么需要这一版

0003 之前的入库是无条件 INSERT，fingerprint 上也没有唯一约束，所以每
重扫一次就多一整套重复行。实跑站点实测 9~16 组，同一个问题在列表里出现
两次，而用户在一条上标了「已修」—— 因为重扫更新的是**另一行**。

0005 那笔修复了「不再产生新的重复」，并在扫描时合并遇到的旧重复；
但**没被这轮扫到的重复组仍留在原地**。本迁移做一次性收尾。

## 谁是正本

1. **带用户判断的行优先**（fixed / ignored / false_positive）。
   那是人下的结论，不能因为「它 id 更大/更小」就被删掉。
2. 全是 open 时取 id 最小的 —— 最老那条，身份稳定。

⚠️ 被删的都不是历史事实，而是 bug 造出来的重复。保留它们才是错的：
同一个问题在报告里出现两次，用户无法判断该修哪一个。

## 为什么在 Python 里写而不是一条 SQL

「优先留非 open 的那条」在 PG 能用 DISTINCT ON，SQLite 没有对应写法；
而本项目要求两个方言都能跑。逐组处理则两边行为一致。
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004_dedupe_issues"
down_revision = "0003_usage_events"
branch_labels = None
depends_on = None

# 这些状态都是「人下的结论」，合并时必须保留，不能被 open 行挤掉。
_VERDICTS = ("fixed", "ignored", "false_positive")


def upgrade() -> None:
    bind = op.get_bind()
    groups = bind.execute(
        sa.text(
            "SELECT site_id, fingerprint, COALESCE(url, '') AS u "
            "FROM issues GROUP BY site_id, fingerprint, COALESCE(url, '') "
            "HAVING COUNT(*) > 1"
        )
    ).fetchall()
    if not groups:
        print("[0004] 没有重复组，无需清理")
        return

    removed = 0
    for site_id, fp, url in groups:
        rows = bind.execute(
            sa.text(
                "SELECT id, status FROM issues "
                "WHERE site_id = :s AND fingerprint = :f "
                "AND COALESCE(url, '') = :u ORDER BY id"
            ),
            {"s": site_id, "f": fp, "u": url},
        ).fetchall()
        if len(rows) < 2:
            continue

        keeper = next(
            (iid for iid, st in rows if st in _VERDICTS),
            rows[0][0],  # 全是 open → 取最老那条
        )
        drop = [iid for iid, _ in rows if iid != keeper]
        if drop:
            bind.execute(
                sa.text(
                    "DELETE FROM issues WHERE id IN ("
                    + ",".join(str(int(i)) for i in drop)
                    + ")"
                )
            )
            removed += len(drop)
    print(f"[0004] 合并 {len(groups)} 组重复，删除 {removed} 行")


def downgrade() -> None:
    # 删除的重复行无法重建 —— 它们的正本都还在，信息不丢。
    print("[0004] 重复行已合并，downgrade 不重建（正本仍在，信息未丢）")
