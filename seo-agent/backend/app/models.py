"""
领域模型 —— 项目的「单一真相源」。

这些 Pydantic 模型同时用于：
  1. 爬虫的解析产物
  2. 规则引擎的输入输出
  3. FastAPI 的 API schema
  4. LLM 结构化输出的契约（instructor）
  5. JSON Schema 自动导出给前端生成 TS 类型

因此这里的字段命名要格外谨慎：一旦定错，后面数据库、API、前端全要跟着改。
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------
# 枚举
# --------------------------------------------------------------------------


class Market(str, Enum):
    """搜索引擎生态。规则按此分包。"""

    BASE = "base"  # 通用规则，所有站点都跑
    GOOGLE = "google"
    BAIDU = "baidu"
    CNH_ECO = "cnh_eco"  # 微信/小红书/知乎等中文生态扩展


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

    @property
    def rank(self) -> int:
        """数字越小越严重，用于排序与去重。"""
        return _SEVERITY_RANK[self]


_SEVERITY_RANK: dict[Severity, int] = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
    Severity.INFO: 4,
}


class Scope(str, Enum):
    """规则的执行作用域。"""

    PAGE = "page"  # 抓完一页就能判
    SITE = "site"  # 需要全站数据才能判（如重复 title、孤岛页）


class LinkKind(str, Enum):
    INTERNAL = "internal"
    EXTERNAL = "external"


# --------------------------------------------------------------------------
# 抓取产物
# --------------------------------------------------------------------------


class ImageRef(BaseModel):
    src: str
    alt: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None


class LinkRef(BaseModel):
    href: str
    anchor: str = ""
    kind: LinkKind = LinkKind.EXTERNAL
    nofollow: bool = False
    # 抓取阶段回填：内链目标最终状态码（None = 未抓）
    target_status: Optional[int] = None


class Page(BaseModel):
    """一个 URL 的抓取与解析结果。规则引擎的唯一输入。"""

    # --- 身份与抓取元信息 ---
    url: str
    site_id: Optional[int] = None
    final_url: Optional[str] = None  # 跟随重定向后的地址
    status_code: int = 0
    content_type: str = ""
    elapsed_ms: Optional[int] = None
    depth: int = 0  # 距首页的点击深度
    discovered_from: Optional[str] = None
    fetched_at: Optional[datetime] = None

    # --- SEO 元数据 ---
    title: Optional[str] = None
    meta_description: Optional[str] = None
    canonical: Optional[str] = None
    robots_meta: Optional[str] = None
    viewport: Optional[str] = None
    lang: Optional[str] = None

    # --- 多语言 / 社交分享 ---
    # 补这两组字段是被两个规则子任务同时卡住后的决定：没有它们，
    # hreflang 与 og:* 类规则只能靠猜，是「死规则」——要么永不触发，
    # 要么乱触发。数据层不支持的规则，写出来比不写更糟。
    # hreflang: [(lang_code, href)]，含 x-default
    hreflang: list[tuple[str, str]] = Field(default_factory=list)
    # Open Graph / Twitter Card，社交分享卡片的来源
    og_title: Optional[str] = None
    og_description: Optional[str] = None
    og_image: Optional[str] = None
    og_type: Optional[str] = None
    og_url: Optional[str] = None
    twitter_card: Optional[str] = None

    # --- 内容结构 ---
    h1: list[str] = Field(default_factory=list)
    headings: list[tuple[int, str]] = Field(default_factory=list)  # [(level, text)]
    text: str = ""  # 正文（trafilatura 抽取）
    word_count: int = 0
    # 全量可见文本字数（只去掉 script/style，导航与页脚都算在内）。
    #
    # 为什么需要它：text 来自 trafilatura，而 trafilatura **会主动剥掉
    # nav/footer/header**。于是「导航重」的页面 word_count 必然被压低——
    # japanpost.jp 首页剥后 74 词、含导航 1433 字符，那不是空页面。
    # 拿 word_count 判「这页是不是空的」是在用一把有偏的尺子量。
    # soft404 规则需要这个反向字段才能区分「真空」与「尺子量错了」。
    full_text_length: int = 0

    # --- 资源与链接 ---
    images: list[ImageRef] = Field(default_factory=list)
    links: list[LinkRef] = Field(default_factory=list)
    jsonld: list[dict[str, Any]] = Field(default_factory=list)
    microdata_types: list[str] = Field(default_factory=list)

    # --- 标记 ---
    is_html: bool = True
    error: Optional[str] = None

    # 供规则使用的派生信息（extract 阶段算好，避免每条规则重算）
    title_length: int = 0
    meta_description_length: int = 0
    has_mixed_content: bool = False
    mixed_content_samples: list[str] = Field(default_factory=list)
    # JS 渲染状态：rendered / disabled / unavailable / failed / not_needed
    # 规则靠它区分「检查过且没问题」与「根本没检查到」——这两者不能混为一谈。
    render_status: Optional[str] = None
    content_is_thin: bool = False
    internal_link_count: int = 0
    # 正文是否靠 JS 客户端渲染（静态 HTML 里看不到真内容）。
    #
    # ⚠️ 没有这个标记，soft404 规则会把「没渲染出来」当成「页面是空的」：
    # agoda.com 一个 733KB 的页面，静态可见文本 0 字，判成
    # likely_true_soft404 + HIGH，用户收到「高危：你这页是空页面」——
    # 去改一个内容饱满的电商首页。规则层光看 word_count=0 分不出来
    # 「这页没内容」和「这页内容我看不见」，必须提取层把事实给它。
    likely_js_rendered: bool = False
    external_link_count: int = 0


# --------------------------------------------------------------------------
# 问题（规则引擎输出）
# --------------------------------------------------------------------------


class Issue(BaseModel):
    """一条 SEO 问题。

    `evidence` 是产品最核心的信任机制：任何结论都必须能被点开验证。
    """

    code: str
    severity: Severity
    market: Market = Market.BASE
    scope: Scope = Scope.PAGE

    url: Optional[str] = None  # page 级规则必填
    title: str = ""  # 人类可读的中文问题名
    description: str = ""  # 问题解释 + 为什么有害
    fix_hint: str = ""  # 怎么修（可执行的建议）
    fix_example: Optional[str] = None  # 可复制的代码/配置片段
    evidence: dict[str, Any] = Field(default_factory=dict)  # 支撑该结论的原始数据

    def dedup_key(self) -> tuple[str, str | None]:
        """同一 code + 同一 URL 只保留最严重的一条。"""
        return (self.code, self.url)


class SiteReport(BaseModel):
    """全站扫描的最终产物。"""

    site_id: Optional[int] = None
    domain: str
    markets: list[Market] = Field(default_factory=lambda: [Market.BASE])
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = None

    pages_crawled: int = 0
    pages_discovered: int = 0
    duration_seconds: Optional[float] = None

    health_score: Optional[float] = None
    score_breakdown: dict[str, Any] = Field(default_factory=dict)
    issues: list[Issue] = Field(default_factory=list)

    @property
    def issues_by_severity(self) -> dict[Severity, list[Issue]]:
        out: dict[Severity, list[Issue]] = {s: [] for s in Severity}
        for issue in self.issues:
            out[issue.severity].append(issue)
        return out
