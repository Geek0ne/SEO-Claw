"""
Sitemap 发现与解析。

为什么必须有：孤岛页检测依赖「sitemap 里有、但站内无入链」的页面。
爬虫只从首页 BFS 的话，抓到的页面必然有入链，孤岛页规则永远不会触发。
sitemap 是唯一能发现这类页面的来源（外链流量入口同理）。

支持：
  - robots.txt 里的 Sitemap: 声明（优先，符合规范）
  - /sitemap.xml、/sitemap_index.xml 等常见路径兜底
  - sitemap index 递归展开（带深度与总量上限，防 sitemap bomb）
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Optional
from xml.etree import ElementTree as ET

import httpx

# sitemap index 递归上限与总 URL 上限，防止恶意/异常 sitemap 拖垮扫描
MAX_INDEX_DEPTH = 3
MAX_SITEMAP_FILES = 50
MAX_URLS = 20_000

# ⚠️ 墙钟预算：递归必须有**整体**时限，不能只靠每请求的 timeout。
#
# 真实踩坑：www.energy.gov 的 /sitemap.xml 是 sitemapindex（6.5KB / 50 条子
# loc），每个子文件一个 HTTP 请求，单请求 timeout 15s。最坏 50 × 15s = 750s，
# 远超单站扫描的 300s 预算——结果不是报错，是**静默卡住**：进程活着、
# 没有 traceback、最终被外部 timeout 杀掉，报告里只留一句 FAIL。
#
# 只看深度和文件数上限是防不住这类的：深度 1、文件 50，都「合法」，
# 但 50 × 单请求超时就足以拖垮整次扫描。而这类站恰恰是政府/大型企业站，
# sitemap 分片是通行做法，不是异常。
#
# 超预算时截断而不是抛异常：sitemap 只是孤岛页检测的播种源，拿到一部分
# URL 就能用，为它把整次扫描搞失败不划算。truncated=True 会如实报出来。
SITEMAP_TIME_BUDGET = 25.0

# 子 sitemap 的**尝试**次数上限（含失败）。与 MAX_SITEMAP_FILES 互补：
# 后者数「成功读到几个文件」，前者数「尝试了几次」。两者都得有——
# 只有前者时，遇到大量失败的子文件就漏过去了（energy.gov 实测 2000 次）。
MAX_CHILD_ATTEMPTS = 200

_COMMON_PATHS = (
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/sitemap-index.xml",
    "/sitemap/sitemap.xml",
    "/sitemap.txt",
)

_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)
_SITEMAP_RE = re.compile(r"^\s*sitemap:\s*(\S+)", re.IGNORECASE | re.MULTILINE)


@dataclass
class SitemapResult:
    found: bool = False
    urls: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)  # 实际读取到的 sitemap 地址
    # 每次尝试过的路径及其结果。sitemap.missing 的 evidence 要靠它证明
    # 「确实去试了」——空列表会和「根本没试」长得一模一样。
    tried: list[dict] = field(default_factory=list)
    error: Optional[str] = None
    truncated: bool = False


class SitemapFinder:
    def __init__(self, user_agent: str, timeout: float = 15.0) -> None:
        self._ua = user_agent
        self._timeout = timeout
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": user_agent},
        )
        # discover() 每次调用重置
        self._deadline: float | None = None
        # ⚠️ 已经**尝试**过的子 sitemap 数。与 result.sources 分开：
        # sources 只在 _load 返回 True 时才追加，而失败的子文件一个都不计数。
        # 踩过：www.energy.gov 的 /sitemap.xml?page=1 根元素是
        # <sitemapindex>，但 2000 条 <loc> 全是文章页。代码信了根元素，
        # 逐个去当子 sitemap 抓，每次 0.4-1s 全返回 False（它们是 HTML），
        # 于是 sources 永远是 0、MAX_SITEMAP_FILES=50 这道闸**一次都没生效**，
        # 2000 次请求就这么漏过去，把整次扫描拖死。
        # 按尝试次数计上限，才管得住「大量失败」这种情况。
        self._child_attempts = 0

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "SitemapFinder":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def discover(self, base_url: str) -> SitemapResult:
        """按 声明 → 常见路径 的顺序找 sitemap。"""
        result = SitemapResult()
        self._deadline = time.monotonic() + SITEMAP_TIME_BUDGET
        self._child_attempts = 0
        candidates = self._candidates(base_url)
        if not candidates:
            result.error = "no_robots_no_common_path"
            return result

        for url in candidates:
            if len(result.sources) >= MAX_SITEMAP_FILES:
                result.truncated = True
                break
            if len(result.urls) >= MAX_URLS:
                result.truncated = True
                break
            found = self._load(url, result, depth=0)
            if found:
                result.sources.append(url)
        result.found = bool(result.urls)
        return result

    def _candidates(self, base_url: str) -> list[str]:
        origin = base_url.rstrip("/")
        candidates: list[str] = []
        robots_url = f"{origin}/robots.txt"
        try:
            resp = self._client.get(robots_url)
            if resp.status_code == 200:
                # robots.txt 里显式声明的优先级最高
                candidates.extend(_SITEMAP_RE.findall(resp.text))
        except httpx.HTTPError:
            pass
        candidates.extend(f"{origin}{p}" for p in _COMMON_PATHS)

        # 去重并保持优先级顺序
        seen: set[str] = set()
        out: list[str] = []
        for c in candidates:
            if c not in seen:
                seen.add(c)
                out.append(c)
        return out

    def _load(self, url: str, result: SitemapResult, depth: int) -> bool:
        """记录一次尝试后委托 _load_inner。

        ⚠️ 记录点必须在这里、而不是只写在内层成功分支上。
        _load_inner 有 5 个 early return（非 200、超时、HTTP 错误、
        没有 <loc>、递归超限），只在成功时记录等于**绝大多数尝试都不留痕**——
        而恰恰是这些「试了但没找到」才是 sitemap.missing 的关键证据。
        早踩过：`tried_paths` 是从 site_facts 里读的，但 site_facts 从来
        没被填过这个键，所以证据恒为 `[]`，看起来像「没试就判没有」。
        """
        self._last_status: Optional[int] = None
        self._last_error: Optional[str] = None
        try:
            ok = self._load_inner(url, result, depth)
        except Exception as exc:  # noqa: BLE001 — 单个 sitemap 读不动不该毁掉整次探测
            self._last_error = type(exc).__name__
            ok = False
        result.tried.append({
            "url": url,
            "depth": depth,
            "status": self._last_status,
            "ok": bool(ok),
            "error": self._last_error,
        })
        return ok

    def _load_inner(self, url: str, result: SitemapResult, depth: int) -> bool:
        if depth > MAX_INDEX_DEPTH:
            return False
        if self._deadline is not None and time.monotonic() > self._deadline:
            result.truncated = True
            return False
        try:
            resp = self._client.get(url)
            self._last_status = resp.status_code
        except httpx.HTTPError as exc:
            self._last_error = type(exc).__name__
            return False
        if resp.status_code != 200 or not resp.content:
            return False

        content = resp.text
        locs = _LOC_RE.findall(content)
        if not locs:
            return False

        # 区分 sitemap index（子文件里装 <sitemap><loc>）与普通 urlset
        is_index = "<sitemapindex" in content.lower() or (
            depth == 0 and all(not loc.endswith((".html", "/")) for loc in locs[:5])
        )

        if is_index:
            child_any = False
            for child in locs:
                if len(result.urls) >= MAX_URLS or len(result.sources) >= MAX_SITEMAP_FILES:
                    result.truncated = True
                    break
                # 墙钟预算：超时即停，不再往下递归。
                # 踩过：energy.gov 的 sitemapindex 有 50 个分片，只靠
                # MAX_SITEMAP_FILES 防不住——50 合法，但 50 × 15s 超时
                # 会让整次扫描静默卡死。详见 SITEMAP_TIME_BUDGET 注释。
                if self._deadline is not None and time.monotonic() > self._deadline:
                    result.truncated = True
                    break
                # 按**尝试次数**计，不按成功次数。sources 只统计成功返回的
                # 文件，大量失败时这道闸形同虚设——见 _child_attempts 注释。
                self._child_attempts += 1
                if self._child_attempts > MAX_CHILD_ATTEMPTS:
                    result.truncated = True
                    break
                if self._load(child, result, depth + 1):
                    child_any = True
            return child_any

        for loc in locs:
            if len(result.urls) >= MAX_URLS:
                result.truncated = True
                break
            if loc not in result.urls:
                result.urls.append(loc)
        return True
