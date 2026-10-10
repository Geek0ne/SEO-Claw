"""api_keys 表 + sites 补归属与验证字段

Revision ID: 0006_api_keys_and_site_verification
Revises: 0005_rank_alert_acks
Create Date: 2026-10-05

## 为什么需要这一版

产品定的方向：**每个用户一把钥匙管理自己的站点**。但「一把钥匙」只解决了
「你是谁」，没解决「这个站凭什么算你的」——后者要靠归属验证。

三处刻意为之：

1. **api_keys 只存 sha256，不存明文。** 库被拖走时攻击者拿到的仍只是
   哈希。明文只在创建那一刻返回一次，丢了只能重发不能找回——这是有意的
   代价：存明文的话一次 SQL 注入就交出所有租户的钥匙。

2. **撤销而非删除。** 删了 key，历史计量就找不到归属了。

3. **sites.owner 默认 "local"。** 自部署单机没有租户概念，把所有老数据
   一次性归到 local，鉴权层也因此能在未开鉴权时直接放行——不需要为
   「单机模式」写第二套数据。

## ⚠️ SQLite 三个坑（0001/0003/0005 都踩过，这次直接避开）

- ``sa.func.now()`` 而非 ``sa.text("now()")``：SQLite 没有 now() 函数，
  写成字符串会建出插入即报 OperationalError 的表。
- ``sa.Integer()`` 而非裸 ``sa.BigInteger()``：SQLite 只把
  INTEGER PRIMARY KEY 当 rowid 别名。
- 新增 NOT NULL 列必须带 server_default：ALTER TABLE ADD COLUMN
  在有数据的表上不加默认值会直接失败。
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0006_api_keys_and_site_verification"
down_revision = "0005_rank_alert_acks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("key_prefix", sa.String(length=16), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash", name="uq_api_key_hash"),
    )
    op.create_index("ix_api_key_owner", "api_keys", ["owner"])

    # ⚠️ 全部带 server_default：有数据的表上 ADD COLUMN NOT NULL 不给默认值
    # 会直接失败。
    op.add_column("sites",
        sa.Column("owner", sa.String(length=64), nullable=False,
                  server_default="local"))
    op.add_column("sites", sa.Column("verify_token", sa.String(length=64), nullable=True))
    op.add_column("sites",
        sa.Column("verify_status", sa.String(length=16), nullable=False,
                  server_default="unverified"))
    op.add_column("sites", sa.Column("verify_method", sa.String(length=16), nullable=True))
    op.add_column("sites", sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_sites_owner", "sites", ["owner"])


def downgrade() -> None:
    op.drop_index("ix_sites_owner", table_name="sites")
    op.drop_column("sites", "verified_at")
    op.drop_column("sites", "verify_method")
    op.drop_column("sites", "verify_status")
    op.drop_column("sites", "verify_token")
    op.drop_column("sites", "owner")
    op.drop_index("ix_api_key_owner", table_name="api_keys")
    op.drop_table("api_keys")
