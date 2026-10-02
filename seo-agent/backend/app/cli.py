#!/usr/bin/env python3
"""
SEO Agent CLI —— M0 入口。

用法：
    python -m app.cli scan https://example.com --max-pages 200
    python -m app.cli scan example.com --max-pages 50 --market google --json
    python -m app.cli rules          # 列出已加载的检查项
"""

from __future__ import annotations

import argparse
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
    markets = [Market(m) for m in args.market]

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
    print(f"  上限 {cfg.max_pages} 页 · 单域 {cfg.per_domain_rps} req/s · 市场 {[m.value for m in markets]}", file=sys.stderr)

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
    site_facts["hit_page_limit"] = bool(
        getattr(crawler, "aborted_reason", None) or len(pages) >= cfg.max_pages
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
                             incremental=bool(args.incremental))
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

    if args.json:
        payload = report.model_dump(mode="json")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        md = render_markdown(report, pages)
        if args.output:
            out_path = Path(args.output)
            # 输出目录可能不存在（第一次就踩过：扫描跑完 60 页却因目录不存在丢结果）
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(md, encoding="utf-8")
            print(f"→ 报告已写入 {args.output}", file=sys.stderr)
        if not args.quiet:
            print(md)

    if not args.json and not args.quiet:
        print(summarize_console(report))
    return 0


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
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="seo-agent", description="AI SEO Agent")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="扫描站点并生成报告")
    scan.add_argument("url", help="目标站点，如 https://example.com")
    scan.add_argument("--max-pages", type=int, default=100)
    scan.add_argument("--max-depth", type=int, default=6)
    scan.add_argument("--rps", type=float, default=3.0, help="单域每秒请求数")
    scan.add_argument("--market", action="append", default=["base"],
                      choices=[m.value for m in Market], help="可重复指定")
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
    scan.add_argument("--proxy", action="append", default=[], metavar="URL",
                      help="代理池条目，可重复（http://user:pass@host:port）。"
                           "被 403/429 封禁时自动轮换到下一个")
    scan.add_argument("--proxy-file", help="代理列表文件，每行一个（# 开头为注释）")
    scan.add_argument("--incremental", action="store_true",
                      help="增量扫描：带 ETag/Last-Modified 条件请求，服务器回 304 的页面跳过规则重跑"
                           "（需要 --checkpoint 提供上一轮快照）")
    scan.set_defaults(func=cmd_scan)

    rules = sub.add_parser("rules", help="列出已加载的检查项")
    rules.set_defaults(func=cmd_rules)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
