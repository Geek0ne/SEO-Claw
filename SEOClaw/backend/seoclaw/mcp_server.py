"""MCP Server：让 AI 助手直接调 SEOClaw 的审计能力。

⚠️ 两处踩过的坑，都钉在代码里：

1. 装到的是 **mcp 2.x**，`FastMCP` 已改名 `MCPServer`
   （``from mcp.server.fastmcp import FastMCP`` 直接 ModuleNotFoundError）。
   不查版本照老教程写，写出来就是跑不起来。
2. 报告装配复用 :mod:`seoclaw.api.summary`，**不另写一份**。MCP 拿到的
   报告必须和网页上那份逐字段一致 —— 不一致的话模型给的建议会和用户
   看到的对不上，而用户没理由知道该信哪个。

## 工具为什么只有三个，且没有一个能写

MCP Server 把工具交给模型自主调用，所以**工具集本身就是权限边界**。
加一个能写库的工具，等于把写权限交给任何能影响提示词的地方。
「少而正」比「多而全」有用得多，也安全得多。
"""

from __future__ import annotations

from typing import Any

try:  # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer
except ModuleNotFoundError as exc:  # pragma: no cover - 环境问题
    raise ModuleNotFoundError(
        "需要 mcp>=2.0（FastMCP 已改名 MCPServer）。"
        "安装：pip install --target ./.deps 'mcp>=2'"
    ) from exc

from .api.summary import build_summary
from .db.repository import SiteRepository
from .db.session import get_session_factory


def build_server() -> "MCPServer":
    """构造 MCP Server（不启动）。测试靠它拿工具列表，无需起进程。"""
    server = MCPServer(
        name="seoclaw",
        instructions=(
            "SEO 站点审计工具。典型用法：seo_list_sites 拿到已接入的站点，"
            "再 seo_get_report 读它的最新体检报告与问题清单。"
            "只有要现扫一个没接入的站时才用 seo_audit_url —— 它会真的去抓网页。"
        ),
    )

    @server.tool()
    async def seo_list_sites() -> list[dict[str, Any]]:
        """列出所有已接入的站点。

        ⚠️ 空数组是合法结论（「还没接入任何站点」），不是出错。
        """
        async with get_session_factory()() as session:
            page = await SiteRepository(session).list(limit=200)
            return [
                {
                    "id": s.id,
                    "domain": s.domain,
                    "markets": list(s.markets or []),
                    "is_active": bool(s.is_active),
                }
                for s in page.items
            ]

    @server.tool()
    async def seo_get_report(domain: str) -> dict[str, Any]:
        """读某站点最新一轮的体检报告（健康分 + 问题清单）。

        ⚠️ 站点不存在或没扫过时**明确说清是哪种**，不返回空壳让调用方猜。
        """
        async with get_session_factory()() as session:
            site = await SiteRepository(session).get_by_domain(domain)
            if site is None:
                return {
                    "ok": False,
                    "reason": "not_found",
                    "detail": f"没有接入的站点：{domain}",
                }
            summary = await build_summary(_uow(session), site.id)
            return {"ok": True, **summary}

    @server.tool()
    async def seo_audit_url(url: str, max_pages: int = 20) -> dict[str, Any]:
        """现扫一个站点并返回报告。⚠️ **会真的去抓网页，比较慢。**

        默认只抓 20 页、硬上限 200：这个工具最大的风险不是慢，是**在一个
        明显很大的站上跑满几百页**，把服务端和目标站一起拖垮。

        失败时返回 ``ok=False`` 并带原因，**不抛异常** —— 模型拿到异常通常
        只会重试，而重试一个必然失败的调用只是加倍伤害。
        """
        from .api.scan_service import run_scan

        max_pages = max(1, min(int(max_pages), 200))
        try:
            async with get_session_factory()() as session:
                repo = SiteRepository(session)
                site = await repo.get_by_domain(url)
                if site is None:
                    site = await repo.create(domain=url, markets=["base"])
                await run_scan(
                    session,
                    site_id=site.id,
                    url=url,
                    markets=["base"],
                    max_pages=max_pages,
                )
                summary = await build_summary(_uow(session), site.id)
                return {"ok": True, **summary}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "reason": type(exc).__name__, "detail": str(exc)[:500]}

    return server


def _uow(session):
    """把裸 session 包成 UnitOfWork —— build_summary 只认 uow。

    ⚠️ 这层包装是为了让 summary 不依赖「谁在调它」：HTTP 那边 uow 由
    FastAPI 依赖注入，MCP 这边自己造。两边拿到的是同一个 uow 门面，
    所以仓储方法只有一份实现。
    """
    from .db.repository import UnitOfWork

    return UnitOfWork(session)


def main() -> None:  # pragma: no cover - 进程入口
    build_server().run()


if __name__ == "__main__":  # pragma: no cover
    main()
