#!/usr/bin/env python3
"""评分权重校准分析 —— 只读 JSON，不重新抓取。

要回答的问题
------------
1. 25 页样本下，现权重（critical 30 / high 15 / medium 5 / low 1）给出的
   健康分分布是否合理？哪些站被判 0~20 分？那些是真差还是采样产物？
2. 同一 severity 内部，受影响面 r 的分布是什么样？—— 这是校准的关键：
   权重是 severity 的函数，受影响面只做线性折算。如果 r 的分布高度集中在
   1.0（全站命中），那 5 页和 25 页会得到**完全相同**的扣分，样本量根本
   帮不上忙；反之 r 分散时提高页数才真的让分数变细。
3. 扣分主要来自哪几条 code？权重该不该按 code 微调，还是保持按 severity？

为什么不自动改权重
------------------
改权重需要「真实严重度」的人工标注，那是 PLAN P0-3 的原定义。
这里只做**可验证的观察**，把建议连同依据一起给出，由人决定。
自动反推出的权重会把我的猜测固化成「已校准」的数字——比拍脑袋更糟，
因为它看起来可信。
"""
from __future__ import annotations

import glob
import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from urllib.parse import urlparse

# 必须在脚本自身所在目录为基准算绝对路径：从仓库根运行时
# 「../backend」会指向仓库外面，ModuleNotFoundError: No module named 'app'。
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
# 依赖装在仓库根的 .deps（不是 site-packages），必须显式挂上，
# 否则 ModuleNotFoundError: No module named 'pydantic'。
sys.path.insert(0, os.path.join(_ROOT, ".deps"))
sys.path.insert(0, os.path.join(_ROOT, "backend"))
from seoclaw.models import Scope, Severity  # noqa: E402
from seoclaw.scoring import SEVERITY_WEIGHT, score  # noqa: E402


def host_of(u: str | None) -> str:
    try:
        return (urlparse(u or "").netloc or "").lower()
    except ValueError:
        return ""


def load(pattern: str) -> list[dict]:
    out = []
    for p in sorted(glob.glob(pattern)):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        if d.get("pages_crawled", 0) > 0:
            out.append(d)
    return out


def main() -> int:
    pattern = sys.argv[1] if len(sys.argv) > 1 else "reports/calib_json/*.json"
    sites = load(pattern)
    if not sites:
        print(f"没读到数据：{pattern}")
        return 1

    print(f"样本 {len(sites)} 站\n")

    # ---------- 1. 健康分分布 ----------
    rows = []
    for d in sites:
        issues = []
        for it in d.get("issues", []):
            sev = it.get("severity")
            if sev not in {s.value for s in Severity}:
                continue
            issues.append(
                type(
                    "I",
                    (),
                    {
                        "code": it.get("code", "?"),
                        "url": it.get("url"),
                        "severity": Severity(sev),
                        "scope": Scope(it.get("scope", "page")),
                    },
                )()
            )
        n = d.get("pages_crawled") or 1
        h, br = score(issues, n)
        rows.append((h, d.get("domain", "?"), n, br, d, issues))

    rows.sort()
    print("=" * 74)
    print(f"{'健康分':>6} {'页数':>5} {'扣分':>7}  站点")
    print("-" * 74)
    for h, dom, n, br, _, _ in rows:
        print(f"{h:6.1f} {n:5} {br['total_deduction']:7.1f}  {dom}")

    hs = [r[0] for r in rows]
    print("-" * 74)
    print(
        f"最低 {min(hs)} 最高 {max(hs)} 中位 {statistics.median(hs):.1f} "
        f"均值 {statistics.mean(hs):.1f}"
    )
    print(f"满分站 {sum(1 for h in hs if h >= 100)}/{len(hs)}  ·  低于 20 分 {sum(1 for h in hs if h < 20)} 站")

    # ---------- 2. 受影响面 r 的分布（校准的关键） ----------
    print("\n" + "=" * 74)
    print("受影响面 r（命中页数 / 总页数）分布 —— 按 severity")
    print("=" * 74)
    r_by_sev: dict[str, list[float]] = defaultdict(list)
    r_by_code: dict[str, list[float]] = defaultdict(list)
    for _, _, n, _, _, issues in rows:
        pages = max(n, 1)
        by_code: dict[str, set[str | None]] = defaultdict(set)
        for it in issues:
            by_code[it.code].add(it.url)
        for code, urls in by_code.items():
            r = min(1.0, len(urls) / pages)
            for it in issues:
                if it.code == code:
                    r_by_sev[it.severity.value].append(r)
                    r_by_code[code].append(r)
                    break
    for sev in ("critical", "high", "medium", "low"):
        rs = r_by_sev.get(sev) or []
        if not rs:
            continue
        at_full = sum(1 for r in rs if r >= 0.999)
        print(
            f"  {sev:9} n={len(rs):3}  "
            f"中位 r={statistics.median(rs):.3f}  "
            f"均值 r={statistics.mean(rs):.3f}  "
            f"全站命中(r=1.0) {at_full}/{len(rs)} = {at_full / len(rs) * 100:.0f}%"
        )

    # ---------- 3. 扣分来源 ----------
    print("\n" + "=" * 74)
    print("扣分来源 Top 15（按总扣分）—— 权重该不该按 code 微调")
    print("=" * 74)
    ded: dict[str, float] = defaultdict(float)
    cnt: Counter[str] = Counter()
    for _, _, _, br, _, _ in rows:
        for code, v in (br.get("per_code") or {}).items():
            ded[code] += float(v.get("deduction", 0.0))
            cnt[code] += 1
    tot = sum(ded.values()) or 1.0
    for code, v in sorted(ded.items(), key=lambda x: -x[1])[:15]:
        print(f"  {code:34} {v:8.1f}  {v / tot * 100:5.1f}%  出现 {cnt[code]} 次")

    # ---------- 4. 页数与分数的关系 ----------
    print("\n" + "=" * 74)
    print("页数 vs 扣分（验证「提高页数是否真的让分数更细」）")
    print("=" * 74)
    by_n: dict[int, list[float]] = defaultdict(list)
    for h, _, n, _, _, _ in rows:
        by_n[n].append(h)
    for n in sorted(by_n):
        v = by_n[n]
        print(f"  pages={n:4}  站数 {len(v):2}  健康分 中位 {statistics.median(v):6.1f}  范围 {min(v):.1f}~{max(v):.1f}")

    print(
        "\n结论口径：以上都是**观察**，不是结论。权重是否调整、调多少，"
        "需要先有「真实严重度」的人工标注——否则只是把猜测换个数字写死。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
