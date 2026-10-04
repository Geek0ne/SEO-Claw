"""API 请求/响应模型。

刻意与 ORM 模型分开：ORM 字段随迁移演进，API 契约不能跟着内部重构一起变。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class SiteCreate(BaseModel):
    domain: str = Field(min_length=3, examples=["example.com"])
    markets: list[str] = Field(default_factory=lambda: ["base"])


class SiteOut(BaseModel):
    id: int
    domain: str
    markets: list[str]
    is_active: bool


class ScanRequest(BaseModel):
    """触发一次扫描。

    ``url`` 省略时用 ``scheme://domain`` 作种子。
    """

    url: Optional[str] = None
    max_pages: int = Field(default=100, ge=1, le=5000)
    max_depth: int = Field(default=6, ge=0, le=20)
    per_domain_rps: float = Field(default=3.0, gt=0, le=50)
    markets: Optional[list[str]] = None
    incremental: bool = False
    checkpoint_dir: Optional[str] = None
    respect_robots: bool = True
    render_js: bool = False


class JobOut(BaseModel):
    id: int
    site_id: int
    status: str
    url_count: int
    pages_crawled: int
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class IssueOut(BaseModel):
    id: int
    code: str
    severity: str
    scope: str
    url: Optional[str] = None
    title: str
    fingerprint: Optional[str] = None
    status: str
    occurrences: int = 1


class IssueStatusIn(BaseModel):
    """改一条问题的状态（「这条我改了」）。

    ⚠️ 用 Literal 约束取值而不是裸 str：写错 ``"fixed "``（带空格）或
    ``"done"`` 时，应当在**校验层**就 422，而不是掉进 SQL 才炸成 500。
    状态拼错还静默写进去，比直接报错难查得多。
    """

    status: Literal["open", "acknowledged", "fixed", "ignored", "false_positive"]


class IssueBulkStatusIn(BaseModel):
    """按根因批量改状态（「这一类我都处理了」）。

    ⚠️ ``fingerprint`` 必填且**没有**全选兜底：全站 200 条一起标「已修」
    是个极容易点错的操作，而点错了没法从状态反推回来（没有 undo）。
    要批量就得指明根因。
    """

    fingerprint: str = Field(min_length=1, max_length=64)
    status: Literal["open", "acknowledged", "fixed", "ignored", "false_positive"]


class IssuePage(BaseModel):
    total: int
    items: list[IssueOut]
    has_next: bool


class ScorePoint(BaseModel):
    """一轮扫描的分数快照 —— 趋势线上的一个点。"""

    job_id: int
    score: Optional[float] = None
    pages_crawled: int
    status: str
    finished_at: Optional[datetime] = None


class ScoreTrend(BaseModel):
    """一个站点的分数变化。

    ⚠️ ``points`` 按时间**升序**（旧的在前）：前端直接连线即得趋势图，
    不必再自己反转发���。倒序取的是 DB 里的默认序（id desc），
    每加一次绘制就得多写一次 reverse —— 那是最容易漏的一步。
    """

    site_id: int
    domain: str
    points: list[ScorePoint]


# --------------------------------------------------------------------------
# P2 智能层：关键词 / Brief / AI 总结
#
# ⚠️ 为什么单开一段而不是塞进前面：前面三类是「事实」（爬虫抓到什么就
# 报什么），这三类是「推断」。混在一起会让调用方分不清哪些结论有证据、
# 哪些是模型猜的 —— 而用户对后者理应有完全不同的信任度。
# --------------------------------------------------------------------------


class KeywordOut(BaseModel):
    id: int
    term: str
    market: str = "base"
    intent: Optional[str] = None
    cluster_id: Optional[int] = None
    score: Optional[float] = None
    source: Optional[str] = None


class KeywordPage(BaseModel):
    total: int
    items: list[KeywordOut]
    has_next: bool


class KeywordExpandIn(BaseModel):
    """触发一次关键词扩展 + 聚类。

    ⚠️ ``seeds`` 必填且不能为空：**无种子的共现等于把全站词两两配对，
    噪声远大于信号**（与 cli.py 里的同一道门槛保持一致口径）。
    """

    seeds: list[str] = Field(min_length=1, max_length=50)
    market: str = "base"
    max_candidates: int = Field(default=50, ge=1, le=200)
    min_pages: int = Field(default=2, ge=1, le=50)


class KeywordExpandOut(BaseModel):
    """扩展结果。

    ⚠️ ``status`` 显式三态，不靠「返回空列表」让调用方自己猜：

    - ``ok``    —— 真扩展了
    - ``skipped_no_corpus`` / ``skipped_no_seeds`` —— **诚实地说不出结论**，
      而不是硬凑一个空结果让人以为「没有可扩展的词」
    """

    status: str
    candidates: int = 0
    clusters: int = 0
    reason: Optional[str] = None


class BriefIn(BaseModel):
    keyword: str = Field(min_length=1, max_length=120)
    target_url: str = Field(min_length=1)
    market: str = "google"
    intent: Optional[str] = None


class BriefOut(BaseModel):
    id: Optional[int] = None
    keyword: str
    target_url: str
    market: str
    intent: Optional[str] = None
    page_type: str = ""
    title_candidates: list[str] = Field(default_factory=list)
    serp_common: dict[str, Any] = Field(default_factory=dict)
    own_length_baseline: dict[str, Any] = Field(default_factory=dict)
    opportunities: list[dict[str, Any]] = Field(default_factory=list)
    not_available: list[str] = Field(default_factory=list)
    #: 明确写出哪些输入缺失导致结论受限 —— 缺 SERP 数据时不该让用户
    #: 以为这份 Brief 是基于竞品全貌得出的。
    caveats: list[str] = Field(default_factory=list)


class SummaryOut(BaseModel):
    """报告 AI 总结。

    ⚠️ ``summary=None`` + ``reason`` 必须成对出现。AI 总结是锦上添花，
    规则引擎的报告才是主结果 —— 任何失败都只让这里变成 null，**绝不让
    整份报告消失**（那是把可选功能变成单点故障）。
    """

    summary: Optional[str] = None
    reason: Optional[str] = None
    model: Optional[str] = None


class ReportSummary(BaseModel):
    domain: str
    pages_crawled: int
    counts: dict[str, int]
    health_score: Optional[float] = None
    issues: list[IssueOut]