#!/usr/bin/env python3
"""把「存疑」按原因拆开——先量，再决定写哪条规则。

为什么要先量：195 条存疑占第三批的 34%，是准确率的真正天花板。
但「存疑」不是一个原因造成的：无 url 的站点级规则、跨页比对、正文需要
人工看、JS 渲染页面…… 每种原因的攻克成本差一个数量级。不拆开就动手，
大概率把时间花在占比最小的那一类上。
"""
from __future__ import annotations

import concurrent.futures as cf
import glob
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

UA = "Mozilla/5.0 (compatible; SEOAgentAudit/1.0; +https://example.com/bot)"
_cache: dict[str, str | None] = {}

sys.path.insert(0, "tools")
import verify_findings as vf  # noqa: E402


def main() -> None:
    rows = []
    for p in sorted(glob.glob("reports/fp_json_v3/*.json")):
        site = p.rsplit("/", 1)[-1][:-5]
        d = json.load(open(p, encoding="utf-8"))
        for iss in d.get("issues", []):
            rows.append((iss.get("code", "?"), iss.get("url", ""), site,
                         iss.get("evidence") or {}))

    def work(r):
        code, url, site, ev = r
        v = vf.verify(code, url, vf.fetch(url), ev)
        return code, site, v.state, v.note, ev

    results = []
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for i, out in enumerate(ex.map(work, rows), 1):
            results.append(out)
            if i % 100 == 0:
                print(f"  …{i}/{len(rows)}", file=sys.stderr)

    unknown = [r for r in results if r[2] == "unknown"]
    print(f"\n总 {len(results)} 条，存疑 {len(unknown)} 条\n")

    # 归类：把 note 的自由文本收敛成少数几个可行动的原因
    def bucket(code: str, note: str) -> str:
        if not code:
            return "(no code)"
        if "无 url" in note:
            return "站点级规则：报告里没有 url，核对器无从回源"
        if "需按语种" in note:
            return "语种判定：需判断正文书写体系"
        if "需回源" in note or "sitemap" in note:
            return "站点级：需单独取 /sitemap.xml 与 robots.txt"
        if "需跨页比对" in note or "跨页" in note:
            return "跨页比对：需一次抓多个页面"
        if "是否冲突" in note or "canonical" in note:
            return "canonical：需判断两个 URL 是否同内容"
        if "是否有意" in note or "需人工" in note or "人工看" in note:
            return "需人工判断业务意图"
        if "JS 渲染" in note or "静态 HTML" in note:
            return "JS 渲染：静态 HTML 看不到元素"
        if "取不到页面" in note:
            return "取不到页面：反爬 / 风控"
        if "协议相对" in note:
            return "混合内容：需看页面实际协议"
        if "多语言" in note or "多语言站" in note:
            return "多语言：需判断该站是否该有"
        if "协议" in note:
            return "协议判定"
        return f"其他：{note[:40]}"

    bc = Counter(bucket(c, n) for c, _s, _st, n, _e in unknown)
    print("=== 存疑按原因 ===")
    for b, n in bc.most_common():
        print(f"  {n:4}  {b}")

    print("\n=== 存疑按规则（跨原因）===")
    for c, n in Counter(r[0] for r in unknown).most_common():
        print(f"  {n:4}  {c}")

    print("\n=== 按原因×规则 交叉（前 20）===")
    cross: dict[tuple[str, str], int] = Counter()
    for c, _s, _st, n, _e in unknown:
        cross[(bucket(c, n), c)] += 1
    for (b, c), n in cross.most_common(20):
        print(f"  {n:4}  [{c}] {b}")

    out = Path("/tmp") / "unknown_breakdown.json"
    out.write_text(
        json.dumps(
            [{"code": c, "site": s, "state": st, "note": n, "bucket": bucket(c, n)}
             for c, s, st, n, _e in unknown],
            ensure_ascii=False, indent=1,
        ),
        encoding="utf-8",
    )
    print(f"\n明细已写 {out}")


if __name__ == "__main__":
    main()
