"""HTML 报告渲染。

为什么不直接让 Markdown 变 HTML：报告是**给人看、给人转发的**，
用户拿到的是一份文件，不是终端输出。所以要求是：

- **单文件、零外链**：不引 CDN、不引字体。报告要能存三年后打开，
  而 CDN 上的样式可能早没了。
- **离线可读**：双击就开，不联网。
- **分级折叠**：39 条规则命中几百处问题，全平铺没人看得下去。
  默认只展开「最该先做的」和严重/高级，其余折叠。

⚠️ 渲染里最容易犯的错是**把「未评估」画成 0 分或满分**：
`health_score is None` 的意思是「这次一页都没审到」，和
「审了、结果很差」是完全不同的两件事。0 页成功时给百分比
或分数，就是在撒谎。score() 返回 None、这里渲染成醒目的警告块，
两层都要守住。
"""

from __future__ import annotations

import html
import json
from typing import Any, Optional

from .models import Issue, Page, Severity, SiteReport
from .report import (
    SEVERITY_ICON,
    SEVERITY_LABEL,
    _ordered_evidence,
    aggregate_by_root_cause,
)
from .scoring import DIMENSIONS, top_actions

# 低于这个页数，扣分系数（受影响页面占比）就太粗，分数不能当精确值读
_SMALL_SAMPLE = 20


def _e(x: Any) -> str:
    """HTML 转义。

    ⚠️ 不是可选项：evidence 里有 URL、有 verbatim 抓回来的原始片段、
    有 title 文本。任何一处未经转义直接拼进 HTML，报告就成了 XSS 载体
    ——而报告是要被人转发出去的。
    """
    return html.escape(str(x if x is not None else ""))


def _severity_class(s: Severity) -> str:
    return f"sev-{s.value}"


def _score_tone(score: float) -> str:
    if score >= 80:
        return "good"
    if score >= 60:
        return "ok"
    if score >= 40:
        return "warn"
    return "bad"


