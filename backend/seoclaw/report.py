"""
报告生成：把结构化结果渲染成人能读懂的报告。

M0 输出 Markdown —— 因为它能直接进 Git、粘进飞书、丢进 issue，
不需要额外依赖。PDF/Excel 留到 M1。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .models import Issue, Page, Severity, SiteReport
from .scoring import DIMENSIONS, top_actions

SEVERITY_LABEL: dict[Severity, str] = {
    Severity.CRITICAL: "严重",
    Severity.HIGH: "高",
    Severity.MEDIUM: "中",
    Severity.LOW: "低",
    Severity.INFO: "提示",
}

SEVERITY_ICON: dict[Severity, str] = {
    Severity.CRITICAL: "🔴",
    Severity.HIGH: "🟠",
    Severity.MEDIUM: "🟡",
    Severity.LOW: "🔵",
    Severity.INFO: "⚪",
}


# 同一根因的不同表现：多个 code 可能指向同一个根源。
# 根因没找对，用户就会去改表面现象，改完发现问题还在——这比漏报更伤。
# 键是根因 id，值是 (根因标题, 根因解释, 涉及的所有 code)
_ROOT_CAUSES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "title_shared_across_pages": (
        "多个页面共用同一套 title",
        "这些页面很可能是同一个模板套出来的。真正要改的是「每个页面的 title 要体现它自己的主题」，"
        "而不是把 title 加长到不报“过短”为止。",
        ("title.duplicate", "title.too_short", "title.too_long"),
    ),
    "canonical_not_self": (
        "canonical 指向了其它页面",
        "先确认这是有意的合并/版本别名，还是模板漏改。若是有意的，保持现状即可。",
        ("canonical.conflict",),
    ),
    "no_index_signal": (
        "索引信号缺失",
        "搜索引擎拿不到该收录什么页面的明确信号。",
        ("meta.missing", "canonical.missing", "h1.missing"),
    ),
}


@dataclass
class IssueGroup:
    """同一 code 下的一组问题（一个 code 往往是同一个根因在多处的表现）。"""

    code: str
    representative: Issue
    affected: list[Issue] = field(default_factory=list)

    @property
    def affected_count(self) -> int:
        return len(self.affected)

    @property
    def urls(self) -> list[str]:
        return [i.url for i in self.affected if i.url]

    @property
    def root_cause(self) -> Optional[str]:
        for root_id, (_, _, codes) in _ROOT_CAUSES.items():
            if self.code in codes:
                return root_id
        return None


def aggregate_by_root_cause(issues: list[Issue]) -> dict[Severity, list[IssueGroup]]:
    """把同 code 的问题合并成一条，避免噪音淹没信号。

    实测（antfu.me）：10 个页面 title 都是 "Anthony Fu"（10 字符），
    旧版报告输出 10 条一模一样的 title.too_short。
    用户看到重复 10 遍的提示会直接关掉报告——
    噪音比漏报更伤，因为用户会连带不再相信那些真正重要的结论。
    合并后变成 1 条「影响 10 个页面」，并直接指出根因。
    """
    buckets: dict[tuple[str, str], IssueGroup] = {}
    for issue in issues:
        key = (issue.severity.value, issue.code)
        if key not in buckets:
            buckets[key] = IssueGroup(code=issue.code, representative=issue, affected=[])
        buckets[key].affected.append(issue)

    out: dict[Severity, list[IssueGroup]] = {s: [] for s in Severity}
    for (sev_value, _code), group in buckets.items():
        # 组内按 URL 排序保证输出稳定（避免每次扫描顺序不同导致报告抖动）
        group.affected.sort(key=lambda i: i.url or "")
        out[Severity(sev_value)].append(group)

    for groups in out.values():
        groups.sort(key=lambda g: (-g.affected_count, g.code))
    return out


def _render_unaudited(pages: list[Page], max_urls: int = 3) -> list[str]:
    """列出**没参与规则审计**的页面。

    ⚠️ 这些页面被审计引擎 ``if not page.is_html or page.error: continue``
    整页跳过 —— 标题、描述、H1 全都没查过。而它们又**不会**出现在
    问题清单里（因为根本没跑规则）。所以以前用户看到的是一份
    「全站都没问题」的报告，而实际上有若干页压根没审。

    这跟 0 页场景是同一类错：**「没审成」不能长成「没问题」的样��**。

    刻意不混进问题清单：混进去会让人以为「这是站点的一个问题」，
    而它其实是「本次抓取的一个缺口」，处置方式完全不同
    （前者改站，后者改抓取配置/网络）。
    """
    unaudited = [p for p in pages if not p.is_html or p.error]
    if not unaudited:
        return []

    def _why(p: Page) -> str:
        if p.error:
            if p.error.startswith("http_error"):
                return p.error.split(":", 1)[1].strip()[:80] or "请求失败"
            return {
                "timeout": "请求超时",
                "too_large": "页面超过体积上限，未下载",
            }.get(p.error, p.error)
        ct = (p.content_type or "").split(";")[0].strip() or "未知类型"
        return f"非 HTML 内容（{ct}），无 SEO 元数据可审"

    lines = [
        f"## 没审到的页面（{len(unaudited)} 个）",
        "",
        "> 这些页面**没有参与任何规则检查**。上面的问题清单不覆盖它们 —— "
        "「没审到」不等于「没问题」。",
        "",
    ]
    for p in unaudited[:max_urls]:
        lines.append(f"- `{p.url}` — {_why(p)}")
    if len(unaudited) > max_urls:
        lines.append(f"- …另有 {len(unaudited) - max_urls} 个")
    lines.append("")
    lines.append(
        "常见成因：目标页体积超限、非 HTML 内容、请求超时/失败。"
        "若是站点真实存在的 HTML 页面，请检查抓取是否被限流。"
    )
    lines.append("")
    return lines


def render_markdown(
    report: SiteReport,
    pages: list[Page],
    max_issue_urls: int = 3,
    brand: Optional[str] = None,
) -> str:
    """生成完整 Markdown 报告。

    ``brand``：白标出口（见 report_html.render_html 同名参数的说明）。
    """
    by_sev = report.issues_by_severity
    lines: list[str] = []

    # ---- 概览 ----
    lines.append(f"# SEO 体检报告 · {report.domain}")
    lines.append("")
    if brand:
        lines.append(f"本报告由 **{brand}** 出具。")
        lines.append("")
    if report.finished_at and report.started_at:
        duration = (report.finished_at - report.started_at).total_seconds()
        lines.append(
            f"扫描时间：{report.started_at.strftime('%Y-%m-%d %H:%M')} UTC"
            f" · 耗时 {duration:.0f}s"
            f" · 抓取 {report.pages_crawled} / 发现 {report.pages_discovered} 个 URL"
        )
    else:
        lines.append(f"抓取 {report.pages_crawled} / 发现 {report.pages_discovered} 个 URL")
    lines.append("")

    # ---- 健康分 ----
    if report.health_score is None:
        # ⚠️ 「未评估」≠「满分」。score() 在 0 页时返回 None 而不是 100，
        # 这里必须把这个状态说出来。若渲染层照样打 100，用户会以为全站
        # 审过了、没问题——而实际上一页都没抓到。两种 0 页场景：
        #   - robots.txt 禁抓（lobste.rs 是 User-agent:* / Disallow:/）
        #   - 请求全被限流/封禁（w3.org 种子页 429 → frontier 空）
        lines.append("## 健康分：未评估")
        lines.append("")
        lines.append(
            f"> ⚠️ **本次没有审到任何页面，所以不给分。**"
            f"已发现 {report.pages_discovered} 个 URL，但 0 页抓取成功。"
        )
        lines.append(
            "> 「未评估」不等于「没问题」——它只说明这次什么也没检查到。"
            "常见原因：robots.txt 禁止抓取、被对方限流/封禁、需 JS 渲染、网络故障。"
        )
        lines.append("")
    if report.health_score is not None:
        lines.append(f"## 健康分：{report.health_score:.0f} / 100")
        # ⚠️ 样本量警告：扣分系数是「受影响页面占比」，页数越少占比越粗。
        # 5 页样本下占比只能取 0.2 的整数倍，一个问题就可能吃掉 30 分——
        # 这时分数不能当精确值读。实测 23 站里 22 站只抓到 5 页。
        if 0 < report.pages_crawled < 20:
            lines.append("")
            lines.append(
                f"> ⚠️ 仅抽查了 {report.pages_crawled} 页，样本量偏小："
                "上面的分数只反映这几页的情况，**不要当全站结论**，也不适合用来对比站点。"
            )
        lines.append("")
        counts = " · ".join(
            f"{SEVERITY_ICON[s]} {SEVERITY_LABEL[s]} {len(by_sev[s])}"
            for s in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW)
        )
        lines.append(f"共 {len(report.issues)} 个问题：{counts}")
        lines.append("")

        dims = (report.score_breakdown or {}).get("dimension_scores") or {}
        if dims:
            lines.append("| 维度 | 得分 |")
            lines.append("|---|---|")
            for key, label in DIMENSIONS.items():
                val = dims.get(key)
                if val is not None:
                    lines.append(f"| {label} | {val:.0f} |")
            lines.append("")

    # ---- 最该先做的 ----
    actions = top_actions(report.issues, max(report.pages_crawled, 1), limit=5)
    if actions:
        lines.append("## 最该先做的 5 件事")
        lines.append("")
        for i, issue in enumerate(actions, 1):
            lines.append(f"### {i}. [{SEVERITY_LABEL[issue.severity]}] {issue.title}")
            lines.append("")
            lines.append(issue.description)
            lines.append("")
            if issue.fix_hint:
                lines.append(f"**怎么修**：{issue.fix_hint}")
                lines.append("")
            if issue.fix_example:
                lines.append("```html")
                lines.append(issue.fix_example)
                lines.append("```")
                lines.append("")
            lines.extend(_render_evidence(issue, max_issue_urls))
    else:
        lines.append("## 结论")
        lines.append("")
        if report.health_score is None:
            lines.append(
                "本次扫描**没有审到任何页面**，因此无法给出结论。"
                "请先解决抓取本身的问题（robots 限制、反爬、网络或 JS 渲染），"
                "再重跑一次。"
            )
        else:
            lines.append("本次扫描没有发现问题。保持现有做法，继续关注内容质量与外链。")
        lines.append("")

    # ---- 没审成的页面（单独成节，不混进问题清单）----
    lines.extend(_render_unaudited(pages, max_issue_urls))

    # ---- 全部问题（按根因聚合）----
    lines.append("## 全部问题明细")
    lines.append("")
    grouped = aggregate_by_root_cause(report.issues)
    for sev in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO):
        group = grouped.get(sev) or []
        if not group:
            continue
        lines.append(
            f"### {SEVERITY_ICON[sev]} {SEVERITY_LABEL[sev]}"
            f"（{sum(g.affected_count for g in group)} 处，"
            f"{len(group)} 类）"
        )
        lines.append("")
        for agg in group:
            lines.extend(_render_issue_line(agg.representative, max_issue_urls, agg=agg))
        lines.append("")

    return "\n".join(lines)


# 证据字段的展示优先级：判定结论类字段必须置顶。
# （曾踩坑：verdict 排在第 7 位，被「只显示前 3 个字段」的逻辑截没了，
#   等于把最关键的判断依据藏了起来——规则判定再准，用户看不到也没意义。）
_EVIDENCE_PRIORITY = (
    "verdict",
    "verdict_explain",
    "canonical_target_status",
    "internal_outbound_links",
    "inbound_links",
    "url_looks_like_index",
    "word_count",
)


def _ordered_evidence(evidence: dict) -> dict:
    """按重要度重排证据字段，保证判定结论在前。"""
    remaining = dict(evidence)
    ordered: dict = {}
    for key in _EVIDENCE_PRIORITY:
        if key in remaining:
            ordered[key] = remaining.pop(key)
    ordered.update(remaining)
    return ordered


def _render_issue_line(
    issue: Issue, max_urls: int, agg: "IssueGroup | None" = None
) -> list[str]:
    """把一条问题渲染成 Markdown 列表行（含证据）。

    传入 agg 时按聚合模式渲染：显示影响面与根因，而不是逐页刷屏。
    """
    loc = f"`{issue.url}`" if issue.url else "全站"
    if agg is not None and agg.affected_count > 1:
        loc = f"影响 {agg.affected_count} 个页面"
    lines = [f"- **{issue.code}** — {issue.title} · {loc}"]

    # 根因提示：同一根因的多个症状要指出来，否则用户会去改表面现象
    if agg is not None:
        root_id = agg.root_cause
        if root_id:
            title, explain, _codes = _ROOT_CAUSES[root_id]
            lines.append(f"  - **根因推测**：{title}")
            lines.append(f"  - {explain}")
        if agg.urls:
            for url in agg.urls[:max_urls]:
                lines.append(f"  - 示例：{url}")
            remaining = len(agg.urls) - max_urls
            if remaining > 0:
                lines.append(f"  - ……另有 {remaining} 个")
        return lines

    sample_urls = issue.evidence.get("sample_urls")
    if issue.scope.value == "site" and isinstance(sample_urls, list):
        for url in sample_urls[:max_urls]:
            lines.append(f"  - 示例：{url}")
    else:
        for key, value in _ordered_evidence(issue.evidence).items():
            if key == "sample_urls":
                continue
            if key in ("verdict", "verdict_explain"):
                # 判定结论必须突出显示——它是用户判断「要不要改」的依据
                lines.append(f"  - **{key}**: {value}")
                continue
            shown = str(value)
            if len(shown) > 160:
                shown = shown[:157] + "..."
            lines.append(f"  - {key}: `{shown}`")
        lines.append("")
    return lines


def _render_evidence(issue: Issue, max_urls: int) -> list[str]:
    """证据区——产品的信任机制：每条结论都能追到原始数据。"""
    lines: list[str] = []
    # tried_paths 是「试过哪些 sitemap 地址、各自什么结果」。它默认会掉进
    # 下面的 str(value) 分支，被 200 字符截断成一坨 Python dict repr——
    # 技术上有证据，读起来像日志。这里单独渲染成列表。
    tried = issue.evidence.get("tried_paths")
    if isinstance(tried, list) and tried:
        lines.append("**试过的路径**（证明确实去试过，而不是直接判「没有」）：")
        lines.append("")
        for item in tried[:max_urls]:
            if isinstance(item, dict):
                status = item.get("status")
                code = str(status) if status is not None else (item.get("error") or "无响应")
                mark = "✓" if item.get("ok") else "✗"
                lines.append(f"- {mark} HTTP {code} `{item.get('url', '')}`")
            else:
                lines.append(f"- {item}")
        remaining = len(tried) - max_urls
        if remaining > 0:
            lines.append(f"- ……另有 {remaining} 个")
        lines.append("")
    sample_urls = issue.evidence.get("sample_urls")
    if isinstance(sample_urls, list) and sample_urls:
        lines.append("**证据**：")
        lines.append("")
        for url in sample_urls[:max_urls]:
            lines.append(f"- {url}")
        remaining = len(sample_urls) - max_urls
        if remaining > 0:
            lines.append(f"- ……另有 {remaining} 个")
        lines.append("")
    elif issue.evidence:
        lines.append("**证据**：")
        lines.append("")
        for key, value in _ordered_evidence(issue.evidence).items():
            if key in ("verdict", "verdict_explain"):
                lines.append(f"- **{key}**: {value}")
                continue
            if key == "tried_paths":
                continue  # 已在上面单独渲染
            shown = str(value)
            if len(shown) > 200:
                shown = shown[:197] + "..."
            lines.append(f"- `{key}` = `{shown}`")
        lines.append("")
    return lines


def summarize_console(report: SiteReport) -> str:
    """终端简版输出。"""
    by_sev = report.issues_by_severity
    lines = [
        "",
        f"域名     {report.domain}",
        f"抓取     {report.pages_crawled} 页 / 发现 {report.pages_discovered} 个 URL",
        f"健康分   {report.health_score:.0f}/100" if report.health_score is not None
        else "健康分   未评估（0 页）",
        f"问题数   {len(report.issues)}"
        f"（严重 {len(by_sev[Severity.CRITICAL])} / 高 {len(by_sev[Severity.HIGH])}"
        f" / 中 {len(by_sev[Severity.MEDIUM])} / 低 {len(by_sev[Severity.LOW])}）",
        "",
        "最该先做：",
    ]
    actions = top_actions(report.issues, max(report.pages_crawled, 1), limit=5)
    for i, issue in enumerate(actions, 1):
        lines.append(f"  {i}. [{SEVERITY_LABEL[issue.severity]}] {issue.title}（{issue.code}）")
    lines.append("")
    return "\n".join(lines)
