"""
爬虫调度器。

M0 阶段刻意做简单：同步 + 内存 frontier + 磁盘 checkpoint。
设计成可替换的接口，M1 接 Redis frontier、M2 水平扩展时不用改调用方。

关键约束（合规与稳定性）：
  - 遵守 robots.txt（可配置，默认遵守）
  - 单域限速（默认 3 req/s）
  - 明确的 User-Agent 声明身份
  - 断点续跑：中断后重启能接着抓
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.robotparser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

from .extract import extract_page
from .models import Page
from .render import RenderConfig, Renderer
from .sitemap import SitemapFinder
from .util import is_internal, normalize_url

DEFAULT_UA = (
    "Mozilla/5.0 (compatible; SEOAgentBot/0.1; +https://example.com/bot) "
    "Python-httpx"
)


@dataclass
class CrawlConfig:
    """爬取行为配置。默认值刻意保守，避免把别人的站打挂。"""

    max_pages: int = 1000
    max_depth: int = 6
    per_domain_rps: float = 3.0  # 单域每秒请求数
    total_rps: float = 20.0  # 全局每秒请求数
    timeout: float = 20.0
    respect_robots: bool = True
    user_agent: str = DEFAULT_UA
    use_sitemap: bool = True  # 从 sitemap.xml 播种，才能发现孤岛页
    # 遇到 429/403 时自动降速到 rps/adaptive_divisor；
    # 连续触发则再退避。这能避免把对方案前限流规则打崩。
    adaptive_backoff: bool = True
    adaptive_divisor: float = 4.0
    backoff_base_seconds: float = 2.0
    backoff_max_seconds: float = 60.0
    max_html_bytes: int = 5 * 1024 * 1024  # 单页最大 5MB，防止超大文件
    include_www_variants: bool = False

    # --- JS 渲染 ---
    # 默认关闭：渲染比静态抓取慢 10~50 倍，且要占几百 MB 浏览器内存。
    # 只在用户明确开启时生效。
    render_js: bool = False
    # 启发式：静态 HTML 里「链接极少 + 正文极少」才认为是需要渲染的 SPA 页。
    # 无条件渲染全部页面会让一次扫描从 1 分钟变成 30 分钟，不可接受。
    render_link_threshold: int = 3
    render_word_threshold: int = 100
    # 探测到需要渲染的页面比例上限：站点整体是 SPA 时，超过这个比例就放弃
    # 渲染并提示用户，否则会安静地跑几小时。
    render_probe_ratio_limit: float = 0.5
    # 已知无 SEO 价值的路径，直接跳过，能省掉大量抓取
    skip_path_patterns: tuple[str, ...] = (
        "/login", "/signin", "/register", "/signup", "/cart", "/checkout",
        "/logout", "/admin", "/wp-admin", "/wp-login", "/api/", "/feed",
        "/rss", "/tag/", "/author/", "/search", "/account", "/static/",
    )


class RateLimiter:
    """双层限速：单域 + 全局。用滑动窗口实现，够用且无依赖。

    支持运行时降速：对方返回 429/403 时调用 slow_down()，
    把单域速率降一个档位，后续再逐步恢复。
    比一开始就上很慢的速度好——快失败、快降速，而不是先挨打再反应。
    """

    def __init__(
        self,
        per_domain_rps: float,
        total_rps: float,
        adaptive_divisor: float = 4.0,
    ) -> None:
        self.base_per_domain_rps = max(per_domain_rps, 0.1)
        self.per_domain_rps = self.base_per_domain_rps
        self.total_rps = max(total_rps, 0.1)
        self.adaptive_divisor = max(adaptive_divisor, 1.0)
        self.total_interval = 1.0 / self.total_rps
        self._interval = 1.0 / self.per_domain_rps
        self._last_domain: dict[str, float] = {}
        self._last_global: float = 0.0
        self._penalty_until: float = 0.0  # 退避到期前的暂停时间点
        self.slow_down_count = 0

    @property
    def current_interval(self) -> float:
        return self._interval

    def slow_down(self) -> None:
        """被限流后降速一个档位。"""
        self.slow_down_count += 1
        self.per_domain_rps = max(self.per_domain_rps / self.adaptive_divisor, 0.05)
        self._interval = 1.0 / self.per_domain_rps

    def penalize(self, seconds: float) -> None:
        """强制暂停一段时间（收到 Retry-After 时用）。"""
        self._penalty_until = max(self._penalty_until, time.monotonic() + seconds)

    def wait(self, domain: str) -> None:
        now = time.monotonic()
        if now < self._penalty_until:
            time.sleep(self._penalty_until - now)
            now = time.monotonic()

        domain_gap = now - self._last_domain.get(domain, 0.0)
        if domain_gap < self._interval:
            time.sleep(self._interval - domain_gap)
        now = time.monotonic()
        global_gap = now - self._last_global
        if global_gap < self.total_interval:
            time.sleep(self.total_interval - global_gap)
        self._last_domain[domain] = time.monotonic()
        self._last_global = time.monotonic()


class RobotsCache:
    """按域缓存 robots.txt。每个域只请求一次。

    同时解析 robots.txt 里的 Crawl-delay（Google 不认，但很多站用它表达意愿），
    对被限流过的域额外尊重它。
    """

    def __init__(self, user_agent: str, timeout: float = 15.0) -> None:
        self._parsers: dict[str, Optional[urllib.robotparser.RobotFileParser]] = {}
        self._delays: dict[str, float] = {}
        self._ua = user_agent
        self._timeout = timeout

    def crawl_delay(self, origin: str) -> Optional[float]:
        return self._delays.get(origin)

    def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._parsers:
            self._parsers[origin] = self._load(origin)
        rp = self._parsers[origin]
        if rp is None:
            return True  # 拿不到 robots 时按允许处理，但要记录
        try:
            return rp.can_fetch(self._ua, url)
        except Exception:  # noqa: BLE001
            return True

    def _load(self, origin: str) -> Optional[urllib.robotparser.RobotFileParser]:
        rp = urllib.robotparser.RobotFileParser()
        try:
            with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
                resp = client.get(f"{origin}/robots.txt", headers={"User-Agent": self._ua})
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
                delay = _parse_crawl_delay(resp.text, self._ua)
                if delay:
                    self._delays[origin] = delay
                return rp
            if resp.status_code in (401, 403):
                # 明确拒绝：保守处理为全部禁止
                rp.parse(["User-agent: *", "Disallow: /"])
                return rp
        except Exception:  # noqa: BLE001
            return None
        # 404 / 其他状态视为无限制
        rp.parse([])
        return rp


_DELAY_RE = re.compile(r"^\s*crawl-delay\s*:\s*([\d.]+)", re.IGNORECASE | re.MULTILINE)


def _parse_crawl_delay(robots_text: str, user_agent: str) -> Optional[float]:
    """粗略解析 Crawl-delay。robots.txt 分组较复杂，这里取全局最小值作为保守值。"""
    values = [float(m) for m in _DELAY_RE.findall(robots_text)]
    if not values:
        return None
    return min(values)


class Crawler:
    """同步爬虫。M0 够用，M1 换 async + Redis 不影响调用方。"""

    def __init__(self, config: Optional[CrawlConfig] = None, checkpoint_dir: Optional[Path] = None) -> None:
        self.config = config or CrawlConfig()
        self.checkpoint_dir = checkpoint_dir
        # pages.jsonl 里已经成功落盘的条数，续写时只追加新增的那些
        self._pages_persisted = 0
        self.limiter = RateLimiter(
            self.config.per_domain_rps,
            self.config.total_rps,
            self.config.adaptive_divisor,
        )
        # 渲染器惰性创建：不开渲染时不该为一个用不到的浏览器付出几百 MB 内存
        self._renderer: Optional[Renderer] = None
        if self.config.render_js:
            self._renderer = Renderer.instance(
                RenderConfig(enabled=True, timeout_ms=int(self.config.timeout * 1000))
            )
        self.robots = RobotsCache(self.config.user_agent, self.config.timeout)
        self.sitemap_result = None  # 由 crawl() 填充
        self.aborted_reason: Optional[str] = None  # 熔断中止时的原因
        self.client = httpx.Client(
            timeout=self.config.timeout,
            follow_redirects=True,
            headers={
                "User-Agent": self.config.user_agent,
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "Crawler":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- 主流程 -----------------------------------------------------------

    def _discover_sitemap(self, origin: str) -> list[str]:
        """找 sitemap 并返回 URL 列表。

        孤岛页检测依赖这一步：不从 sitemap 播种的话，只从首页 BFS
        抓到的页面必然都有入链，孤岛页规则永远不会触发。
        """
        if not self.config.use_sitemap:
            return []
        try:
            with SitemapFinder(self.config.user_agent, self.config.timeout) as finder:
                result = finder.discover(origin)
        except Exception:  # noqa: BLE001 — sitemap 不可用不该让整次扫描失败
            return []

        self.sitemap_result = result
        if not result.found:
            return []
        # 只保留本站的 URL，外站 sitemap 不处理
        domain = urlparse(origin).netloc
        return [u for u in result.urls if is_internal(u, domain)]

    def crawl(self, start_url: str, on_page: Optional[object] = None) -> list[Page]:
        """从 start_url 开始 BFS 抓取，返回解析后的页面列表。"""
        cfg = self.config
        start = _canonicalize(start_url)
        domain = urlparse(start).netloc
        origin = f"{urlparse(start).scheme}://{domain}"

        visited: set[str] = set()
        # ⚠️ 续跑必须同时拿回 frontier 和已解析的 pages：
        # 只拿 visited 会让种子自己命中 visited（normalize 后 key 相同），
        # frontier 一开始就空，续跑报告全空——实测踩过。
        ckpt = self._load_checkpoint(domain)

        sitemap_urls = self._discover_sitemap(origin)

        frontier: list[tuple[str, int, Optional[str]]] = []
        pages: list[Page] = []
        if ckpt:
            visited.update(ckpt["visited"])
            for item in ckpt["frontier"]:
                if len(item) >= 2:
                    frontier.append((item[0], int(item[1]), item[2] if len(item) > 2 else None))
            for raw in ckpt["pages"]:
                try:
                    pages.append(Page.model_validate(raw))
                except Exception:  # noqa: BLE001 — 单条坏数据不该毁掉整份续跑
                    continue
        # frontier 为空（首次跑、或旧版纯文本 checkpoint）才重新播种
        if not frontier:
            frontier.append((start, 0, None))
        discovered = 1 + len(visited)
        self.discovered_count = 1  # 爬取中途异常退出时也有值可读
        # 连续连接失败计数：达到阈值说明对方在按 IP 限流/拉黑，继续打只会让封禁更久
        consecutive_errors = 0
        consecutive_error_limit = 5

        # sitemap 里的 URL 作为深度 1 的种子入队：它们可能完全没有入链
        for url in sitemap_urls:
            if normalize_url(url) in visited:
                continue
            frontier.append((url, 1, start))
            discovered += 1
        while frontier and len(pages) < cfg.max_pages:
            url, depth, parent = frontier.pop(0)
            key = normalize_url(url)
            if key in visited:
                continue
            visited.add(key)

            if depth > cfg.max_depth:
                continue
            if cfg.respect_robots and not self.robots.allowed(url):
                continue
            if self._should_skip(url):
                continue

            self.limiter.wait(domain)
            page = self._fetch(url, depth=depth, discovered_from=parent)

            if page is not None and self.config.adaptive_backoff:
                # 被限流的表现：429 / 403，或直接连接被拒
                blocked = page.status_code in (403, 429) or (
                    page.error and page.error.startswith("http_error")
                )
                if blocked:
                    self.limiter.slow_down()
                    retry_after = 0.0
                    if page.status_code == 429:
                        retry_after = 10.0  # 保守起见，不猜对方的 Retry-After
                    if retry_after:
                        self.limiter.penalize(retry_after)
                    print(
                        f"⚡ 被限流（HTTP {page.status_code}），单域速率已降至 "
                        f"{self.limiter.per_domain_rps:.2f} req/s",
                        file=sys.stderr,
                    )

            if page is None:
                continue
            pages.append(page)

            if page.error and page.error.startswith(("http_error", "timeout")):
                consecutive_errors += 1
                if consecutive_errors >= consecutive_error_limit:
                    print(
                        f"⚠️ 连续 {consecutive_errors} 次请求失败，已中止本域扫描。\n"
                        f"   常见原因：对方按 IP 限流/封禁。继续请求只会延长封禁时间。",
                        file=sys.stderr,
                    )
                    self.aborted_reason = (
                        f"aborted_after_{consecutive_errors}_consecutive_failures"
                    )
                    break
            else:
                consecutive_errors = 0

            if on_page and callable(on_page):
                on_page(page, len(pages))  # type: ignore[operator]

            if page.is_html and not page.error and page.status_code == 200:
                for link in page.links:
                    if link.kind.value != "internal":
                        continue
                    lkey = normalize_url(link.href)
                    if lkey in visited:
                        continue
                    frontier.append((link.href, depth + 1, page.url))
                    discovered += 1

            if len(pages) % 25 == 0:
                self._save_checkpoint(domain, visited, frontier, pages)

        self._save_checkpoint(domain, visited, frontier, pages)
        self.discovered_count = discovered
        return pages

    def verify_canonical_targets(self, pages: list[Page], limit: int = 60) -> dict[str, int]:
        """回访 canonical 指向的外部目标，拿到它的 HTTP 状态码。

        目的：区分「canonical 指向一个不存在的地址」（真 bug，critical）
        与「canonical 指向另一个存在的页面」（可能是有意合并/版本别名）。

        只针对与自身不同的 canonical 目标去请求，且限量——避免多打一遍站点。
        返回 {归一化URL: 状态码}。
        """
        from .util import normalize_url

        targets: dict[str, str] = {}
        for page in pages:
            if not page.canonical or page.status_code != 200:
                continue
            key = normalize_url(page.canonical)
            if key == normalize_url(page.final_url or page.url):
                continue
            if key not in targets and len(targets) < limit:
                targets[key] = page.canonical

        result = self._probe_targets(targets)
        return result

    def _probe_targets(self, targets: dict[str, str]) -> dict[str, int]:
        """对 {归一化URL: 原始URL} 逐个探 HTTP 状态码，返回 {归一化URL: 状态码}。

        HEAD 不被支持时（403/405/501）退回 GET——很多 CDN/图床对 HEAD
        直接给 403，不退回就会把正常的图误判成「打不开」。
        请求失败记 0（区别于 404：连都没连上）。
        """
        result: dict[str, int] = {}
        for key, url in targets.items():
            self.limiter.wait(urlparse(url).netloc)
            try:
                resp = self.client.head(url)
                if resp.status_code in (403, 405, 501):  # HEAD 不被支持，退回 GET
                    resp = self.client.get(url)
                result[key] = resp.status_code
            except httpx.HTTPError:
                result[key] = 0
                if self.config.adaptive_backoff:
                    self.limiter.slow_down()
        return result

    def verify_og_image_targets(self, pages: list[Page], limit: int = 40) -> dict[str, int]:
        """回访 og:image，拿到 HTTP 状态码。

        og:image 指向的图打不开时，微信/微博等分享卡片会显示空白或占位图，
        看起来像站点坏了——但这**不影响排名**，所以规则侧是 INFO 而非高危。

        ⚠️ 之前这条回访**没人做**：`og_image_status` 只有规则侧在读，全库零
        写入，于是 `og:image.broken` 永远是条死规则——规则本身写得对
        （`status is None` 就不猜，不拿「没检查过」冒充「有问题」），
        但没人喂它数据，测试里手塞值就绿了，生产上永远不会触发。

        这与 sitemap 的 `tried_paths` 是同一类病：**证据链缺一环**，
        区别是这个是「规则永远沉默」，那个是「结论对但证据不支撑结论」。

        限量 40：图床通常在 CDN 上，一次扫描没必要把全站封面图都打一遍。
        """
        from .util import normalize_url

        targets: dict[str, str] = {}
        for page in pages:
            if not page.og_image or page.status_code != 200:
                continue
            key = normalize_url(page.og_image)
            if key not in targets and len(targets) < limit:
                targets[key] = page.og_image
        return self._probe_targets(targets)

    # -- 内部方法 ---------------------------------------------------------

    def _fetch(self, url: str, depth: int, discovered_from: Optional[str]) -> Optional[Page]:
        start = time.monotonic()
        try:
            resp = self.client.get(url)
        except httpx.TimeoutException:
            return Page(url=url, depth=depth, discovered_from=discovered_from,
                        error="timeout", is_html=False)
        except httpx.HTTPError as exc:
            # 连接被拒 / DNS 失败 / TLS 失败都归到这里。
            # 若同一域连续失败，通常是对方按 IP 限流或拉黑，
            # 此时应中止整域扫描而不是继续重试（见 crawl() 的连续失败熔断）。
            return Page(url=url, depth=depth, discovered_from=discovered_from,
                        error=f"http_error: {type(exc).__name__}: {exc}", is_html=False)

        elapsed = int((time.monotonic() - start) * 1000)
        if len(resp.content) > self.config.max_html_bytes:
            return Page(url=url, status_code=resp.status_code, depth=depth,
                        discovered_from=discovered_from, error="too_large", is_html=False)

        content_type = resp.headers.get("content-type", "")
        raw = resp.text if "text/" in content_type or "html" in content_type else ""

        page = extract_page(
            url=url,
            raw_html=raw,
            status_code=resp.status_code,
            content_type=content_type,
            final_url=str(resp.url),
            depth=depth,
            discovered_from=discovered_from,
            elapsed_ms=elapsed,
        )

        # JS 渲染：只在「静态 HTML 看起来是 SPA 空壳」时才做，不是每页都渲染。
        # 实测依据：go.dev 静态 HTML 里几乎没有 <a>，不开渲染只抓到 1 个 URL。
        if self.config.render_js and self._needs_render(page):
            rendered, status = self._render(url)
            page.render_status = status
            if rendered:
                rpage = extract_page(
                    url=url,
                    raw_html=rendered,
                    status_code=page.status_code,
                    content_type="text/html",
                    final_url=page.final_url or str(resp.url),
                    depth=depth,
                    discovered_from=discovered_from,
                    elapsed_ms=elapsed,
                )
                # 只有渲染后「链接或正文更丰富」才采纳，否则保留静态结果
                if (
                    rpage.internal_link_count > page.internal_link_count
                    or rpage.word_count > page.word_count
                ):
                    rpage.render_status = status
                    return rpage
        return page

    def _needs_render(self, page: Page) -> bool:
        """判断这个页面是否值得花一次浏览器渲染。

        ⚠️ 启发式必然有两类错：该渲染没渲染（漏报，但页面仍被静态分析）
        和不该渲染却渲染（变慢，有限成本）。两个错的方向都是安全的——
        宁可漏，也不要每页都渲染，那会让一次扫描从 1 分钟变成 30 分钟。
        """
        if not page.is_html or page.error or page.status_code != 200:
            return False
        return (
            page.internal_link_count <= self.config.render_link_threshold
            and page.word_count <= self.config.render_word_threshold
        )

    def _render(self, url: str) -> tuple[Optional[str], str]:
        """调用渲染器。渲染是增强能力，任何异常都不能让整个扫描失败。"""
        if self._renderer is None:
            return None, "disabled"
        try:
            return self._renderer.render(url)
        except Exception:  # noqa: BLE001
            return None, "failed"

    def _should_skip(self, url: str) -> bool:
        path = urlparse(url).path.lower()
        return any(pat in path for pat in self.config.skip_path_patterns)

    # -- 断点续传 ---------------------------------------------------------

    def _checkpoint_path(self, domain: str) -> Optional[Path]:
        if not self.checkpoint_dir:
            return None
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        safe = domain.replace("/", "_").replace(":", "_")
        return self.checkpoint_dir / f"{safe}.visited"

    def _load_checkpoint(self, domain: str) -> Optional[dict]:
        """读回上次中断时的 frontier / visited / 已解析页面。

        ⚠️ 之前这里只回填 visited，续跑必然抓回 0 页。实测：
        种子 https://www.w3.org/ 归一化后就是 "w3.org/"，它自己在
        visited 里 → frontier 一开始就空 → 报告全空。
        而且 frontier 丢了以后，光有 visited 也补不回来：frontier 是
        队列本身，没队列就无从续跑。所以三样都得存。

        兼容旧版纯文本格式（一行一个 visited key）：读成 visited，
        但此时 frontier 缺失，调用方必须重新播种。
        """
        path = self._checkpoint_path(domain)
        pages = self._load_pages(domain)
        self._pages_persisted = len(pages)
        if not path or not path.exists():
            # visited 丢了但 pages 还在：保���已解析结果，重新播种继续抓。
            # 全丢才算没有 checkpoint。
            return {"visited": [], "frontier": [], "pages": pages} if pages else None
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            return {"visited": [], "frontier": [], "pages": pages} if pages else None
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            # 旧版纯文本格式：每行一个 visited。frontier 缺失 → 调用方重新播种
            return {"visited": [ln.strip() for ln in raw.splitlines() if ln.strip()],
                    "frontier": [], "pages": pages}
        if not isinstance(data, dict):
            return {"visited": [], "frontier": [], "pages": pages} if pages else None
        # 兼容上一版把 pages 塞在同一个 JSON 里的格式
        inline = list(data.get("pages") or [])
        if inline and not pages:
            pages = inline
        return {
            "visited": list(data.get("visited") or []),
            "frontier": [tuple(x) for x in (data.get("frontier") or [])],
            "pages": pages,
        }

    def _pages_path(self, domain: str) -> Optional[Path]:
        """已解析页面的追加日志（JSONL）。与 .visited 分开，原因见 _save_checkpoint。"""
        path = self._checkpoint_path(domain)
        if not path:
            return None
        return path.with_name(path.name + ".pages.jsonl")

    def _load_pages(self, domain: str) -> list:
        """读回 pages.jsonl。

        追加写中途被 kill 会留下半截最后一行，所以**逐行解析、坏行跳过**，
        而不是整体 json.loads 失败就丢全部。半截行正是「刚好被杀」最常见的
        形态，在续跑场景下要能容下来。
        """
        ppath = self._pages_path(domain)
        if not ppath or not ppath.exists():
            return []
        out: list[dict] = []
        try:
            with ppath.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        continue  # 半截行
                    if isinstance(obj, dict):
                        out.append(obj)
        except OSError:
            return out
        return out

    def _save_checkpoint(self, domain: str, visited: set[str],
                         frontier: list, pages: list) -> None:
        """visited/frontier 小 → 原子重写；pages 大 → **只追加**。

        ⚠️ 上一版把三者放一个 JSON、每 25 页全量重写，实测抓 35 页时
        checkpoint 就到了 935KB，1000 页会变成 ~26MB 反复重写 40 次——
        「1000 页不崩」那条验收我自己差点做崩。根因是**全量重写**，
        不是数据量本身，所以拆成两个文件：小的照旧重写（要保证原子性），
        大的改成 JSONL 追加，写入量从 O(n²) 降到 O(n)。
        """
        path = self._checkpoint_path(domain)
        if path:
            payload = {
                "visited": sorted(visited),
                # parent 可能为 None；list→tuple 不行（JSON 存成 list），读回时再补
                "frontier": [[u, d, p] for (u, d, p) in frontier],
            }
            tmp = path.with_suffix(path.suffix + ".tmp")
            try:
                tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                tmp.replace(path)
            except OSError:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass

        ppath = self._pages_path(domain)
        if not ppath:
            return
        pending = pages[self._pages_persisted:]
        if not pending:
            return
        try:
            with ppath.open("a", encoding="utf-8") as f:
                for p in pending:
                    f.write(json.dumps(p.model_dump(mode="json"), ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
            self._pages_persisted += len(pending)
        except OSError:
            # 追加失败就停在原处：下次续跑会重写这些页（visited 里已有它们，
            # 所以不重复抓，只是这批解析结果没存上——比坏 checkpoint 强）
            pass


def _canonicalize(url: str) -> str:
    """补全协议、去掉 fragment 与末尾斜杠，作为起点规范化。"""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url.lstrip("/")
    parsed = urlparse(url)
    return urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path.rstrip("/") or "/", "", "", "")
    )