_CSS = """
:root{
  --bg:#f6f7f9; --card:#fff; --ink:#1a1d21; --muted:#6b7280; --line:#e5e7eb;
  --good:#0f9d58; --ok:#8ab400; --warn:#f29900; --bad:#db4437;
  --critical:#db4437; --high:#e8710a; --medium:#f29900; --low:#4a90d9; --info:#9aa0a6;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",
  "Hiragino Sans GB","Microsoft YaHei",sans-serif}
.wrap{max-width:920px;margin:0 auto;padding:28px 20px 80px}
h1{font-size:24px;margin:0 0 4px}
h2{font-size:18px;margin:36px 0 12px;padding-bottom:8px;border-bottom:1px solid var(--line)}
.sub{color:var(--muted);font-size:13px;margin-bottom:24px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
  padding:18px 20px;margin-bottom:14px}
.score{display:flex;align-items:center;gap:22px;flex-wrap:wrap}
.score-num{font-size:46px;font-weight:700;line-height:1}
.good .score-num{color:var(--good)} .ok .score-num{color:var(--ok)}
.warn .score-num{color:var(--warn)} .bad .score-num{color:var(--bad)}
.bar{height:8px;border-radius:4px;background:var(--line);overflow:hidden;
  flex:1;min-width:220px}
.bar>i{display:block;height:100%;background:currentColor}
.meta{color:var(--muted);font-size:13px}
.alert{background:#fff4f4;border:1px solid #f3bcbc;border-left:4px solid var(--bad);
  border-radius:8px;padding:14px 16px;margin-bottom:14px}
.alert.warn{background:#fffbf0;border-color:#f0dca8;border-left-color:var(--warn)}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0 0}
.chip{font-size:12px;padding:3px 9px;border-radius:99px;border:1px solid var(--line);
  background:#fafafa;color:var(--muted)}
.chip b{color:var(--ink);font-weight:600}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line)}
th{color:var(--muted);font-weight:500;font-size:12px}
td.num{text-align:right;font-variant-numeric:tabular-nums}
details{border:1px solid var(--line);border-radius:8px;background:var(--card);margin-bottom:10px}
details>summary{cursor:pointer;padding:12px 16px;list-style:none;
  display:flex;align-items:center;gap:10px;flex-wrap:wrap}
details>summary::-webkit-details-marker{display:none}
details>summary::before{content:"▸";color:var(--muted);transition:transform .12s}
details[open]>summary::before{transform:rotate(90deg)}
.sev-dot{width:9px;height:9px;border-radius:50%;flex:none}
.sev-critical{background:var(--critical)} .sev-high{background:var(--high)}
.sev-medium{background:var(--medium)} .sev-low{background:var(--low)}
.sev-info{background:var(--info)}
.sev-tag{font-size:11px;padding:2px 7px;border-radius:4px;color:#fff;flex:none}
.tag-critical{background:var(--critical)} .tag-high{background:var(--high)}
.tag-medium{background:var(--medium)} .tag-low{background:var(--low)}
.tag-info{background:#757575}
.code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;
  color:var(--muted)}
.body{padding:0 16px 16px 34px}
.body p{margin:8px 0}
.fix{background:#f8f9fa;border:1px solid var(--line);border-radius:6px;padding:10px 12px;margin:10px 0}
.fix-label{font-size:11px;color:var(--muted);display:block;margin-bottom:5px;letter-spacing:.04em}
pre{margin:0;overflow-x:auto;font:12.5px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;
  white-space:pre-wrap;word-break:break-word}
.fix-example{border-left:3px solid var(--good)}
a{color:#1a73e8;text-decoration:none;word-break:break-all}
a:hover{text-decoration:underline}
ul.urls{margin:8px 0 0;padding-left:18px}
ul.urls li{font-size:12.5px;color:var(--muted);margin:2px 0}
.evidence{font-size:13px;margin-top:8px}
.evidence dt{color:var(--muted);font-size:11px;margin-top:7px}
.evidence dd{margin:2px 0 0}
.action-n{width:24px;height:24px;border-radius:50%;background:var(--ink);color:#fff;
  display:inline-flex;align-items:center;justify-content:center;
  font-size:12px;font-weight:600;flex:none}
.footer{margin-top:44px;color:var(--muted);font-size:12px;text-align:center}
@media (prefers-color-scheme:dark){
  :root{--bg:#16181d;--card:#1e2128;--ink:#e8eaed;--muted:#9aa0a6;--line:#2c3038}
  .chip{background:#24272e}
  .fix{background:#24272e}
  .alert{background:#2a1d1d;border-color:#5c2b2b}
  .alert.warn{background:#2a2519;border-color:#5c4d2b}
}
@media print{
  body{background:#fff} .card,details{break-inside:avoid}
  details{border-color:#ccc}
}
"""


def _evidence_html(issue: Issue, max_urls: int = 3) -> str:
    ev = _ordered_evidence(issue.evidence or {})
    if not ev:
        return ""
    rows: list[str] = []
    for k, v in ev.items():
        # URL 列表单独渲染，避免一个 dl 里塞几百个 <li>
        if k in ("example_urls", "affected_urls") and isinstance(v, list):
            urls = [u for u in v if u][:max_urls]
            if not urls:
                continue
            more = len(v) - len(urls)
            items = "".join(f'<li><a href="{_e(u)}">{_e(u)}</a></li>' for u in urls)
            tail = f'<li>…另有 {more} 处</li>' if more > 0 else ""
            rows.append(
                f'<dt>{_e(k)}</dt><dd><ul class="urls">{items}{tail}</ul></dd>'
            )
            continue
        text = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
        rows.append(f"<dt>{_e(k)}</dt><dd>{_e(text)}</dd>")
    if not rows:
        return ""
    return f'<dl class="evidence">{"".join(rows)}</dl>'


def _issue_head(issue: Issue) -> str:
    """问题摘要行：严重度标签 + 标题 + code。"""
    sev = issue.severity
    return (
        f'<span class="sev-tag tag-{sev.value}">{_e(SEVERITY_LABEL[sev])}</span>'
        f'<strong>{_e(issue.title)}</strong>'
        f'<span class="code">{_e(issue.code)}</span>'
    )


