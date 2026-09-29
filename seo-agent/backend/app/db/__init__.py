"""数据访问层。

对外只暴露三样东西：
  * ``models``   —— ORM 实体（Alembic autogenerate 的 metadata 根）
  * ``session``  —— 引擎 / 会话 / 事务边界
  * ``repository`` —— 仓储函数与 UnitOfWork 门面

上层不要直接 ``session.query()``：口径（分页、排序、状态过滤、fingerprint
归一化）必须只有一处实现，否则报告、看板、告警会各算各的。
"""

from . import models, repository, session
from .models import Base
from .repository import UnitOfWork, compute_fingerprint
from .session import get_engine, get_session, get_session_factory, session_scope

__all__ = [
    "models",
    "repository",
    "session",
    "Base",
    "UnitOfWork",
    "compute_fingerprint",
    "get_engine",
    "get_session",
    "get_session_factory",
    "session_scope",
]
