#!/usr/bin/env python3
"""规则普查：注册了但从未在真实语料里触发过的规则。

## 为什么查这个

`og:image.broken` 被发现是条死规则：`og_image_status` 全库零写入，
规则永远拿不到数据 → 永不触发。但 `app.cli rules` 照样列出它，
测试手塞值照样绿。**注册 ≠ 活着。**

我那次是写完 tried_paths 后才意识到「死字段是靠肉眼 grep 偶然发现的」，
所以应该系统查一遍形态：注册了、但 107 站真实语料里一次都没触发过。

## 怎么读结果

「从未触发」本身**不等于**死规则，要分三类，不能一刀切：

1. **真死**：触发条件依赖一个永远为空的字段（如 og:image 的回访）。
   判据：规则的 guard 里读了一个全库零写入的键。
2. **罕见但合理**：条件本就少见（如 `noindex` 在正常站点上确实少见）。
3. **样本不够**：107 站 × 600 条里真的没碰上，不代表不该有。

所以这个脚本只负责**把名单列出来让人判**，不自动下结论。
自动判定会把这个工具变成第二个「没看到就下结论」的东西。

## 用法

    python3 tools/rule_census.py
"""
import glob
import json
import pathlib
import sys

BACKEND = pathlib.Path("/root/.openclaw/workspace/SEOClaw/backend")
CORPUS = pathlib.Path("/root/.openclaw/workspace/SEOClaw/reports/fp_json_v4")


def registered_codes() -> dict[str, set[str]]:
    """返回 {code: {market, ...}}。

    ⚠️ 必须存**集合**不能存单个市场。base 的 canonical.conflict、
    h1.missing、img.alt.generic 会被 google/baidu/cnh_eco 包一并返回
    （规则按市场过滤，不是各包独立定义）。我第一版写
    `out[code] = market.value`，后者覆盖前者，base 全被抹掉——
    「base 22 条」变成「base 0 条」、105 条变 39 条，工具反过来说
    「base 一条规则都没有」。**按错误口径输出的普查工具比没有更糟。**
    """
    sys.path.insert(0, str(BACKEND.parent / ".deps"))
    sys.path.insert(0, str(BACKEND))
    # ⚠️ registry 不在 app.audit 命名空间里，实际是 app.audit.engine.default_registry
    # （第一次写 from app.audit import registry 直接 ImportError——别照 __init__.py 猜。）
    from app.audit.engine import default_registry  # noqa: PLC0415
    from app.models import Market  # noqa: PLC0415

    registry = default_registry()

    out: dict[str, set[str]] = {}
    for market in Market:
        try:
            rules = registry.page_rules_for([market]) + registry.site_rules_for([market])
        except Exception:
            continue
        for r in rules:
            out.setdefault(r.code, set()).add(market.value)
    return out


def corpus_codes() -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in sorted(CORPUS.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for iss in d.get("issues", []):
            code = iss.get("code", "?")
            counts[code] = counts.get(code, 0) + 1
    return counts


def read_corpus_markets() -> set[str]:
    """语料实际扫了哪些市场。

    **必须读，不能假定全市场。** 我第一版拿全市场注册表去比一份
    base-only 的语料，于是把 83 条从未上场的规则算成「从未触发」。
    """
    out: set[str] = set()
    for f in sorted(CORPUS.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for m in d.get("markets") or []:
            out.add(m)
    return out


def main() -> int:
    reg = registered_codes()
    cnt = corpus_codes()
    if not reg:
        print("✗ 没读到注册规则表，检查 import 路径", file=sys.stderr)
        return 1

    # ⚠️ 关键：语料是 markets=['base'] 扫的。全市场注册表里有 83 条
    # google/baidu/cnh_eco 规则根本没在这次扫描里启用——把它们算进
    # 「从未触发」是拿没上场的规则说它没动。我第一版就犯了这个错：
    # 列出 20 条「注册但从未触发」，其中 hreflang/og 那批的结论**完全
    # 站不住**（数据层后来补齐了、extract 实跑能采到，是语料太旧）。
    # 工具给假结论比不给结论糟，所以这里只比 base，别的市场单列。
    corpus_markets = read_corpus_markets()
    scope = set(corpus_markets) or {"base"}

    in_scope_reg = {c: ms for c, ms in reg.items() if ms & scope}
    out_scope_reg = {c: ms for c, ms in reg.items() if not (ms & scope)}
    fired = sorted(set(in_scope_reg) & set(cnt))
    never = sorted(set(in_scope_reg) - set(cnt))
    ghost = sorted(set(cnt) - set(reg))

    print("=" * 70)
    print(f"语料市场 {sorted(scope)} · 该市场注册规则 {len(in_scope_reg)} 条")
    print(f"全市场去重后规则 {len(reg)} 条 · 语料 {sum(cnt.values())} 条发现项")
    print("=" * 70)
    print(f"\n触发过：{len(fired)} 条")
    for c in fired:
        print(f"  {cnt[c]:>4}×  {c}")

    print(f"\n⚠️ {sorted(scope)} 内注册但语料从未触发：{len(never)} 条")
    for c in never:
        print(f"   ?   {c}   ({','.join(sorted(in_scope_reg[c]))})")
    if never:
        print("   ↑ 逐条判：真死（依赖永远为空的字段）/ 罕见但合理 / 样本不够。")
        print("     不要一刀切当成死规则——那又是一个「没看到就下结论」。")

    print()
    print("=" * 70)
    print(f"🔴 未被本次语料覆盖的市场：{len(out_scope_reg)} 条规则")
    print("=" * 70)
    by_mkt: dict[str, list[str]] = {}
    for c, ms in out_scope_reg.items():
        for m in ms:
            if m not in scope:
                by_mkt.setdefault(m, []).append(c)
    for m, codes in sorted(by_mkt.items()):
        print(f"  {m}：{len(codes)} 条")
        for c in sorted(codes):
            print(f"      {c}")

    print()
    print("   ↑ 这些规则**一次都没在真实站点上跑过**，只有合成单测。")
    print("     单测能证明「给这个输入会触发」，证明不了「真站点上不乱触发」。")
    print("     这是准确率数字的真实覆盖面——报 93.3% 时必须一起说。")

    if ghost:
        print(f"\n🔴 语料里有但注册表没有：{len(ghost)} 条 —— 报告与代码不同步")
        for c in ghost:
            print(f"   {cnt[c]:>4}×  {c}")
    else:
        print("\n✓ 语料里的 code 全部能在注册表里找到（无幽灵 code）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())