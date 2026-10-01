#!/usr/bin/env python3
"""扫「读得出、没人写」的 site_facts / evidence 键。

## 为什么写这个

`sitemap.missing` 的 evidence 里有 `tried_paths`，全库 grep 发现**只有一处读、
零处写**，恒为 `[]`。于是报告里「tried_paths = []、error = None」看起来就像
「没去试就判站点没有 sitemap」——正是这条硬要求最忌讳的样子。

判定本身没错（读了 `SitemapFinder.discover` 实现，它确实在跑），错的是**呈现出来
的证据不足以支撑结论**。

一个死字段是靠肉眼 grep 偶然发现的，那就系统扫一遍同类：
- `ctx.site_facts.get("X")` / `facts["X"]` 在规则里被读
- 全代码库有没有任何地方写 `facts["X"] = ...`

读得出但没人写 → 这个证据字段恒为空 → 报告在渲染一个不存在的证据。

**不判「规则错」**：字段为空只说明证据链断了，规则判定可能仍然正确。
但用户看到的就是「没试就判没有」，所以必须列出来逐个看。
"""
import ast
import pathlib
import re
import sys
from collections import defaultdict

ROOT = pathlib.Path("/root/.openclaw/workspace/seo-agent/backend/app")

# facts / site_facts / evidence 里被**读**的键
READ_SITES = re.compile(r'(?:site_facts|facts|ctx\.site_facts)\s*(?:\.get\(|\[)\s*["\'](\w+)["\']')
READ_EVIDENCE = re.compile(r'evidence\s*(?:\.get\(|\[)\s*["\'](\w+)["\']')
# 被**写**的键
WRITE_FACTS = re.compile(r'(?:site_facts|facts)\s*\[\s*["\'](\w+)["\']\s*\]\s*=')
WRITE_EVIDENCE = re.compile(r'["\'](\w+)["\']\s*:\s*')


def py_files() -> list[pathlib.Path]:
    return [p for p in ROOT.rglob("*.py") if "__pycache__" not in str(p)]


def main() -> int:
    reads_facts: dict[str, set[str]] = defaultdict(set)
    writes_facts: dict[str, set[str]] = defaultdict(set)
    reads_ev: dict[str, set[str]] = defaultdict(set)

    for p in py_files():
        src = p.read_text(encoding="utf-8", errors="replace")
        for key in READ_SITES.findall(src):
            reads_facts[key].add(p.name)
        for key in WRITE_FACTS.findall(src):
            writes_facts[key].add(p.name)
        for key in READ_EVIDENCE.findall(src):
            reads_ev[key].add(p.name)

    print("=" * 70)
    print("A. site_facts：读得出、没人写（证据恒为空）")
    print("=" * 70)
    dead_facts = sorted(set(reads_facts) - set(writes_facts))
    if not dead_facts:
        print("  （无）")
    for key in dead_facts:
        where = ", ".join(sorted(reads_facts[key]))
        print(f"  ✗ facts[{key!r}]  只在 {where} 被读，全库无写入")

    print()
    print("=" * 70)
    print("B. evidence：字典字面量里出现过的键 vs 全库出现位置")
    print("=" * 70)
    # evidence 的键是规则里写字面量产生的，扫全库出现处做对照
    all_src = {p.name: p.read_text(encoding="utf-8", errors="replace") for p in py_files()}
    suspicious = []
    for key, files in sorted(reads_ev.items()):
        # 找只出现在 render/report 消费侧、规则侧没有写入的地方
        producers = [f for f, s in all_src.items()
                     if f"{key!r}" in s or f'"{key}"' in s]
        if len(producers) <= 1:
            suspicious.append((key, files))
    if suspicious:
        for key, files in suspicious:
            print(f"  ? evidence[{key!r}]  读于 {', '.join(sorted(files))}，写入侧仅 {len(producers)} 处")
    else:
        print("  （无明显只读键）")

    print()
    print("=" * 70)
    print("C. 结论")
    print("=" * 70)
    if dead_facts:
        print(f"  {len(dead_facts)} 个 site_facts 键是死字段，报告在渲染空证据。")
        print("  逐个判断：是「真没实现」还是「实现了但忘了接线」。")
    else:
        print("  site_facts 无死字段。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())