#!/usr/bin/env python3
"""
SEO-Claw CLI —— M0 入口。

用法：
    python -m seoclaw.cli scan https://example.com --max-pages 200
    python -m seoclaw.cli scan example.com --max-pages 50 --market google --json
    python -m seoclaw.cli rules          # 列出已加载的检查项
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .audit.engine import default_registry, run_audit
from .crawler import CrawlConfig, Crawler
from .models import Market, SiteReport
from .report import render_markdown, summarize_console
from .scoring import score
from .util import same_site_scope


async def _persist_keywords_for_session(
    session, *, site_id: int, pages, market: str
) -> dict:
    """在已有 session 里跑关键词扩展 + 聚类并落库。

    为什么单独一个函数（且**不与 persist_scan 共用异常处理**）：
    关键词算不出来不该让页面与问题一起回滚 —— 前者是增强，后者是主结果。

    ⚠️ 两道门槛都会「诚实地说不出结论」，而不是硬凑一个结果：
    可用语料不足 2 页 → 跳过（共现挖掘需要跨页证据）；
    没有种子词 → 跳过（无种子的共现等于把全站词两两配对，噪声大于信号）。
    """
    from collections import Counter

    from .db.repository import KeywordRepository
    from .keywords import cluster, expand, tokenize
    from .persist import persist_keywords

    # 语料：标题 + H1 + 正文。正文截断 —— 共现统计不需要全文，
    # 而全文会让 1000 页的 tokenize 慢上一个数量级。
    corpus: list[tuple[str, str]] = []
    title_tokens: set[str] = set()
    title_tf: Counter = Counter()
    for p in pages:
        if p.status_code != 200 or p.error or not p.is_html:
            continue
        h1 = " ".join(p.h1)
        head = (p.title or "") + " " + h1
        head_toks = tokenize(head)
        title_tokens.update(head_toks)
        title_tf.update(head_toks)
        corpus.append((p.url, f"{head} {(p.text or '')[:2000]}"))

    if len(corpus) < 2:
        return {"skipped": f"可用语料仅 {len(corpus)} 页，共现挖掘需要跨页证据"}

    # 种子：优先用库里已跟踪的词。空库则退回「标题里最高频的 5 个 token」。
    # ⚠️ KeywordRepository.list() 返回的是**分页对象** Page(items=...)，不是列表。
    # 直接迭代会报 `TypeError: 'Page' object is not iterable` —— 第一次实跑就撞上了。
    known = await KeywordRepository(session).list(site_id, limit=50)
    seeds = [k.term for k in known.items]
    if not seeds:
        seeds = [t for t, _ in title_tf.most_common(5)]
    if not seeds:
        return {"skipped": "没有任何种子词（title/h1 全为空），无法做共现挖掘"}

    candidates = expand(seeds, corpus, min_pages=2)
    if not candidates:
        return {"skipped": "共现挖掘没有产出候选词"}

    clusters, _evidence = cluster([c.term for c in candidates])
    return await persist_keywords(
        session,
        site_id=site_id,
        candidates=candidates,
        clusters=clusters,
        market=market,
        title_tokens=title_tokens,
    )


def _persist_scan(
    db_spec: str,
    *,
    url: str,
    pages,
    issues,
    markets,
    discovered: int,
    elapsed: float,
) -> dict:
    """把扫描结果写进库，返回落库摘要。

    ``db_spec`` 既可以是 SQLite 文件路径（``seo.db``），也可以是完整
    ``DATABASE_URL``。判断方式：**含 ``://`` 就当 URL，否则当文件路径**。

    ⚠️ 表结构一律走 **Alembic**，不在这里 create_all——
    create_all 不做 schema 版本管理，将来加了列会造出
    「库里缺列但代码以为是新的」这种静默故障。
    """
    import asyncio

    from .db.session import get_engine, get_session_factory, session_scope
    from .persist import get_or_create_site, persist_scan

    db_url = db_spec if "://" in db_spec else f"sqlite+aiosqlite:///{db_spec}"

    async def _run() -> dict:
        engine = get_engine(db_url)
        factory = get_session_factory(db_url)
        async with factory() as session:
            async with session_scope(session):
                site_id = await get_or_create_site(
                    session, url, markets=[m.value for m in markets]
                )
                info = await persist_scan(
                    session,
                    site_id=site_id,
                    pages=pages,
                    issues=issues,
                    url_count=discovered,
                    elapsed=elapsed,
                )
                # 关键词扩展 + 聚类（纯离线，见 app/keywords/）。
                # 单独 try：关键词算不出来不该让页面/问题落库一起回滚。
                try:
                    info["keywords"] = await _persist_keywords_for_session(
                        session, site_id=site_id, pages=pages,
                        market=markets[0].value if markets else "base",
                    )
                except Exception as exc:  # noqa: BLE001
                    info["keywords"] = {"error": f"{type(exc).__name__}: {exc}"}
                return info


    return asyncio.run(_run())


def cmd_scan(args: argparse.Namespace) -> int:
    cfg = CrawlConfig(
        max_pages=args.max_pages,
        max_depth=args.max_depth,
        per_domain_rps=args.rps,
        respect_robots=not args.ignore_robots,
        adaptive_backoff=args.adaptive_backoff,
        render_js=args.render_js,
        timeout=float(args.render_timeout) if args.render_js else 20.0,
    )
    # 市场包两种：常规（base/google/baidu/cnh_eco，走 Market 过滤）
    # 与实验包（geo，点名后才加载，不进默认注册表）。
    known = {m.value for m in Market}
    requested = list(dict.fromkeys(args.market))  # 去重且保序
    extra_packs = [p for p in requested if p not in known]
    markets = [Market(m) for m in requested if m in known] or [Market.BASE]

    proxies = list(args.proxy or [])
    if args.proxy_file:
        try:
            for ln in Path(args.proxy_file).read_text(encoding="utf-8").splitlines():
                t = ln.strip()
                if t and not t.startswith("#"):
                    proxies.append(t)
        except OSError as exc:
            print(f"❌ 读取代理文件失败：{exc}", file=sys.stderr)
            return 2
    cfg.proxies = tuple(proxies)

    print(f"→ 扫描 {args.url}", file=sys.stderr)
    print(
        f"  上限 {cfg.max_pages} 页 · 单域 {cfg.per_domain_rps} req/s · "
        f"市场 {[m.value for m in markets]}"
        + (f" + 实验包 {extra_packs}" if extra_packs else ""),
        file=sys.stderr,
    )

    started = time.monotonic()
    started_at = datetime.now(timezone.utc)
    checkpoint = Path(args.checkpoint) if args.checkpoint else None

    with Crawler(cfg, checkpoint_dir=checkpoint) as crawler:
        last = [0.0]

        def progress(page, n):  # noqa: ANN001
            now = time.monotonic()
            if now - last[0] < 1.0 and n < cfg.max_pages:
                return
            last[0] = now
            print(f"  [{n}/{cfg.max_pages}] {page.status_code} {page.word_count:>6}字 {page.url[:80]}", file=sys.stderr)

        crawler.incremental = bool(args.incremental)
        if args.incremental and not checkpoint:
            print("⚠️ --incremental 需要 --checkpoint 提供上一轮快照，没有基准就退化成全量扫描",
                  file=sys.stderr)
        pages = crawler.crawl(args.url, on_page=progress)
        discovered = getattr(crawler, "discovered_count", len(pages))
        site_facts = _collect_site_facts(crawler)

    rot = getattr(crawler, "proxy_rotations", 0)
    if proxies:
        print(
            f"→ 代理池 {len(proxies)} 个 · 实际轮换 {rot} 次"
            + (f"（当前出口 {crawler.current_proxy}）" if rot else "（未触发轮换）"),
            file=sys.stderr,
        )
    print(f"→ 抓取完成：{len(pages)} 页，耗时 {time.monotonic() - started:.0f}s", file=sys.stderr)

    # 抓取覆盖情况：孤岛页/重复页这类全局结论必须知道覆盖率才敢下结论
    site_facts["discovered_count"] = discovered
    # ★ 口径必须是「frontier 还有没有剩」，不是「本趟有没有打满上限」。
    # 分批跑站时每一趟都以打满上限收尾，旧口径会让 hit_page_limit 永远为 True
    # → has_enough_data() 永远 False → 孤岛页/重复页这类站点级结论永远不出现，
    # 「分批跑完整站」等于白做（2026-10-02 实测 3→6→9 页确认分批本身没问题）。
    # frontier 空 = 该抓的都抓完了，覆盖率是完整的，站点级规则该发话。
    site_facts["hit_page_limit"] = bool(
        getattr(crawler, "aborted_reason", None)
        or not getattr(crawler, "frontier_drained", False)
    )
    # ⚠️ 分子只数**抓成功**的页。pages 里混着失败页（429/403/超时/连接错误），
    # 它们进 pages 列表但一行内容都没有——算进分子就成了「抓到了」。
    # 实测踩过：w3.org 被打限流，种子页 429、frontier 空，
    # 报告却打「1/1 = 100.0%」——一页没抓到还宣称 100% 覆盖。
    # 这跟 gymshark 的 0.0 分、lobste.rs 的 100 分是同一类病：把抓取失败
    # 当成正常结果报出去。全站 0 页成功时必须显式说明，不能给百分比。
    ok_pages = [p for p in pages if p.status_code == 200 and not p.error]
    failed = len(pages) - len(ok_pages)
    if ok_pages:
        coverage = len(ok_pages) / max(discovered, 1)
        print(
            f"→ 抓取覆盖率：{len(ok_pages)}/{discovered} = {coverage:.1%}"
            + (f"（{failed} 页抓取失败，未计入）" if failed else ""),
            file=sys.stderr,
        )
    else:
        # 0 页成功时给百分比就是在撒谎，直接说没抓到
        print(
            f"⚠️ 抓取覆盖率：0/{discovered} —— **本页都没抓成功**，"
            f"{failed} 次请求全部失败（限流/封禁/网络）。下面的结论不可用。",
            file=sys.stderr,
        )
    site_facts["pages_ok"] = len(ok_pages)
    site_facts["pages_failed"] = failed

    # 回访外部目标。canonical：区分「指向不存在的地址」与「有意的版本别名/合并」；
    # og:image：区分「封面图真的打不开」与「根本没回访过」。
    # 合在一个 verifier 里，避免开两个 HTTP 客户端。
    if not args.no_verify_canonical or not args.no_verify_og_image:
        with Crawler(cfg) as verifier:
            if not args.no_verify_canonical:
                site_facts["canonical_target_status"] = verifier.verify_canonical_targets(pages)
                checked = len(site_facts.get("canonical_target_status") or {})
                if checked:
                    print(f"→ canonical 目标回访：{checked} 个", file=sys.stderr)
            if not args.no_verify_og_image:
                # ⚠️ 之前这个键没人写，`og:image.broken` 在生产里是条死规则：
                # 规则写得对（没回访就不猜），但没人喂数据，测试里手塞值就绿了。
                site_facts["og_image_status"] = verifier.verify_og_image_targets(pages)
                n = len(site_facts.get("og_image_status") or {})
                if n:
                    print(f"→ og:image 回访：{n} 个", file=sys.stderr)
    if "sitemap_found" in site_facts:
        state = "找到" if site_facts["sitemap_found"] else "未找到"
        print(f"→ sitemap：{state}（{site_facts.get('sitemap_url_count', 0)} 个 URL）", file=sys.stderr)
    if site_facts.get("robots_status"):
        print(f"→ robots.txt：HTTP {site_facts['robots_status']}", file=sys.stderr)

    # 增量收益要如实报，不能只在没报错时悄悄变快
    if args.incremental:
        hit = getattr(crawler, "not_modified_count", 0)
        sent = getattr(crawler, "conditional_sent", 0)
        print(f"→ 增量扫描：条件请求 {sent} 次，其中 {hit} 个页面服务器回 304（未重传正文）",
              file=sys.stderr)
    issues, _ctx = run_audit(pages, urlparse(args.url).netloc, markets, site_facts,
                             incremental=bool(args.incremental),
                             extra_rule_packages=extra_packs)
    netloc = urlparse(args.url).netloc
    # 分母只算本站页面。抓取器会把兄弟子域也当站内（is_internal 按可注册域
    # 判断，对内链权重传递是对的），但计分不该跨子域——gymshark 25 页里
    # 24 页是 us.checkout.gymshark.com，用 25 做分母会把主站的扣分稀释 24 倍。
    in_scope_pages = sum(1 for p in pages if same_site_scope(p.url, netloc))
    health, breakdown = score(issues, in_scope_pages or len(pages), netloc)

    report = SiteReport(
        domain=urlparse(args.url).netloc,
        markets=markets,
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
        pages_crawled=len(pages),
        pages_discovered=discovered,
        duration_seconds=time.monotonic() - started,
        health_score=health,
        score_breakdown=breakdown,
        issues=issues,
    )

    # 落库：可选。**必须放在 report 构造之后** —— 只有 issues/pages 都定稿了
    # 才写，否则库里会留下一份与报告对不上的半成品。
    #
    # ⚠️ 落库失败绝不能让扫描失败：报告已经生成了，用户拿不到报告才是真损失。
    # 失败只告警，退出码仍按报告可用性给。
    if args.db:
        try:
            info = _persist_scan(
                args.db,
                url=args.url,
                pages=pages,
                issues=issues,
                markets=markets,
                discovered=discovered,
                elapsed=time.monotonic() - started,
            )
            print(
                f"→ 已落库：site #{info['site_id']} · job #{info['job_id']} · "
                f"{info['pages_written']} 页 / {info['issues_written']} 条问题",
                file=sys.stderr,
            )
            # ⚠️ 关键词结果必须显式说出来。「主结果落库成功、关键词悄悄为 0」
            # 看起来跟「这个站没关键词机会」一模一样 —— 而后者是结论，前者是故障。
            kw = info.get("keywords") or {}
            if "error" in kw:
                print(f"⚠️ 关键词扩展失败：{kw['error']}", file=sys.stderr)
            elif "skipped" in kw:
                print(f"→ 关键词扩展跳过：{kw['skipped']}", file=sys.stderr)
            elif kw:
                print(
                    f"→ 关键词：{kw.get('keywords_written', 0)} 个词 / "
                    f"{kw.get('clusters_written', 0)} 个簇"
                    + (f"（其中 {kw['tracked']} 个已有页面在竞争）" if kw.get("tracked") else ""),
                    file=sys.stderr,
                )
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️ 落库失败（报告不受影响）：{type(exc).__name__}: {exc}", file=sys.stderr)

    # AI 总结：可选增强，**任何失败都不能让报告消失**。
    # 但「用户配了却没生成」必须说出来——静默失败会被当成
    # 「总结就是这个结论」，那等于给了一个不完整的答案。
    ai_summary = None
    if args.llm_summary:
        from .llm import LLMConfig, summarize

        cfg = LLMConfig.from_env()
        ai_summary = summarize(report, config=cfg)
        if ai_summary:
            print(f"→ 已生成 AI 总结（{cfg.model}）", file=sys.stderr)
        else:
            print(
                "⚠️ 未生成 AI 总结"
                + ("：缺少 API key（SEO_CLAW_LLM_API_KEY / OPENROUTER_API_KEY / OPENAI_API_KEY）"
                   if not cfg.api_key else "：调用失败，详见上。")
                + "。报告其余部分完整，不受影响。",
                file=sys.stderr,
            )

    if args.json:
        payload = report.model_dump(mode="json")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif not args.html:
        md = render_markdown(report, pages)
        if ai_summary:
            md = md.replace(
                "## 最该先做的 5 件事",
                f"## AI 总结\n\n{ai_summary}\n\n## 最该先做的 5 件事",
                1,
            )
        if args.output:
            _write(Path(args.output), md)
        if not args.quiet:
            print(md)

    # HTML 独立于 markdown 输出：--html 可以和 -o 同时给，
    # 也可以单独给（那样就不往 stdout 灌 Markdown）。
    if args.html:
        from .report_html import render_html

        _write(Path(args.html), render_html(report, pages, ai_summary=ai_summary))
        if not args.quiet and not args.json:
            print(
                "→ HTML 报告已写入 "
                f"{args.html}（单文件、无外链，可直接发给客户）",
                file=sys.stderr,
            )

    if not args.json and not args.quiet:
        print(summarize_console(report))
    return 0


def _write(out_path: Path, content: str) -> None:
    """写报告文件。

    ⚠️ 输出目录可能不存在——第一次就踩过：扫描跑完 60 页，
    结果因为目录不存在直接丢。所以每次写之前都建。
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")


