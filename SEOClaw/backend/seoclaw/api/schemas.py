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


class RankDropRequest(BaseModel):
    """排名跌幅告警的查询条件。

    ⚠️ 三道门槛**显式暴露给调用方**，不藏在代码默认值里：按天盯排名
    的人若每跌 2 名收一条提醒，一周七条然后全部忽略 —— 告警一多就不叫
    告警了。阈值该由「多吵才算吵」决定，那是使用场景的事，不是代码的事。
    """

    window_days: int = Field(default=30, ge=2, le=365)
    min_drop: float = Field(default=5.0, ge=0.0, le=1000.0)
    min_impressions: int = Field(default=10, ge=0, le=1_000_000)
    min_days: int = Field(default=4, ge=2, le=90)
    #: 只返回还没被标记过「已看过」的。默认 False —— 全量返回才是
    #: 「这个位置现在有哪些跌落」的诚实答案；要「有什么新动静」才开。
    only_new: bool = False


class RankAlertAckIn(BaseModel):
    """标记若干条告警为已看过。

    ⚠️ 由**用户动作**驱动，不在查询时自动标记：「我算了但没人看」
    不等于「看过了」，自动标记等于这声告警根本没发过。
    """

    alert_keys: list[str] = Field(min_length=1, max_length=200)


class RankAlertOut(BaseModel):
    """一条排名跌幅告警。

    ⚠️ ``message`` 是人话结论，直接可发给用户。不给这个的话，通知里塞
    一堆数字等于让用户自己解读 —— 而用户看不出「10→20」是好是坏。
    """

    url: str
    from_position: float
    to_position: float
    drop: float
    from_date: str
    to_date: str
    message: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    #: 稳定标识这一场跌落，用于 ack。
    alert_key: str = ""


class QuotaOut(BaseModel):
    used: int
    #: None = 不限量（单机模式）
    limit: Optional[int] = None
    enforced: bool = False


class MeOut(BaseModel):
    owner: str
    auth_enabled: bool
    quota: QuotaOut


class ApiKeyOut(BaseModel):
    id: int
    name: str
    key_prefix: str
    created_at: str
    last_used_at: Optional[str] = None
    revoked: bool = False


class ApiKeyCreated(BaseModel):
    """⚠️ **明文只在这里出现一次**，之后库里只有哈希，丢了只能重发。"""

    key: str
    key_prefix: str
    name: str
    warning: str


class VerificationOut(BaseModel):
    status: str
    token: Optional[str] = None
    dns_instructions: Optional[str] = None
    meta_instructions: Optional[str] = None
    verified_at: Optional[str] = None
    verify_method: Optional[str] = None


class UsageOut(BaseModel):
    """某站点的计量汇总。

    ⚠️ ``by_kind`` 是 ``SUM`` 出来的，不是「读出来累加」—— 追加写的
    意义就是数字随时能被复算，一旦开始读出来累加，两条口径必然分叉，
    而计费数字分叉的下场是对不上账。
    """

    site_id: int
    by_kind: dict[str, int] = Field(default_factory=dict)
    total: int = 0


class ReportSummary(BaseModel):
    domain: str
    pages_crawled: int
    counts: dict[str, int]
    health_score: Optional[float] = None
    issues: list[IssueOut]