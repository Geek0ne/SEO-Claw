"""Web 端报告导出：把数据库里的扫描结果渲染成可带走的文件。

## 为什么另写一份而不是复用 report.py

``report.py`` 渲染的是**扫描时刻**的 ``SiteReport``（带 Page 级证据链、
覆盖率披露、根因分组）——它需要抓取现场的全部数据，而数据库里只留了
问题与分数。硬造一个假的 ``SiteReport`` 去喂它，会渲染出「有证据链」
的样子但证据是空的——那正是本项目最反对的「看起来很像」。

所以这里的口径是**数据库视角的体检摘要**：有什么说什么。CLI 报告是
完整版（扫描现场生成），Web 导出是归档版（从库里重建），两者定位不同、
不互相冒充。

## 三种格式

- ``json`` —— 结构化原始数据，给程序用；
- ``md``   —— 归档 / 粘进工单；
- ``html`` —— 单文件、无外链，可直接发客户。
"""

from __future__ import annotations

import html as _html
import json
from datetime import datetime, timezone
from typing import Any

SEV_LABEL = {"critical": "严重", "high": "高", "medium": "中", "low": "低", "info": "提示"}
SEV_ORDER = ["critical", "high", "medium", "low", "info"]
STATUS_LABEL = {
    "open": "待处理",
    "acknowledged": "已知晓",
    "fixed": "已修复",
    "ignored": "已忽略",
    "false_positive": "误报",
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def render_markdown(summary: dict[str, Any], trend: dict[str, Any] | None = None) -> str:
    """数据库视角的 Markdown 摘要。"""
    counts = summary.get("counts") or {}
    lines: list[str] = [
        f"# SEO 体检摘要 · {summary.get('domain', '')}",
        "",
        f"导出时间：{_now()} · 覆盖页面 {summary.get('pages_crawled', 0)} 页",
        "",
    ]
    score = summary.get("health_score")
    lines.append(f"## 健康分：{'—' if score is None else f'{score:.0f} / 100'}")
    if score is None:
        lines.append("")
        lines.append("> 尚无可评分的扫描（0 页成功时健康分保持空缺，不以 0 代替）。")
    lines.append("")

    total = sum(counts.get(k, 0) for k in SEV_ORDER)
    lines.append(f"共 {total} 个问题：" + " · ".join(
        f"{SEV_LABEL[k]} {counts.get(k, 0)}" for k in SEV_ORDER
    ))
    lines.append("")

    issues = summary.get("issues") or []
    if issues:
        lines.append("## 问题清单")
        lines.append("")
        lines.append("| 严重级 | 规则 | 问题 | 页面 | 状态 |")
        lines.append("|---|---|---|---|---|")
        for i in issues:
            lines.append(
                f"| {SEV_LABEL.get(i.get('severity'), i.get('severity'))} "
                f"| `{i.get('code')}` | {i.get('title')} "
                f"| {i.get('url') or '（站点级）'} "
                f"| {STATUS_LABEL.get(i.get('status'), i.get('status'))} |"
            )
        lines.append("")

    if trend and trend.get("points"):
        lines.append("## 扫描历史")
        lines.append("")
        for p in trend["points"]:
            sc = "—" if p.get("score") is None else f"{p['score']:.0f}"
            lines.append(
                f"- #{p.get('job_id')} · 分数 {sc} · {p.get('pages_crawled')} 页"
                f" · {p.get('status')} · {p.get('finished_at') or '未完成'}"
            )
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("本摘要从数据库重建，不含扫描现场的完整证据链；")
    lines.append("完整报告请在扫描时用 `--html` / `-o` 导出（CLI）或在 Web 端查看在线报告。")
    return "\n".join(lines)


def render_html(summary: dict[str, Any], trend: dict[str, Any] | None = None) -> str:
    """单文件 HTML（无外链）。"""
    e = lambda s: _html.escape(str(s if s is not None else ""))  # noqa: E731
    counts = summary.get("counts") or {}
    score = summary.get("health_score")
    rows = "".join(
        f"<tr><td>{e(SEV_LABEL.get(i.get('severity'), i.get('severity')))}"
        f"<td><code>{e(i.get('code'))}</code><td>{e(i.get('title'))}"
        f"<td class='u'>{e(i.get('url') or '（站点级）')}"
        f"<td>{e(STATUS_LABEL.get(i.get('status'), i.get('status')))}"
        for i in (summary.get("issues") or [])
    )
    hist = ""
    if trend and trend.get("points"):
        items = ""
        for p in trend["points"]:
            sc = p.get("score")
            sc_text = "—" if sc is None else f"{sc:.0f}"
            items += (
                f"<li>#{e(p.get('job_id'))} · 分数 {e(sc_text)}"
                f" · {e(p.get('pages_crawled'))} 页 · {e(p.get('status'))}</li>"
            )
        hist = f"<h2>扫描历史</h2><ul class='hist'>{items}</ul>"
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SEO 体检摘要 · {e(summary.get('domain'))}</title>
<style>
body{{font:14px/1.7 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
color:#222;background:#faf9f6;margin:0;padding:40px 20px}}
.wrap{{max-width:900px;margin:0 auto;background:#fff;border:1px solid #e5e1d8;
border-radius:4px;padding:32px 36px}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:16px;margin:28px 0 10px;
border-bottom:1px solid #eee;padding-bottom:6px}}
.meta{{color:#8a8577;font-size:12px;font-family:ui-monospace,Menlo,monospace}}
.score{{font:600 44px/1 ui-monospace,Menlo,monospace;margin:14px 0}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{border:1px solid #eee;padding:6px 10px;text-align:left;vertical-align:top}}
th{{background:#f7f5f0;font-weight:600}} .u{{word-break:break-all;color:#666}}
code{{font:12px ui-monospace,Menlo,monospace;background:#f4f2ec;padding:1px 5px;border-radius:2px}}
.hist li{{margin:3px 0;font-family:ui-monospace,Menlo,monospace;font-size:12px}}
.note{{margin-top:26px;padding:12px 14px;background:#f7f5f0;border-left:3px solid #c98a2b;
color:#6b6455;font-size:12px}}
</style></head><body><div class="wrap">
<h1>SEO 体检摘要 · {e(summary.get('domain'))}</h1>
<div class="meta">导出时间 {_now()} · 覆盖页面 {e(summary.get('pages_crawled'))} 页</div>
<div class="score">{'—' if score is None else f'{score:.0f}'}</div>
<div class="meta">健康分 / 100{'（尚无可评分的扫描）' if score is None else ''}</div>
<h2>问题分布</h2>
<p>{' · '.join(f'{SEV_LABEL[k]} {counts.get(k, 0)}' for k in SEV_ORDER)}</p>
<h2>问题清单</h2>
<table><tr><th>严重级</th><th>规则</th><th>问题</th><th>页面</th><th>状态</th></tr>{rows}</table>
{hist}
<div class="note">本摘要从数据库重建，不含扫描现场的完整证据链；完整报告请在扫描时导出（CLI <code>--html</code> / <code>-o</code>）。</div>
</div></body></html>"""
