"""扫描编排：把同步爬虫 + 异步落库接起来。

两处必须处理的不对称：

1. **Crawler 是同步的，db 层是异步的**。FastAPI 事件循环里直接调
   ``crawler.crawl()`` 会阻塞整个服务——一次扫描几十秒，期间所有请求
   都排队。所以同步抓取一律丢线程池（``asyncio.to_thread``）。

2. **ORM 字段名与应用层不同**（``meta_desc`` vs ``meta_description``、
   ``links_json`` vs ``links``）。映射集中在这里，不散落到路由里。
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Optional

from ..audit.engine import run_audit
from ..crawler import CrawlConfig, Crawler
from ..db import repository as repo
from ..db.models import JobStatus as DbJobStatus
from ..models import Issue, Market, Page
from ..report import render_markdown
from ..scoring import score


def _page_to_row(p: Page) -> dict[str, Any]:
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


def _issue_to_row(i: Issue, *, job_id: int, page_id: Optional[int] = None) -> dict[str, Any]:
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


def _issue_to_dict(i: Issue, affected: int = 1) -> dict[str, Any]:
    """给前端/CLI 用的紧凑问题视图。

    ⚠️ 不要把 evidence 原样塞进去：sitemap.missing 那条会把 5 个探测路径
    全列出来，单条就能撑爆一屏 JSON。证据在 HTML 报告里按需展开。
    """
    return {
        "code": i.code,
        "severity": i.severity.value,
        "market": i.market.value,
        "scope": i.scope.value,
        "title": i.title,
        "description": i.description,
        "fix_hint": i.fix_hint,
        "fix_example": i.fix_example,
        "url": i.url,
        "affected_pages": affected,
    }


def _group_issues(issues: list[Issue], cap: int = 200) -> list[dict[str, Any]]:
    """按 fingerprint 聚成行动项。

    一条 Issue 记录 = 一个受影响页面；同根因的 300 条不该在界面上占 300 行。
    数量记在 ``affected_pages`` 上——用户要回答的是「一共多少页受影响」，
    拿不到这个数字的列表没法当行动清单用。
    """
    by_fp: dict[str, list[Issue]] = {}
    for i in issues:
        key = i.evidence.get("fingerprint") or f"{i.code}|{i.url or ''}"
        by_fp.setdefault(key, []).append(i)
    out: list[dict[str, Any]] = []
    for group in list(by_fp.values())[:cap]:
        out.append(_issue_to_dict(group[0], affected=len(group)))
    return out


def _crawl_and_audit(
    url: str,
    *,
    max_pages: int,
    max_depth: int,
    per_domain_rps: float,
    markets: list[str],
    incremental: bool,
    checkpoint_dir: Optional[str],
    respect_robots: bool,
    render_js: bool,
) -> tuple[list[Page], dict[str, Any], float, int]:
    """同步部分：抓取 + 规则 + 评分。**只在这里用同步 API**，必须在线程池里跑。"""
    cfg = CrawlConfig(
        max_pages=max_pages,
        max_depth=max_depth,
        per_domain_rps=per_domain_rps,
        respect_robots=respect_robots,
        render_js=render_js,
    )
    from pathlib import Path

    ck = Path(checkpoint_dir) if checkpoint_dir else None
    started = time.monotonic()
    with Crawler(cfg, checkpoint_dir=ck) as crawler:
        crawler.incremental = incremental
        pages = crawler.crawl(url)
        discovered = getattr(crawler, "discovered_count", len(pages))

    from ..cli import _collect_site_facts

    with Crawler(cfg) as verifier:
        site_facts = _collect_site_facts(verifier)
    site_facts["discovered_count"] = discovered
    ok_pages = [p for p in pages if p.status_code == 200 and not p.error]
    site_facts["pages_ok"] = len(ok_pages)
    site_facts["pages_failed"] = len(pages) - len(ok_pages)

    domain = _domain_of(url)
    issues, _ctx = run_audit(
        pages, domain, [Market(m) for m in markets], site_facts, incremental=incremental
    )
    return pages, {"issues": issues, "site_facts": site_facts}, time.monotonic() - started, discovered


def _domain_of(url: str) -> str:
    from urllib.parse import urlparse

    d = urlparse(url).netloc
    return d[4:] if d.startswith("www.") else d


async def run_scan(
    session: Any,
    *,
    site_id: int,
    url: str,
    markets: list[str],
    max_pages: int = 100,
    max_depth: int = 6,
    per_domain_rps: float = 3.0,
    incremental: bool = False,
    checkpoint_dir: Optional[str] = None,
    respect_robots: bool = True,
    render_js: bool = False,
) -> dict[str, Any]:
    """跑一次扫描并落库。返回本次 job 的汇总。"""
    job = await repo.create_crawl_job(session, site_id)
    await repo.finish_job(session, job.id, status=DbJobStatus.RUNNING)

    try:
        pages, audit, elapsed, discovered = await asyncio.to_thread(
            _crawl_and_audit,
            url,
            max_pages=max_pages,
            max_depth=max_depth,
            per_domain_rps=per_domain_rps,
            markets=markets,
            incremental=incremental,
            checkpoint_dir=checkpoint_dir,
            respect_robots=respect_robots,
            render_js=render_js,
        )

        issues = audit["issues"]
        site_facts = audit["site_facts"]
        ok_pages = [p for p in pages if p.status_code == 200 and not p.error]
        health, breakdown = score(issues, len(ok_pages), domain=_domain_of(url))

        # 页面按 url 建索引，落 issue 时回填 page_id（不必逐条再查库）
        page_ids: dict[str, int] = {}
        for p in pages:
            row = await repo.upsert_page(
                session, site_id, p.url, **_page_to_row(p)
            )
            page_ids[p.url] = row.page.id

        # ⚠️ 必须走 sync 而不是 save_issues：后者是无条件 INSERT，
        # 同一个站每重扫一次就多一整套重复行（实测 site1：job1=7 行 → job2=36 行），
        # 且用户标过「已修」的行原样留着 —— 「已修」按钮等于只能用一次。
        _sync_stats = await repo.sync_issues_for_scan(
            session,
            site_id,
            job_id=job.id,
            issues=(
                _issue_to_row(i, job_id=job.id, page_id=page_ids.get(i.url or ""))
                for i in issues
            ),
            # 本轮**真正重新检查过**的页面集合。同步入库据此判断「旧问题
            # 是不是真消失了」。
            #
            # ⚠️ 必须排除 not_modified 页 —— 这是我自己埋的雷：
            # 增量扫描里服务器回 304 的页**不重跑规则**（见 audit/engine
            # 的 _skip_page_rules），所以这轮扫不出它上面的任何问题。但
            # 它 status_code 仍是 200，照样落进 ok_pages。若把它算进范围，
            # sync_for_scan 会认为「本轮扫过且没问题」→ 自动标成已修好。
            # 用户根本没改任何东西，一开增量扫描就凭空「修好」一大批问题 ——
            # 这正是我在仓库注释里说过「绝不谎报」的那件事。
            scoped_urls={p.url for p in ok_pages if not p.not_modified},
        )
        # ⚠️ 这个文件没有 logger（我第一版写了这行，实跑才发现是 NameError，
        # 白等一次端到端）。同步统计目前只在排障时手工看，所以直接丢弃；
        # 真要长期观测就先把 logger 引进这个模块，别在调用点现编一个。
        _sync_stats

        # ⚠️ 分数必须**跟着这一轮扫描**存进 crawl_jobs。issues 表是最新快照
        # ——上一轮的问题已被这一轮覆盖，事后再拿 issues 重算，算出来的
        # 不是那一轮的分数。分数是历史事实，要跟产生它的那次 job 一起存。
        await repo.finish_job(
            session,
            job.id,
            status=DbJobStatus.SUCCEEDED,
            url_count=discovered,
            pages_crawled=len(ok_pages),
            health_score=health,
            score_breakdown=breakdown,
        )
        return {
            "job_id": job.id,
            "domain": _domain_of(url),
            "pages_crawled": len(ok_pages),
            "pages_discovered": discovered,
            "duration_seconds": round(elapsed, 1),
            "health_score": health,
            "score_breakdown": breakdown,
            "issue_count": len(issues),
            # ⚠️ 界面的问题列表全靠这个字段。以前这里只回 issue_count，
            # 前端去读 rep.issues 永远是 undefined —— 页面显示一个分数，
            # 下面列表永远空白，看着像「没问题」。这个字段不能省。
            "issues": _group_issues(issues),
            "top_actions": [i.code for i in _prioritize(issues, len(ok_pages))],
            "site_facts": site_facts,
        }
    except Exception as exc:  # noqa: BLE001 — job 状态必须落 failed，否则永远卡在 running
        await repo.finish_job(session, job.id, status=DbJobStatus.FAILED, error=str(exc)[:500])
        raise


def _prioritize(issues: list[Issue], total_pages: int) -> list[Issue]:
    from ..scoring import prioritize

    return prioritize(issues, total_pages)