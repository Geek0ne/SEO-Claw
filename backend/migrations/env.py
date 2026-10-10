"""Alembic 运行环境。

两处刻意的设计：

1. **迁移跑同步 engine，应用跑 async engine，但 URL 必须同源。**
   `to_sync_url()` 负责把 `postgresql+asyncpg://` 换成同步驱动 ——
   Alembic 的 autogenerate 靠 DBAPI 反射 schema，asyncpg 驱动会让它
   直接挂在建连接上。绝不能在迁移里另配一个连接串（会漂移，且明文密码
   会进版本库）。

2. **metadata 从 `seoclaw.db.models` 导入，不重复定义。**
   迁移文件是"历史快照"（生成后不再随模型改动），但 env.py 不是：
   它必须永远指向当前模型，否则 autogenerate 出来的差异会骗人。
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# 让 `import seoclaw.db` 在任意 CWD 下都能工作（pytest 可能从仓库根启动）。
BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
for candidate in (BACKEND_ROOT, REPO_ROOT / ".deps"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from seoclaw.db.models import Base  # noqa: E402
from seoclaw.db.session import to_sync_url  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def get_url() -> str:
    """按 迁移专用环境变量 > 通用环境变量 > alembic.ini 的顺序取连接串。

    优先用 ``MIGRATION_DATABASE_URL``：迁移连的库有时和应用库不同
    （比如灰度分支用独立 schema），而 DATABASE_URL 会被容器平台占用。
    """
    return (
        os.getenv("MIGRATION_DATABASE_URL")
        or os.getenv("SEO_CLAW_DATABASE_URL")
        or os.getenv("SEO_AGENT_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or config.get_main_option("sqlalchemy.url")
        or "sqlite:///./seoclaw.db"
    )


def run_migrations_offline() -> None:
    """离线模式：只输出 SQL 脚本，不连库。

    用途是"把这个版本的 DDL 交给 DBA 手工在生产执行"或做变更评审。
    注意 offline 模式拿不到数据库实际状态，所以 literal_binds 打开后
    参数会被内联成字面量。
    """
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        # 迁移只建我们自己的表；不排除任何 schema。
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：连库执行。

    关键配置 ``compare_type=True``：SQLAlchemy 的类型变化（如
    String(255) → Text）在默认配置下检测不到，会漏生成 alter，
    直到某天插入超长数据才炸。
    """
    connectable = engine_from_config(
        {"sqlalchemy.url": to_sync_url(get_url())},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # 迁移是一次性任务，无需连接池复用
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