def _group_html(group: Any, max_urls: int) -> str:
    rep = group.representative
    head = _issue_head(rep)
    n = group.affected_count
    # ⚠️ 受影响条数要写清是「几处」而不是「几个问题」——
    # 用户看到 "title.duplicate ×1" 会以为只有一处有重复标题。
    cnt = f'<span class="chip">影响 <b>{n}</b> 处页面</span>'
    if n > 1:
        cnt = f'<span class="chip">同一根因影响 <b>{n}</b> 处页面</span>'

    body: list[str] = [f"<p>{_e(rep.description)}</p>"]
    if rep.fix_hint:
        body.append(
            f'<div class="fix"><span class="fix-label">怎么修</span>{_e(rep.fix_hint)}</div>'
        )
    if rep.fix_example:
        body.append(
            f'<div class="fix fix-example"><span class="fix-label">示例</span>'
            f"<pre>{_e(rep.fix_example)}</pre></div>"
        )
    urls = [u for u in group.urls if u][:max_urls]
    if urls:
        items = "".join(f'<li><a href="{_e(u)}">{_e(u)}</a></li>' for u in urls)
        more = n - len(urls)
        tail = f"<li>…另有 {more} 处</li>" if more > 0 else ""
        body.append(
            f'<p class="meta" style="margin-bottom:4px">部分受影响页面</p>'
            f'<ul class="urls">{items}{tail}</ul>'
        )
    body.append(_evidence_html(rep, max_urls))

    root = group.root_cause
    if root:
        body.append(
            f'<p class="meta">归因：{_e(root)}（同一根因的不同表现，'
            "改表面现象问题会留着）</p>"
        )
    return (
        f"<details><summary>{head}{cnt}</summary>"
        f'<div class="body">{"".join(body)}</div></details>'
    )


def _actions_html(report: SiteReport, max_urls: int) -> str:
    actions = top_actions(
        report.issues, max(report.pages_crawled, 1), limit=5
    )
    if not actions:
        if report.health_score is None:
            return (
                '<div class="alert"><strong>本次扫描没有审到任何页面，无法给出结论。</strong>'
                "<br>请先解决抓取本身的问题（robots 限制、限流/封禁、需 JS 渲染、网络），"
                "再重跑一次。</div>"
            )
        return (
            '<div class="alert warn" style="background:#f6fdf6;border-color:#b7e0b7;'
            'border-left-color:#0f9d58"><strong>本次扫描没有发现问题。</strong>'
            "<br>这不���明全站没问题——只说明抽查的这几页里没命中规则。</div>"
        )

    out: list[str] = []
    for i, issue in enumerate(actions, 1):
        sev = issue.severity
        body = [f"<p>{_e(issue.description)}</p>"]
        if issue.fix_hint:
            body.append(
                f'<div class="fix"><span class="fix-label">怎么修</span>'
                f"{_e(issue.fix_hint)}</div>"
            )
        if issue.fix_example:
            body.append(
                f'<div class="fix fix-example"><span class="fix-label">示例</span>'
                f"<pre>{_e(issue.fix_example)}</pre></div>"
            )
        body.append(_evidence_html(issue, max_urls))
        out.append(
            f'<div class="card"><div style="display:flex;gap:11px;align-items:flex-start">'
            f'<span class="action-n">{i}</span><div style="flex:1">'
            f'<div style="display:flex;gap:9px;align-items:center;flex-wrap:wrap;margin-bottom:4px">'
            f'<span class="sev-tag tag-{sev.value}">{_e(SEVERITY_LABEL[sev])}</span>'
            f"<strong>{_e(issue.title)}</strong>"
            f'<span class="code">{_e(issue.code)}</span></div>'
            f'{"".join(body)}</div></div></div>'
        )
    return "".join(out)