def _collect_site_facts(crawler: Crawler) -> dict:
    """收集站点级事实，传给 SITE 级规则（robots/sitemap 类检查）。

    这里只汇总爬虫已经拿到的探测结果，不额外发请求。
    """
    facts: dict = {}

    # --- robots.txt ---
    # （原先这里有个遍历 robots._parsers 的循环，循环体只有 pass，
    #  读的 _origin_hint 全库从未被写过——纯死代码，已删。）
    robots_client = getattr(crawler.robots, "_client", None)
    facts["robots_url"] = None
    facts["robots_status"] = None
    facts["robots_directives"] = []

    # 重新请求一次 robots.txt 只为拿状态码与原文解析——请求已在 robots 检查中做过，
    # 这里直接读缓存的 parser 内部状态不可靠，故重新取一次（每个站点仅一次）。
    try:
        from urllib.parse import urlparse as _up

        origin_guess = None
        sm = getattr(crawler, "sitemap_result", None)
        if sm is not None and sm.sources:
            origin_guess = f"{_up(sm.sources[0]).scheme}://{_up(sm.sources[0]).netloc}"
        if origin_guess:
            r = httpx.get(
                f"{origin_guess}/robots.txt",
                timeout=10,
                follow_redirects=True,
                headers={"User-Agent": crawler.config.user_agent},
            )
            facts["robots_url"] = f"{origin_guess}/robots.txt"
            facts["robots_status"] = r.status_code
            if r.status_code == 200:
                facts["robots_directives"] = _parse_robots_directives(r.text)
    except Exception:  # noqa: BLE001
        pass

    # --- sitemap ---
    sm = getattr(crawler, "sitemap_result", None)
    if sm is not None:
        facts["sitemap_found"] = sm.found
        facts["sitemap_url_count"] = len(sm.urls)
        facts["sitemap_sources"] = sm.sources
        facts["sitemap_error"] = sm.error
        facts["sitemap_truncated"] = sm.truncated
        # 试过的路径。规则侧的 evidence 靠它证明「确实去试过」——
        # 这个键此前**从来没被填过**，所以 tried_paths 恒为 []，
        # 看起来像「没试就判没有」。
        facts["sitemap_tried"] = sm.tried

    return facts


