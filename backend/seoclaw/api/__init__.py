"""API 层：站点管理 / 扫描触发 / 报告查询 / 质量与验证。

⚠️ 路由分两块挂载，**都要挂**：``routes`` 是业务路由，``quality`` 是
只读的元信息路由（关于这个工具本身的验证资产）。两块都注册在
``/api/v1`` 前缀下——界面上所有路径同源，不存在「一个前缀两种写法」。
"""

from .quality import router as quality_router
from .routes import router

__all__ = ["router", "quality_router"]