def render_html(report: SiteReport, pages: list[Page], max_issue_urls: int = 3) -> str:
    """生成单文件 HTML 报告。"""
    parts: list[str] = []
    A = parts.append

    A("<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">")
    A('<meta name="viewport" content="width=device-width,initial-scale=1">')
    A(f"<title>SEO 体检报告 · {_e(report.domain)}</title>")
    A(f"<style>{_CSS}</style></head><body><div class=\"wrap\">")

    A(f"<h1>SEO 体检报告 · {_e(report.domain)}</h1>")

    # ---- 扫描概况 ----
    bits = [f"抓取 <b>{report.pages_crawled}</b> 页"]
    if report.pages_discovered:
        bits.append(f"发现 {report.pages_discovered} 个 URL")
    if report.started_at and report.finished_at:
        dur = (report.finished_at - report.started_at).total_seconds()
        bits.append(f"耗时 {dur:.0f}s")
    A(f'<div class="sub">{" · ".join(bits)}</div>')

    by_sev = report.issues_by_severity

    # ---- 健康分 / 未评估 ----
    if report.health_score is None:
        A('<div class="alert"><strong>健康分：未评估</strong>')
        A(
            "<p>本次<b>没有审到任何页面</b>，所以不给分。"
            f"已发现 {report.pages_discovered} 个 URL，但 0 页抓取成功。</p>"
            "<p><b>「未评估」不等于「没问题」</b>——它只说明这次什么也没检查到。"
            "常见原因：robots.txt 禁止抓取、被对方限流/封禁、需要 JS 渲染、网络故障。"
            "把这份报告当成「你的站很健康」是本次最容易犯的错误。</p></div>"
        )
    else:
        score = float(report.health_score)
        A('<div class="card"><div class="score">')
        A(f'<div class="{_score_tone(score)}" style="flex:none">'
          f'<div class="score-num">{score:.0f}</div>'
          f'<div class="meta">/ 100</div></div>')
        A(f'<div class="bar {_score_tone(score)}"><i style="width:{max(score,0):.1f}%"></i></div>')
        A('<div class="meta" style="flex:none">')
        A(" · ".join(
            f'<span class="sev-dot sev-{s.value}" title="{_e(SEVERITY_LABEL[s])}"></span> '
            f"{_e(SEVERITY_LABEL[s])} {len(by_sev[s])}"
            for s in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM,
                      Severity.LOW, Severity.INFO)
        ))
        A("</div></div></div>")

        # 样本量警告：扣分系数是「受影响页面占比」，页数少时占比很粗。
        if 0 < report.pages_crawled < _SMALL_SAMPLE:
            A(f'<div class="alert warn"><strong>仅抽查了 {report.pages_crawled} 页，'
              "样本量偏小。</strong><br>上面的分数只反映这几页的情况，"
              "<b>不要当全站结论</b>，也不适合用来横向对比站点。</div>")

        dims = (report.score_breakdown or {}).get("dimension_scores") or {}
        if dims:
            rows = "".join(
                f'<tr><td>{_e(DIMENSIONS.get(k, k))}</td>'
                f'<td class="num">{v:.0f}</td></tr>'
                for k, v in dims.items()
                if v is not None
            )
            A('<div class="card"><table><thead><tr><th>维度</th>'
              '<th style="text-align:right">得分</th></tr></thead>'
              f"<tbody>{rows}</tbody></table></div>")

    # ---- 最该先做的 ----
    A("<h2>最该先做的 5 件事</h2>")
    A(_actions_html(report, max_issue_urls))

    # ---- 全部问题 ----
    A("<h2>全部问题明细</h2>")
    grouped = aggregate_by_root_cause(report.issues)
    any_issue = False
    for sev in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM,
                Severity.LOW, Severity.INFO):
        groups = grouped.get(sev) or []
        if not groups:
            continue
        any_issue = True
        total = sum(g.affected_count for g in groups)
        # 严重/高级默认展开，低级/提示默认折叠——先让人处理要命的问题
        open_attr = " open" if sev in (Severity.CRITICAL, Severity.HIGH) else ""
        A(f"<details{open_attr}><summary>"
          f'<span class="sev-dot sev-{sev.value}"></span>'
          f"<strong>{_e(SEVERITY_ICON[sev])} {_e(SEVERITY_LABEL[sev])}</strong>"
          f'<span class="chip">共 <b>{total}</b> 处 · <b>{len(groups)}</b> 类</span>'
          "</summary>")
        A('<div class="body">')
        for g in groups:
            A(_group_html(g, max_issue_urls))
        A("</div></details>")
    if not any_issue:
        A('<div class="alert warn" style="background:#f6fdf6;border-color:#b7e0b7;'
          'border-left-color:#0f9d58">没有命中任何规则。</div>')

    A(f'<div class="footer">由 SEO Agent 生成 · '
      f"{_e(report.started_at.strftime('%Y-%m-%d %H:%M')) if report.started_at else ''} UTC</div>")
    A("</div></body></html>")
    return "".join(parts)