def _parse_robots_directives(text: str) -> list[tuple[str, list[str]]]:
    """把 robots.txt 解析成 [(user_agent, [该 UA 下的规则行])]。"""
    out: list[tuple[str, list[str]]] = []
    current_agents: list[str] = []
    current_rules: list[str] = []

    def flush() -> None:
        if current_agents:
            for agent in current_agents:
                out.append((agent.lower(), list(current_rules)))

    for raw_line in text.splitlines():
        line = raw_line.split("#")[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            if current_agents and current_rules:
                flush()
                current_rules = []
            current_agents = [value]
        elif key in ("allow", "disallow", "crawl-delay"):
            current_rules.append(f"{key}: {value}")
    flush()
    return out


def cmd_rules(args: argparse.Namespace) -> int:
    registry = default_registry()
    # 用全部市场过滤，不写死清单：漏一个市场就会让它的规则「已注册但看不见」，
    # 排查起来很费时间（cnh_eco 就踩过这个坑）。
    all_markets = list(Market)
    page_rules = registry.page_rules_for(all_markets)
    site_rules = registry.site_rules_for(all_markets)
    print(f"已加载 {len(page_rules)} 条页面级规则 + {len(site_rules)} 条站点级规则\n")
    for label, rules in (("页面级", page_rules), ("站点级", site_rules)):
        print(f"── {label} ──")
        for r in sorted(rules, key=lambda x: (x.severity.rank, x.code)):
            print(f"  {r.severity.value:<8} {r.code:<24} {r.title}")
        print()
    print("注：另有实验性规则包 geo（AI 搜索引用性，4 条），证据强度弱于以上规则，")
    print("    默认不加载。点名启用：--market geo")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """构造参数解析器。

    刻意独立成函数而不是内联在 ``main()``：``--db`` 这类参数要能被
    单测直接断言（默认关闭、不给时不落库），不必跑整条命令。
    """
    parser = argparse.ArgumentParser(prog="seoclaw", description="SEO-Claw —— 站点 SEO 体检")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__import__('seoclaw').__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="扫描站点并生成报告")
    scan.add_argument("url", help="目标站点，如 https://example.com")
    scan.add_argument("--max-pages", type=int, default=100)
    scan.add_argument("--max-depth", type=int, default=6)
    scan.add_argument("--rps", type=float, default=3.0, help="单域每秒请求数")
    scan.add_argument("--market", action="append", default=["base"],
                      choices=[m.value for m in Market] + ["geo"],
                      help="可重复指定。base/google/baidu/cnh_eco 为常规规则包；"
                           "geo 为实验性包（AI 搜索引用性，证据强度较弱，不加载进默认扫描）")
    scan.add_argument("--output", "-o", help="报告输出路径（Markdown）")
    scan.add_argument("--json", action="store_true", help="输出 JSON")
    scan.add_argument("--checkpoint", help="断点续传目录")
    scan.add_argument("--ignore-robots", action="store_true", help="⚠️ 忽略 robots.txt，仅限你自有站点调试")
    scan.add_argument("--no-verify-canonical", action="store_true",
                      help="跳过 canonical 目标回访（会少一批请求）")
    scan.add_argument("--no-verify-og-image", action="store_true",
                      help="跳过 og:image 回访（会少一批请求；跳过则分享卡片类问题不报）")
    scan.add_argument("--adaptive-backoff", dest="adaptive_backoff", action="store_true", default=True,
                      help="遇 429/403 自动降速（默认开启）")
    scan.add_argument("--no-adaptive-backoff", dest="adaptive_backoff", action="store_false",
                      help="关闭自动降速")
    scan.add_argument("--render-js", action="store_true",
                      help="对疑似 SPA 空壳页执行 JS 渲染（慢 10~50 倍，需已装浏览器）")
    scan.add_argument("--render-timeout", type=float, default=20.0,
                      help="单页渲染超时秒数（默认 20，仅在开启 --render-js 时生效）")
    scan.add_argument("--quiet", "-q", action="store_true")
    scan.add_argument("--html", help="HTML 报告输出路径（单文件、无外链、可离线打开）")
    scan.add_argument("--llm-summary", action="store_true",
                      help="用 LLM 生成报告的 AI 总结段落（需配置 API key；失败不影响报告本身）")
    scan.add_argument("--proxy", action="append", default=[], metavar="URL",
                      help="代理池条目，可重复（http://user:pass@host:port）。"
                           "被 403/429 封禁时自动轮换到下一个")
    scan.add_argument("--proxy-file", help="代理列表文件，每行一个（# 开头为注释）")
    scan.add_argument("--incremental", action="store_true",
                      help="增量扫描：带 ETag/Last-Modified 条件请求，服务器回 304 的页面跳过规则重跑"
                           "（需要 --checkpoint 提供上一轮快照）")
    scan.add_argument("--db", metavar="PATH_OR_URL",
                      help="把本次扫描结果落库。给 SQLite 文件路径（如 seo.db）"
                           "或直接给 DATABASE_URL（如 postgresql+asyncpg://...）；"
                           "不给则只出报告、不写库")
    scan.set_defaults(func=cmd_scan)

    rules = sub.add_parser("rules", help="列出已加载的检查项")
    rules.set_defaults(func=cmd_rules)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
