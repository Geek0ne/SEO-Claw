"""HTTP 路由：站点管理 / 扫描触发 / 报告查询三类。

⚠️ 同步爬虫不能直接在协程里跑 —— `run_scan` 内部用 `asyncio.to_thread`
丢到线程池，事件循环才不会被一次几十秒的扫描堵死。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Response

from ..db import models as m
from .auth import current_auth, guard
from .deps import get_uow
from .summary import build_summary
from .schemas import (
    ApiKeyCreated,
    ApiKeyOut,
    MeOut,
    QuotaOut,
    VerificationOut,
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
    RankAlertAckIn,
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
    # ⚠️ 必须显式写 owner：列的默认值是 "local"，那是给自部署单机用的。
    # SaaS 模式下若靠默认，新建的站会落到 local 归属，租户就看不到它了。
    site.owner = current_auth().owner
    await uow.session.commit()
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
    # ⚠️ 必须按 owner 过滤。我第一版只在 _require_site 加了归属校验，
    # 以为「15 个端点都受益」就万事大吉 —— 但列表端点根本不调
    # _require_site，于是 tenant-a 能看到 tenant-b 的全部站点。
    # 单站点硬闯是 404（对），列表整片泄露（错）。实跑才逮到。
    page = await uow.sites.list(
        limit=limit, offset=offset, owner=current_auth().owner
    )
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
    """取站点，并**校验归属**。

    ⚠️ 归属校验放在这里而不是每个端点，是因为端点有 15 个：逐个加会
    漏，而漏掉的那一个**不会报错、只会放行** —— 那是最坏的失败方式。

    不属于当前归属时回 404 而不是 403：403 等于告诉对方「这个站存在，
    只是你没权限」，那本身就是信息泄露。
    """
    site = await uow.sites.get(site_id)
    if site is None:
        raise HTTPException(status_code=404, detail=f"站点不存在：{site_id}")
    guard(current_auth(), site)
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
    from . import quota as q

    site = await _require_site(uow, site_id)
    # ⚠️ 按**请求的页数**拦，不是按已用值：否则用户可以提交一次 5000 页
    # 的请求，穿过检查后才在扫描中途被拒 —— 那时候爬取已经开始了。
    a = current_auth()
    # ⚠️ 必须 await。enforce 里 raise HTTPException 是在**协程体内**发生的，
    # 不 await 它等于这段校验根本不存在 —— 而一个「看起来拦了其实没拦」
    # 的额度检查比没有更坏：用户会以为超额被挡住了。
    await q.enforce(uow.session, a.owner, would_use=int(body.max_pages), enabled=a.enabled)
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

    # 归属校验：不是本租户的站点在这里就 404，返回值本身用不上
    await _require_site(uow, site_id)
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
    「还没接 AI」和「AI 说了但没内容」对用户是两件完全不同的事。

    ⚠️ 这里刻意**不用** ``llm.summarize``：它内部吞掉所有异常返回 None，
    而这里要把失败原因告诉用户（key 无效？模型不可用？超时？）。
    代价是要自己接异常，但少了「为什么失败」这个信息。
    """
    import asyncio

    from ..llm import LLMConfig, LLMNotConfigured, _build_prompt, chat

    site = await _require_site(uow, site_id)
    cfg = LLMConfig.from_env()
    if not cfg.api_key:
        return SummaryOut(
            reason="未配置 LLM key。设 SEO_CLAW_LLM_API_KEY 后本端点才可用；"
                   "报告本身不受影响，规则引擎结果才是主结果。"
        )

    page = await uow.issues.list(site_id, limit=200)
    # ⚠️ _latest_score 收的是 **jobs 列表**，返回 float —— 我第一版按
    # 「(uow, site_id) → 对象」去调，端点直接 500。
    # 今天在「凭印象写签名」上栽的次数最多，这里改成照第 687 行的用法走。
    # ⚠️⚠️ 这里我连着错了两次签名：先当 (uow, site_id)，再当返回 list。
    # 实际是：list_for_site 返回 **Page**，_latest_score 也吃 **Page**
    # （它内部读 jobs.items[0]）。两次都是「凭印象写」造成的，
    # 所以这次照第 687 行的既有用法照抄，不再自己编。
    jobs_page = await uow.jobs.list_for_site(site_id, limit=1)
    job = jobs_page.items[0] if jobs_page.items else None
    health = _latest_score(jobs_page)

    # ⚠️ _build_prompt 要的是「报告对象」，这里手上只有 issues 分页。
    # 拼一个薄壳而不是改 _build_prompt 的签名 —— 那个函数 CLI 也在用，
    # 改签名要同步改两处调用点，而它们要的字段其实是一样的。
    class _Shim:
        domain = site.domain
        issues = page.items
        pages_crawled = getattr(job, "pages_crawled", None) or page.total
        pages_discovered = page.total
        health_score = health
        score_breakdown = getattr(job, "score_breakdown", None) or {}

    prompt = _build_prompt(_Shim(), max_issues=12)

    try:
        # ⚠️ 必须 to_thread：chat() 是同步 httpx，直接在 async 端点里调
        # 会把整个事件循环卡住 —— 一个 60 秒超时的模型请求足以让这个服务
        # 对**所有用户**无响应。我今天已经在验证脚本里犯过一次这个错。
        text = await asyncio.to_thread(chat, prompt, config=cfg)
    except LLMNotConfigured as exc:
        return SummaryOut(reason=f"LLM 未就绪：{exc}")
    except Exception as exc:  # noqa: BLE001
        return SummaryOut(reason=f"调用失败：{type(exc).__name__}: {exc}")
    if not (text or "").strip():
        return SummaryOut(reason="模型返回了空内容，可换个模型再试。")
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

    # ⚠️ only_new 过滤的是「用户已标记看过」的，**不是自动标记**。
    # 若这里顺手把返回过的都记成已看，那「我算了但没人看」也算看过，
    # 这声告警等于根本没发过 —— 用户下一次就不会再来了。
    if body.only_new:
        seen = await uow.alert_acks.acked_keys(site_id)
        alerts = [a for a in alerts if a.key not in seen]

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
            alert_key=a.key,
        )
        for a in alerts
    ]


