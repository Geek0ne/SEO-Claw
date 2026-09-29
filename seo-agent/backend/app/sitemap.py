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
from dataclasses import dataclass, field
from typing import Optional
from xml.etree import ElementTree as ET

import httpx

# sitemap index 递归上限与总 URL 上限，防止恶意/异常 sitemap 拖垮扫描
MAX_INDEX_DEPTH = 3
MAX_SITEMAP_FILES = 50
MAX_URLS = 20_000

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

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "SitemapFinder":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def discover(self, base_url: str) -> SitemapResult:
        """按 声明 → 常见路径 的顺序找 sitemap。"""
        result = SitemapResult()
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
        if depth > MAX_INDEX_DEPTH:
            return False
        try:
            resp = self._client.get(url)
        except httpx.HTTPError:
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
