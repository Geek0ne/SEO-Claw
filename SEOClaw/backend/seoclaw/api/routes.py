"""HTTP 路由：站点管理 / 扫描触发 / 报告查询三类。

⚠️ 同步爬虫不能直接在协程里跑 —— `run_scan` 内部用 `asyncio.to_thread`
丢到线程池，事件循环才不会被一次几十秒的扫描堵死。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..db import models as m
from .deps import get_uow
from .schemas import (
    IssueBulkStatusIn,
    IssueOut,
    IssuePage,
    IssueStatusIn,
    JobOut,
    ReportSummary,
    ScanRequest,
    BriefIn,
    BriefOut,
    KeywordExpandIn,
    KeywordExpandOut,
    KeywordOut,
    KeywordPage,
    RankAlertOut,
    RankDropRequest,
    ScorePoint,
    ScoreTrend,
    SummaryOut,
    UsageOut,
    SiteCreate,
    SiteOut,
)
from .scan_service import run_scan

router = APIRouter(prefix="/api/v1")


@router.get("/health")
def health() -> dict:
    """健康检查。

    ⚠️ 顺带报告**进程起点**与**代码文件最后修改时间**，并在两者矛盾时
    明确标 ``stale: true``。

    为什么加这个：我今天被同一个坑绊了两次（16:28、22:31）—— 改完代码
    去验，接口 404，第一反应是「代码写错了」，实际是**服务加载的是旧
    进程**。`{"ok": true}` 对这种状态完全沉默：它说服务活着，而活着的是
    三小时前的版本。

    这个坑之所以反复咬人，是因为它**伪装成别的 bug** —— 404 长得就像
    「路由没注册」。让 health 自己说出「我加载的代码比磁盘旧」，下次
    一次就能定位。

    ⚠️ 局限：只看本文件 mtime。改别的模块（schemas/仓库层）不会被标出来
    —— 要彻底解决得比 git HEAD，那是另一件事，不假装做了。
    """
    return {
        "ok": True,
        "process_started_at": _PROCESS_STARTED_AT,
        "code_modified_at": _CODE_MTIME,
        "stale": bool(_CODE_MTIME and _CODE_MTIME > _PROCESS_STARTED_AT),
    }


_PROCESS_STARTED_AT = time.time()
_CODE_MTIME = (
    Path(__file__).stat().st_mtime if Path(__file__).exists() else None
)


# --------------------------------------------------------------------------
# 站点管理
# --------------------------------------------------------------------------


@router.post("/sites", response_model=SiteOut, status_code=201)
async def create_site(body: SiteCreate, uow=__import__("fastapi").Depends(get_uow)) -> SiteOut:
    existing = await uow.sites.get_by_domain(body.domain)
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"站点已存在：{body.domain}")
    site = await uow.sites.create(body.domain, markets=body.markets)
    return SiteOut(
        id=site.id,
        domain=site.domain,
        markets=list(site.markets or []),
        is_active=site.is_active,
    )


@router.get("/sites", response_model=list[SiteOut])
async def list_sites(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    uow=__import__("fastapi").Depends(get_uow),
) -> list[SiteOut]:
    page = await uow.sites.list(limit=limit, offset=offset)
    return [
        SiteOut(
            id=s.id, domain=s.domain, markets=list(s.markets or []), is_active=s.is_active
        )
        for s in page.items
    ]


def _issue_out(i: m.Issue) -> IssueOut:
    """Issue → 出参。

    ⚠️ 抽出来是因为这段构造在 list_issues / update_issue_status 两处各写了一遍。
    以后给 IssueOut 加字段，漏改一处就会出现「列表里没有、详情里有」。
    """
    return IssueOut(
        id=i.id,
        code=i.code,
        severity=i.severity.value,
        scope=i.scope.value,
        url=i.url,
        title=i.title,
        fingerprint=i.fingerprint,
        status=i.status.value,
        occurrences=i.occurrences or 1,
    )


async def _require_site(uow, site_id: int) -> m.Site:
    site = await uow.sites.get(site_id)
    if site is None:
        raise HTTPException(status_code=404, detail=f"站点不存在：{site_id}")
    return site


@router.get("/sites/{site_id}", response_model=SiteOut)
async def get_site(site_id: int, uow=__import__("fastapi").Depends(get_uow)) -> SiteOut:
    site = await _require_site(uow, site_id)
    return SiteOut(
        id=site.id, domain=site.domain, markets=list(site.markets or []), is_active=site.is_active
    )


# --------------------------------------------------------------------------
# 扫描
# --------------------------------------------------------------------------


@router.post("/sites/{site_id}/scan", response_model=dict, status_code=201)
async def scan(site_id: int, body: ScanRequest, uow=__import__("fastapi").Depends(get_uow)) -> dict:
    site = await _require_site(uow, site_id)
    url = body.url or f"https://{site.domain}"
    markets = body.markets or list(site.markets or ["base"])
    # ⚠️ 开了增量却没给 checkpoint_dir → prior 为空 → 一个条件请求都不发，
    # 静默退化成全量扫描。CLI 那边有告警，API 这边原本没有：
    # 用户从接口看不出这次「增量」其实是全量，会误以为已经省钱。
    if body.incremental and not body.checkpoint_dir:
        raise HTTPException(
            status_code=400,
            detail="incremental=true 需要同时提供 checkpoint_dir（上一轮快照所在目录）。"
            "没有基准时不会发出任何条件请求，只会退化成一次全量扫描。",
        )
    summary = await run_scan(
        uow.session,
        site_id=site_id,
        url=url,
        markets=markets,
        max_pages=body.max_pages,
        max_depth=body.max_depth,
        per_domain_rps=body.per_domain_rps,
        incremental=body.incremental,
        checkpoint_dir=body.checkpoint_dir,
        respect_robots=body.respect_robots,
        render_js=body.render_js,
    )
    return summary


@router.get("/sites/{site_id}/jobs", response_model=list[JobOut])
async def list_jobs(
    site_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    uow=__import__("fastapi").Depends(get_uow),
) -> list[JobOut]:
    await _require_site(uow, site_id)
    page = await uow.jobs.list_for_site(site_id, limit=limit)
    return [
        JobOut(
            id=j.id,
            site_id=j.site_id,
            status=j.status.value,
            url_count=j.url_count,
            pages_crawled=j.pages_crawled,
            error=j.error,
            started_at=j.started_at,
            finished_at=j.finished_at,
        )
        for j in page.items
    ]


# --------------------------------------------------------------------------
# 报告
# --------------------------------------------------------------------------


@router.get("/sites/{site_id}/issues", response_model=IssuePage)
async def list_issues(
    site_id: int,
    severity: Optional[str] = None,
    code: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    uow=__import__("fastapi").Depends(get_uow),
) -> IssuePage:
    await _require_site(uow, site_id)
    page = await uow.issues.list(
        site_id,
        severity=severity,
        code=code,
        limit=limit,
        offset=offset,
    )
    return IssuePage(
        total=page.total,
        items=[
            IssueOut(
                id=i.id,
                code=i.code,
                severity=i.severity.value,
                scope=i.scope.value,
                url=i.url,
                title=i.title,
                fingerprint=i.fingerprint,
                status=i.status.value,
                occurrences=i.occurrences or 1,
            )
            for i in page.items
        ],
        has_next=offset + len(page.items) < page.total,
    )


@router.patch("/sites/{site_id}/issues/{issue_id}", response_model=IssueOut)
async def update_issue_status(
    site_id: int,
    issue_id: int,
    body: IssueStatusIn,
    uow=__import__("fastapi").Depends(get_uow),
) -> IssueOut:
    """把一条问题标成「已修 / 已知悉 / 忽略」。

    没有这条，这个产品就只是个只读报告：扫出一百条，用户改完了
    系统却永远显示那一百条还在——扫完就没有闭环了。

    ⚠️ **必须校验归属**：站点是租户边界。不校验的话
    ``PATCH /sites/1/issues/9999`` 会把 2 号站点的问题改掉，
    而调用方拿到的是 200 —— 越界写入比 404 难查得多。
    """
    await _require_site(uow, site_id)
    issue = await uow.issues.get(issue_id)
    if issue is None or issue.site_id != site_id:
        # 归属不对也说 404：说「那条存在但不属于你」等于泄露了别的站点
        # 有什么问题，而用户压根没有查询别人的资格。
        raise HTTPException(status_code=404, detail=f"问题不存在：{issue_id}")
    # ⚠️ 必须转成枚举再赋值。Literal 校验出来的是 str，而列的类型是
    # IssueStatus：塞 str 不会立刻报错，只在出参时炸
    # `AttributeError: 'str' object has no attribute 'value'`。
    # 这类「写入不报错、读取才炸」的错最难查，必须在写入口就转好。
    issue.status = m.IssueStatus(body.status)
    await uow.session.flush()
    return _issue_out(issue)


@router.patch("/sites/{site_id}/issues", response_model=dict)
async def bulk_update_issue_status(
    site_id: int,
    body: IssueBulkStatusIn,
    uow=__import__("fastapi").Depends(get_uow),
) -> dict:
    """按根因批量改状态（「这一类我都处理了」）。

    ⚠️ 刻意**不提供全选兜底**：一次把全站几百条标成「已修」极易点错，
    而这个操作没有 undo —— 状态只能一条条改回来。批量必须指明根因。
    """
    await _require_site(uow, site_id)
    n = await uow.issues.resolve_by_fingerprint(site_id, body.fingerprint, body.status)
    return {"updated": n}


# --------------------------------------------------------------------------
# P2 智能层：关键词 / Brief / AI 总结
#
# ⚠️ 这三类此前只有 CLI 能用（cli.py 里 15 处调用），**API 一行都没暴露**
# —— 意味着几个月前写好的能力，除了敲命令行没人能用得到。这不是「少个
# 功能」，是「做完了但没交付」。
#
# 统一原则：**推断类结果必须自带 limitations**。关键词扩展不出来、Brief
# 缺 SERP 数据、AI 总结没 key —— 三种都返回「诚实说不出结论」而不是空
# 列表或 500。返回空数组时调用方无法区分「真没有」和「算失败」，而这两种
# 该做的后续动作完全不同。
# --------------------------------------------------------------------------


@router.get("/sites/{site_id}/keywords", response_model=KeywordPage)
async def list_keywords(
    site_id: int,
    intent: Optional[str] = None,
    cluster_id: Optional[int] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    uow=__import__("fastapi").Depends(get_uow),
) -> KeywordPage:
    """已落库的关键词（扩展+聚类的结果，由扫描时顺带写入）。"""
    await _require_site(uow, site_id)
    page = await uow.keywords.list(
        site_id,
        intent=intent,
        cluster_id=cluster_id,
        limit=limit,
        offset=offset,
    )
    return KeywordPage(
        total=page.total,
        items=[
            KeywordOut(
                id=k.id,
                term=k.term,
                market=k.market,
                intent=k.intent,
                cluster_id=k.cluster_id,
                score=k.score,
                source=k.source,
            )
            for k in page.items
        ],
        has_next=offset + len(page.items) < page.total,
    )


@router.post("/sites/{site_id}/keywords/expand", response_model=KeywordExpandOut)
async def expand_keywords(
    site_id: int,
    body: KeywordExpandIn,
    uow=__import__("fastapi").Depends(get_uow),
) -> KeywordExpandOut:
    """按种子词，从**已抓页面**的语料里扩展候选并聚类，然后落库。

    ⚠️ 与 CLI 走同一套口径（同一道门槛、同一份实现），因为两处各算一套
    必然分叉，而分叉之后没人知道该信哪个。
    """
    from ..keywords import cluster as kw_cluster
    from ..keywords import expand as kw_expand
    from ..keywords import tokenize
    from ..persist import persist_keywords

    await _require_site(uow, site_id)
    corpus: list[tuple[str, str]] = []
    title_tokens: set[str] = set()
    # ⚠️ pages.list 返回的是 Page(items/total)，**不是可迭代对象**。
    # 直接 for row in 会 TypeError → 500。这是我第一版的错：
    # 「有分页」和「能直接迭代」是两回事。
    for row in (await uow.pages.list(site_id, limit=200, status_code=200)).items:
        # 正文截断：共现统计不需要全文，而全文会让 1000 页的 tokenize
        # 慢上一个数量级（与 cli.py 同一取舍）。
        text = (row.text or "")[:4000]
        head = (row.title or "") + " " + " ".join(row.h1 or [])
        if not (text or head.strip()):
            continue
        corpus.append((row.url, head + " " + text))
        title_tokens.update(tokenize(head))

    if len(corpus) < body.min_pages:
        return KeywordExpandOut(
            status="skipped_no_corpus",
            reason=(
                f"可用语料 {len(corpus)} 页 < 门槛 {body.min_pages} 页："
                "共现挖掘需要跨页证据，单页词语多半是该页专有名词"
            ),
        )
    seeds = [s.strip() for s in body.seeds if s.strip()]
    if not seeds:
        return KeywordExpandOut(
            status="skipped_no_seeds",
            reason="种子词为空：无种子的共现等于把全站词两两配对，噪声大于信号",
        )

    candidates = kw_expand.expand(
        seeds, corpus, max_candidates=body.max_candidates, min_pages=body.min_pages
    )
    stats = await persist_keywords(
        uow.session,
        site_id=site_id,
        candidates=candidates,
        clusters=kw_cluster.cluster([c.term for c in candidates])[0],
        market=body.market,
        title_tokens=title_tokens,
    )
    return KeywordExpandOut(
        status="ok",
        candidates=len(candidates),
        clusters=int(stats.get("clusters") or 0),
    )


@router.post("/sites/{site_id}/brief", response_model=BriefOut)
async def make_brief(
    site_id: int,
    body: BriefIn,
    uow=__import__("fastapi").Depends(get_uow),
) -> BriefOut:
    """为「一个关键词 + 一个目标 URL」生成内容 Brief。

    ⚠️ ``caveats`` 是这个端点最重要的字段：**缺 SERP 数据时不能装作是
    基于竞品全貌得出的结论**。Top10 共性需要 serp_snapshots 有数据，没数据
    就明说「竞品分析缺失」，让用户知道这份 Brief 的依据只有自己站。
    """
    from ..brief import ContentBrief, PageSignal, SerpEntry, generate_brief
    from ..models import Market

    site = await _require_site(uow, site_id)
    caveats: list[str] = []

    serp_entries: list[SerpEntry] = []
    try:
        # ⚠️ latest_for_keyword 收的是 keyword_id（整型），不是词字符串。
        # 得先把词翻成 id；翻不到就是「这个词没被抓过」，不是异常。
        kw = await uow.keywords.get_by_term(site_id, body.keyword)
        if kw is not None:
            serp_entries = [
                SerpEntry(
                    position=sn.position,
                    url=sn.url,
                    title=sn.title or "",
                    snippet=sn.snippet,
                )
                for sn in await uow.serp.latest_for_keyword(kw.id, limit=10)
            ]
    except Exception:  # noqa: BLE001 —— 没 SERP 数据不该让整个端点失败
        serp_entries = []
    if not serp_entries:
        caveats.append(
            "竞品数据缺失：serp_snapshots 里没有该词的记录，"
            "本 Brief 的 Top10 共性与标题候选**只基于本站**，不可当作竞品全貌"
        )

    own_pages = [
        PageSignal(
            url=row.url,
            title=row.title or "",
            h1=list(row.h1 or []),
            word_count=row.word_count or 0,
        )
        for row in (await uow.pages.list(site_id, limit=50, status_code=200)).items
    ]
    if not own_pages:
        caveats.append("本站无可用页面：字数基线缺失，标题长度建议将不可靠")

    brief: ContentBrief = generate_brief(
        body.keyword,
        target_url=body.target_url,
        market=Market(body.market) if body.market else Market.GOOGLE,
        intent=body.intent,
        serp_entries=serp_entries,
        own_pages=own_pages,
    )
    return BriefOut(
        keyword=brief.keyword,
        target_url=brief.target_url,
        market=brief.market,
        intent=brief.intent,
        page_type=brief.page_type,
        title_candidates=list(brief.title_candidates),
        serp_common=dict(brief.serp_common),
        own_length_baseline=dict(brief.own_length_baseline),
        opportunities=list(brief.opportunities),
        not_available=list(brief.not_available),
        caveats=caveats,
    )


@router.get("/sites/{site_id}/report/summary", response_model=SummaryOut)
async def report_summary(
    site_id: int,
    uow=__import__("fastapi").Depends(get_uow),
) -> SummaryOut:
    """报告的 AI 总结。

    ⚠️ **没配 key 就明确说没配**，而不是返回 null 让前端显示成空白 ——
    「还没接AI」和「AI 说了但没内容」对用户是两件完全不同的事。

    走 ``llm.summarize``：它内部吞掉所有异常返回 None，理由是 AI 总结是
    锦上添花、规则引擎报告才是主结果，**总结失败绝不能让报告整个消失**。
    这里要区分失败原因，所以改用 ``chat`` 拿异常。
    """
    from ..llm import LLMConfig, LLMNotConfigured, chat

    await _require_site(uow, site_id)
    cfg = LLMConfig.from_env()
    if not cfg.api_key:
        return SummaryOut(
            reason="未配置 LLM key（设 SEO_CLAW_LLM_API_KEY 后本端点才可用）"
        )
    page = await uow.issues.list(site_id, limit=200)
    try:
        text = chat(
            f"用中文为这个 SEO 体检报告写 3-5 句总结，指出最该先改的一处。"
            f"问题共 {page.total} 条，最严重的几条："
            + "；".join(f"{i.title}" for i in page.items[:5]),
            config=cfg,
        )
    except LLMNotConfigured:
        return SummaryOut(reason="LLM key 无效或模型不可用")
    except Exception as exc:  # noqa: BLE001
        return SummaryOut(reason=f"调用失败：{type(exc).__name__}: {exc}")
    return SummaryOut(summary=text, model=cfg.model)


@router.post("/sites/{site_id}/rank-drops", response_model=list[RankAlertOut])
async def rank_drops(
    site_id: int,
    body: RankDropRequest,
    uow=__import__("fastapi").Depends(get_uow),
) -> list[RankAlertOut]:
    """排名跌幅告警。

    ⚠️ **沉默比误报重要**：按天盯排名的人若每跌 2 名就收一条提醒，
    一周会收到七条，然后全部忽略 —— 告警一多就不叫告警了。所以三道
    门槛都由调用方显式传入（min_drop / min_impressions / min_days），
    而不是藏在代码里的默认魔法值。

    空数组是合法结论，不是失败：「最近没跌」就该返回空。
    """
    from ..alerts import RankPoint, detect_rank_drops

    await _require_site(uow, site_id)
    rows = await uow.ranks.recent(site_id, days=body.window_days)

    # 按 URL 攒成时间序列。recent 是 date DESC 排的，但 detect 会自己
    # 排序，这里只管分组 —— 排序口径只留一处，两处各排一次必有一处是错的。
    by_url: dict[str, list[RankPoint]] = {}
    for r in rows:
        by_url.setdefault(r.url, []).append(
            RankPoint(
                date=r.date.isoformat(),
                position=r.position,
                impressions=r.impressions or 0,
                clicks=r.clicks or 0,
            )
        )

    alerts = detect_rank_drops(
        by_url,
        min_drop=body.min_drop,
        min_impressions=body.min_impressions,
        min_days=body.min_days,
    )
    return [
        RankAlertOut(
            url=a.url,
            from_position=a.from_position,
            to_position=a.to_position,
            drop=a.drop,
            from_date=a.from_date,
            to_date=a.to_date,
            message=a.message,
            evidence=a.evidence,
        )
        for a in alerts
    ]


@router.get("/sites/{site_id}/usage", response_model=UsageOut)
async def usage(site_id: int, uow=__import__("fastapi").Depends(get_uow)) -> UsageOut:
    """计量汇总（按 kind）。

    ⚠️ 这里只给**数字**，不给「还剩多少额度」—— 配额与定价是产品决策，
    没定之前硬编一个阈值只会被当成既定事实。数字先可算，定价后加。
    """
    await _require_site(uow, site_id)
    by_kind = await uow.usage.totals(site_id)
    return UsageOut(
        site_id=site_id, by_kind=by_kind, total=sum(by_kind.values())
    )


@router.get("/sites/{site_id}/trend", response_model=ScoreTrend)
async def trend(site_id: int, uow=__import__("fastapi").Depends(get_uow)) -> ScoreTrend:
    """分数随时间的变化 —— 趋势线数据。

    ⚠️ 两个坑，都在这行代码里体现：

    1. **只取算得出分数的那几次。** 0 页成功时 health_score 是 null，
       那是「什么都没看到」而不是「0 分」。把它画进趋势线，会让一条
       明明没抓到的扫描看起来像暴跌 —— **用一个抓取失败冒充一次质量下滑，
       是比不画更糟的谎**。所以 ``score is None`` 的直接跳过。

    2. **按时间升序返回。** DB 默认是 ``id DESC``（新的在前），直接吐给前端
       连线会画成一条反着的线，而这种错在图上看不出来，只会看起来「不对」，
       极难自查。所以这里显式 reverse。
    """
    site = await _require_site(uow, site_id)
    page = await uow.jobs.list_for_site(site_id, limit=100)
    points: list[ScorePoint] = []
    for job in reversed(page.items):  # 最老的在前
        if getattr(job, "health_score", None) is None:
            continue
        points.append(
            ScorePoint(
                job_id=job.id,
                score=job.health_score,
                pages_crawled=job.pages_crawled,
                status=job.status.value,
                finished_at=job.finished_at,
            )
        )
    return ScoreTrend(site_id=site_id, domain=site.domain, points=points)


@router.get("/sites/{site_id}/report", response_model=ReportSummary)
async def report(site_id: int, uow=__import__("fastapi").Depends(get_uow)) -> ReportSummary:
    """最新一次扫描的汇总。

    ⚠️ 0 页成功时 ``health_score`` 必须是 ``null`` 而不是 0 ——
    「一页没抓到」和「抓到了但全是问题」是两回事，不能都报 0 分。
    """
    site = await _require_site(uow, site_id)
    jobs = await uow.jobs.list_for_site(site_id, limit=1)
    # count_by_severity 一次返回 dict，且只统计 OPEN 状态的问题。
    # 缺失的 severity 必须补 0：前端按 key 取值，缺 key 会渲染成 undefined。
    raw_counts = await uow.issues.count_by_severity(site_id)
    counts: dict[str, int] = {sev.value: raw_counts.get(sev.value, 0) for sev in m.Severity}
    issues_page = await uow.issues.list(site_id, limit=200)
    items = [
        _issue_out(i) for i in issues_page.items
    ]
    pages_crawled = jobs.items[0].pages_crawled if jobs.items else 0
    return ReportSummary(
        domain=site.domain,
        pages_crawled=pages_crawled,
        counts=counts,
        health_score=None if pages_crawled == 0 else _latest_score(jobs),
        issues=items,
    )


def _latest_score(jobs) -> float | None:
    """取最近一次扫描的健康分。

    ⚠️ 以前这里读 ``job.score_breakdown`` 字典，而 crawl_jobs **压根没有
    这一列**（已由 0002_job_scores 补上，但老数据还是 null）→ 属性读不到
    → 返回 None → 接口 health_score 恒为 null → 前端按「一页都没抓到」
    渲染。**分数算了、接口也返回了，却从没存下来。**

    现在读 ``job.health_score`` 这条真列。老库没跑过迁移时它不存在，
    故用 getattr 兜底成 None，而不是直接抛 AttributeError 把接口打挂。
    """
    if not jobs.items:
        return None
    v = getattr(jobs.items[0], "health_score", None)
    return float(v) if isinstance(v, (int, float)) else None