@router.post("/sites/{site_id}/rank-drops/ack", response_model=dict)
async def ack_rank_drops(
    site_id: int,
    body: RankAlertAckIn,
    uow=__import__("fastapi").Depends(get_uow),
) -> dict:
    """把若干条告警标记为「已看过」，幂等。

    ⚠️ **只接受调用方给的 key，不校验它们当前是否仍是告警** ——
    「历史上某场跌落被看过」这件事本身就该长期有效。若要求 key 必须
    还在当前告警列表里，那么随着窗口滑动，同一件事会重新变成「新告警」，
    反复提醒；而标记它的目的正是避免这个。
    """
    await _require_site(uow, site_id)
    added = await uow.alert_acks.ack(site_id, body.alert_keys)
    return {"acked": added, "total": len(set(body.alert_keys))}


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
    await _require_site(uow, site_id)  # 站点不存在 → 404
    # ⚠️ 装配交给 summary.build_summary：MCP Server 也要同一份报告。
    # 两处各写一份必然分叉，而分叉之后没人知道该信哪个 —— 而 MCP 的
    # 报告是给模型看的，与网页不一致意味着模型的建议会和用户看到的对不上。
    return ReportSummary(**await build_summary(uow, site_id))


@router.get("/sites/{site_id}/report/export")
async def export_report(
    site_id: int,
    format: str = Query("md", pattern="^(md|html|json)$"),   # noqa: A002
    uow=__import__("fastapi").Depends(get_uow),
) -> Response:
    """导出报告文件（md / html / json）。

    Web 端此前只有「看」没有「带定」：CLI 能导三种格式，网页上一条都
    导不出——交付客户的场景全被推回命令行。这里补上 F5 的「一键导出」。

    ⚠️ 口径是**数据库重建的摘要**，不是扫描现场的完整报告（见
    :mod:`seoclaw.api.export` 的说明）——文件里写明了这一点，
    不冒充完整版。
    """
    from .export import render_html, render_markdown

    await _require_site(uow, site_id)  # 站点不存在 → 404
    summary = await build_summary(uow, site_id)

    # 扫描历史一并带给导出件：趋势数据在库里，没理由不让它跟着走。
    jobs = await uow.jobs.list_for_site(site_id, limit=50)
    trend = {
        "points": [
            {
                "job_id": j.id,
                "score": getattr(j, "health_score", None),
                "pages_crawled": j.pages_crawled,
                "status": j.status.value,
                "finished_at": j.finished_at.isoformat() if j.finished_at else None,
            }
            for j in jobs.items
        ]
    }

    import json as _json
    from datetime import datetime, timezone

    domain = summary.get("domain", "site").replace("/", "_")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    base = f"seo-claw-{domain}-{stamp}"

    if format == "json":
        body = _json.dumps(
            {"summary": summary, "trend": trend}, ensure_ascii=False, indent=2
        )
        media, ext = "application/json; charset=utf-8", "json"
    elif format == "html":
        body = render_html(summary, trend)
        media, ext = "text/html; charset=utf-8", "html"
    else:
        body = render_markdown(summary, trend)
        media, ext = "text/markdown; charset=utf-8", "md"

    return Response(
        content=body,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{base}.{ext}"'},
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

# ══════════════════════════════════════════════════════════════════
# 租户：身份、钥匙、归属验证
#
# 归属校验统一在 _require_site 里做（那里已经接好 current_auth），
# 所以下面这些端点不需要各自再写一遍 —— 写了就等于两处口径。
# ══════════════════════════════════════════════════════════════════


@router.get("/me", response_model=MeOut)
async def me(uow=__import__("fastapi").Depends(get_uow)) -> MeOut:
    """我是谁 + 我还有多少免费额度。

    ⚠️ 单机模式（未开鉴权）返回 ``enforced: false``，而不是 limit=0。
    「不限量」是产品决定，「额度是 0」是配置错误，含义不同。
    """
    from . import quota as q

    a = current_auth()
    snap = await q.enforce(uow.session, a.owner, would_use=0, enabled=a.enabled)
    return MeOut(owner=a.owner, auth_enabled=a.enabled, quota=QuotaOut(**snap))


@router.post("/keys", response_model=ApiKeyCreated, status_code=201)
async def create_key(
    name: str = "default",
    uow=__import__("fastapi").Depends(get_uow),
) -> ApiKeyCreated:
    """签发一把访问钥匙。⚠️ **明文只在这里返回一次。**

    库里只存 sha256：明文丢一次就等于全库钥匙同时暴露。丢了只能
    重新签发，找不回来 —— 这是有意的代价。
    """

    from .auth import new_key

    raw, prefix, key_hash = new_key()
    row = m.ApiKey(
        owner=current_auth().owner,
        name=name[:64],
        key_prefix=prefix,
        key_hash=key_hash,
    )
    uow.session.add(row)
    await uow.session.commit()
    return ApiKeyCreated(
        key=raw,
        key_prefix=prefix,
        name=row.name,
        warning="这是唯一一次显示完整钥匙。请立刻保存；丢失后只能重新签发，无法找回。",
    )


@router.get("/keys", response_model=list[ApiKeyOut])
async def list_keys(uow=__import__("fastapi").Depends(get_uow)) -> list[ApiKeyOut]:
    """列出钥匙。只返回前缀 —— 完整钥匙不在库里，也没有理由展示。"""
    from sqlalchemy import select

    a = current_auth()
    rows = (await uow.session.execute(
        select(m.ApiKey).where(m.ApiKey.owner == a.owner).order_by(m.ApiKey.id)
    )).scalars().all()
    return [
        ApiKeyOut(
            id=r.id,
            name=r.name,
            key_prefix=r.key_prefix,
            created_at=r.created_at.isoformat() if r.created_at else "",
            last_used_at=r.last_used_at.isoformat() if r.last_used_at else None,
            revoked=r.revoked_at is not None,
        )
        for r in rows
    ]


@router.post("/keys/{key_id}/revoke", response_model=ApiKeyOut)
async def revoke_key(
    key_id: int, uow=__import__("fastapi").Depends(get_uow)
) -> ApiKeyOut:
    """撤销钥匙（标记而非删除）。

    ⚠️ 删掉的话历史计量就找不到归属了 —— 而计费数字必须能被追溯。
    """
    from datetime import datetime, timezone

    from sqlalchemy import select

    a = current_auth()
    row = (await uow.session.execute(
        select(m.ApiKey).where(m.ApiKey.id == key_id, m.ApiKey.owner == a.owner)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="钥匙不存在。")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        await uow.session.commit()
    return ApiKeyOut(
        id=row.id,
        name=row.name,
        key_prefix=row.key_prefix,
        created_at=row.created_at.isoformat() if row.created_at else "",
        last_used_at=row.last_used_at.isoformat() if row.last_used_at else None,
        revoked=True,
    )


# ── 归属验证：这个站凭什么算你的 ────────────────────────────


@router.get("/sites/{site_id}/verification", response_model=VerificationOut)
async def get_verification(
    site_id: int, uow=__import__("fastapi").Depends(get_uow)
) -> VerificationOut:
    """当前验证状态；没验证过就顺带把 token 与两条通道的说明给出来。"""
    from . import verification as V

    site = await _require_site(uow, site_id)
    return VerificationOut(
        status=site.verify_status,
        token=site.verify_token,
        dns_instructions=V.dns_instructions(site.domain, site.verify_token or "")
        if site.verify_status != "verified" else None,
        meta_instructions=V.meta_instructions(site.verify_token or "")
        if site.verify_status != "verified" else None,
        verified_at=site.verified_at.isoformat() if site.verified_at else None,
        verify_method=site.verify_method,
    )


@router.post("/sites/{site_id}/verification", response_model=VerificationOut)
async def start_verification(
    site_id: int, uow=__import__("fastapi").Depends(get_uow)
) -> VerificationOut:
    """生成（或重新生成）验证 token。

    ⚠️ 重新生成会让旧 token 立即失效 —— 这是刻意的：token 泄露过之后
    留着它等于把门开着，而站点所有者随时能再生成一个。
    """
    from . import verification as V

    site = await _require_site(uow, site_id)
    site.verify_token = V.new_token()
    site.verify_status = "unverified"
    site.verified_at = None
    site.verify_method = None
    await uow.session.commit()
    return VerificationOut(
        status=site.verify_status,
        token=site.verify_token,
        dns_instructions=V.dns_instructions(site.domain, site.verify_token),
        meta_instructions=V.meta_instructions(site.verify_token),
    )


@router.post("/sites/{site_id}/verification/check", response_model=VerificationOut)
async def check_verification(
    site_id: int,
    method: str = "dns",
    uow=__import__("fastapi").Depends(get_uow),
) -> VerificationOut:
    """实际去查 DNS TXT 或首页 meta。

    ⚠️ **查不到 ≠ 验证失败。** DNS 超时、记录未传播、首页打不开都会
    落到 unknown，所以结果有三态。用户看到 unknown 时该做的是手动确认，
    不是反复点重试。
    """
    from . import verification as V

    site = await _require_site(uow, site_id)
    if not site.verify_token:
        raise HTTPException(
            status_code=400, detail="还没有生成验证 token，请先点「开始验证」。"
        )
    if method not in ("dns", "meta"):
        raise HTTPException(status_code=400, detail="method 只能是 dns 或 meta。")

    # dig / httpx 都是阻塞的，放线程池 —— 否则会把事件循环卡住，
    # 单个慢 DNS 就能让整个服务对所有用户无响应。
    import asyncio

    if method == "dns":
        res = await asyncio.to_thread(
            V.check_dns, site.domain, site.verify_token
        )
    else:
        res = await asyncio.to_thread(
            V.check_meta, site.domain, site.verify_token
        )

    if res.verdict == "yes":
        from datetime import datetime, timezone

        site.verify_status = "verified"
        site.verify_method = method
        site.verified_at = datetime.now(timezone.utc)
    elif res.verdict == "unknown":
        # ⚠️ unknown **不**改状态：查不到只是「我暂时判断不了」，
        # 不能当成「没通过」把用户已放进去的 token 清掉。
        pass
    await uow.session.commit()

    return VerificationOut(
        status=site.verify_status,
        token=site.verify_token,
        dns_instructions=V.dns_instructions(site.domain, site.verify_token),
        meta_instructions=V.meta_instructions(site.verify_token),
        verified_at=site.verified_at.isoformat() if site.verified_at else None,
        verify_method=site.verify_method,
    )


@router.delete("/sites/{site_id}", status_code=204)
async def delete_site(
    site_id: int, uow=__import__("fastapi").Depends(get_uow)
) -> None:
    """删除站点。⚠️ 连带删除它的所有页面、问题、关键词、计量记录。

    这是不可逆的，所以端点存在不等于 UI 上就该随手给个按钮 ——
    Web 那边会要求二次确认。
    """
    site = await _require_site(uow, site_id)
    await uow.session.delete(site)
    await uow.session.commit()
    return None
