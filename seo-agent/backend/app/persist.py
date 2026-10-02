"""扫描结果落库：CLI 与 API 共用。

## 为什么要单独抽一层

实测发现（2026-10-02）：``app/cli.py`` 里落库调用 **0 处**，
而 ``app/api/scan_service.py`` 有 6 处。也就是说 **9 张表建好了、
Alembic 迁移也齐了，但 CLI 这条最常用的入口一次都没往库里写过**——
107 站校准期间跑的扫描，报告落成文件就散了；``rank_history`` 与
``keywords`` 两张表至今没有任何写入方。

修的时候不能简单地在 cli.py 里 ``from .api.scan_service import ...``：
``app/api/__init__.py`` 会 ``from .routes import router``，而 routes 依赖
FastAPI —— 那一行 import 会把 FastAPI 变成 CLI 的硬依赖。CLI 刻意不依赖
Web 层，所以映射逻辑落在这一层，两边各自 import。

## 写入顺序

1. ``create_crawl_job`` 登记 PENDING（先落库再干活：进程崩了也留得下痕迹）
2. 页面按 url upsert，同时攒 url → page_id 索引
3. ``save_issues`` 一次批量写，带 job_id 与 page_id
4. ``finish_job`` 写终态 + 计数

⚠️ **page_id 回填靠第 2 步的索引**，不逐条再查库：issue 数量常是页数的
数倍，逐条查会让落库时间被 N+1 拖垮。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlsplit

from .db import repository as repo
from .db.models import JobStatus
from .db.repository import SiteRepository
from .models import Issue, Page


def domain_of(url: str) -> str:
    """从 URL 取 host（去掉 www. 前缀由仓储内部归一）。"""
    return urlsplit(url).netloc


def page_to_row(p: Page) -> dict[str, Any]:
    """应用层 Page → ORM ``pages`` 表字段。

    ⚠️ 字段名刻意不与模型同名（``meta_desc`` / ``links_json``）：那是 ORM
    建表时就定下的，改名要配迁移，而这里只是写入侧映射。
    """
    return {
        "final_url": p.final_url,
        "status_code": p.status_code,
        "content_type": p.content_type,
        "depth": p.depth,
        "discovered_from": p.discovered_from,
        "title": p.title,
        "meta_desc": p.meta_description,
        "canonical": p.canonical,
        "robots_meta": p.robots_meta,
        # ⚠️ ORM 的 h1 是 Text 列（单个字符串），不是 JSON 列。
        # 直接塞 list 会在 flush 时报
        # `sqlite3.ProgrammingError: type 'list' is not supported`，
        # 而且报错被 PendingRollbackError 包一层，看起来像「会话坏了」，
        # 真实原因藏在 "Original exception was" 那行里。用换行分隔。
        "h1": "\n".join(p.h1) if p.h1 else None,
        "text": p.text,
        "word_count": p.word_count,
        "content_hash": p.content_hash,
        # links_json 是 JSON 列，但声明类型是 dict（default=dict）。
        # 包一层 {"links": [...]}：既能原样读回，也不改变列的既有语义。
        "links_json": {"links": [lk.model_dump(mode="json") for lk in p.links]},
        "error": p.error,
        "fetched_at": p.fetched_at or datetime.now(timezone.utc),
    }


def issue_to_row(i: Issue, *, job_id: int, page_id: Optional[int] = None) -> dict[str, Any]:
    return {
        "code": i.code,
        "severity": i.severity.value,
        "market": i.market.value,
        "scope": i.scope.value,
        "url": i.url,
        "page_id": page_id,
        "job_id": job_id,
        "title": i.title,
        "description": i.description,
        "fix_hint": i.fix_hint,
        "fix_example": i.fix_example,
        "evidence": i.evidence,
    }


async def get_or_create_site(
    session, url: str, *, markets: Optional[list[str]] = None
) -> int:
    """按域名找站点，没有就建。返回 site_id。

    ⚠️ CLI 场景下站点多半不存在（用户敲一条命令就扫一个站），
    但重复扫同一个站必须复用同一条记录 —— 否则 pages/issues 外键全断，
    而且 rank_history 会按不同 site_id 分裂成互不相干的几条历史。
    """
    domain = domain_of(url)
    repo_site = SiteRepository(session)
    site = await repo_site.get_by_domain(domain)
    if site is None:
        site = await repo_site.create(domain, markets=markets or ["base"])
    return site.id


async def persist_scan(
    session,
    *,
    site_id: int,
    pages: list[Page],
    issues: list[Issue],
    url_count: int = 0,
    elapsed: float = 0.0,  # 目前不落库：crawl_jobs 无该列，见下方 finish_job 注释
) -> dict[str, Any]:
    """把一次扫描结果写进库。返回 ``{job_id, pages_written, issues_written}``。

    调用方负责开/关事务（``session_scope`` 或 ``UnitOfWork``）。
    """
    job = await repo.create_crawl_job(session, site_id)
    await repo.finish_job(session, job.id, status=JobStatus.RUNNING)

    # 页面按 url 建索引，落 issue 时回填 page_id（不必逐条再查库）
    page_ids: dict[str, int] = {}
    for p in pages:
        row = await repo.upsert_page(session, site_id, p.url, **page_to_row(p))
        page_ids[p.url] = row.page.id

    saved = await repo.save_issues(
        session,
        site_id,
        (issue_to_row(i, job_id=job.id, page_id=page_ids.get(i.url or "")) for i in issues),
    )

    ok_pages = sum(1 for p in pages if p.status_code == 200 and not p.error)
    # ⚠️ crawl_jobs 表**没有** elapsed_seconds 列（只有 url_count /
    # pages_crawled / error / started_at / finished_at）。我第一版写了
    # `elapsed_seconds=`，而 ORM 的 finish 会把它当列名 → 运行即 TypeError。
    # 耗时改由 finished_at - started_at 表达，不另存冗余列。
    await repo.finish_job(
        session,
        job.id,
        status=JobStatus.SUCCEEDED,
        url_count=url_count,
        pages_crawled=ok_pages,
    )
    return {
        "job_id": job.id,
        "site_id": site_id,
        "pages_written": len(pages),
        "issues_written": len(saved),
        "pages_ok": ok_pages,
    }


__all__ = [
    "domain_of",
    "page_to_row",
    "issue_to_row",
    "get_or_create_site",
    "persist_scan",
]