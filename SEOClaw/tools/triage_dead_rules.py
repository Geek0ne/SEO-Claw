#!/usr/bin/env python3
"""判 20 条「注册但从未触发」的规则：是死规则，还是罕见/样本不够。

## 判据（按顺序，先命中先算数）

1. **依赖字段没有采集位** → 真死。规则读 `page.X`，但 `Page` 模型没有 X，
   或 `extract.py` 从不赋 X。这时它永远拿到默认值，永远不触发。
   ——与 og:image 同类：`og_image_status` 全库零写入。
2. **依赖 site_facts 键全库零写入** → 真死（同上）。
3. **依赖数据层不支持（需回访/需渲染/需外部 API）** → 真死或需重做。
4. **字段有、采集有，只是 107 站里确实没碰上** → 不是死规则，
   是样本不够。记下来，不动。

## 为什么必须逐条判

这 20 条里混着两类：
- `hreflang.*` —— Page 模型**根本没有 hreflang 字段**（Google agent 自己也
  说了「数据层根本不支持」），所以它是结构性死规则；
- `og.basic_missing` —— og 字段确实采集了，可能只是这 107 站都写了 og。

一刀切说「20 条全死」和一刀切说「20 条都正常」都是没做功课。
"""
import ast
import pathlib
import re
import sys

BACKEND = pathlib.Path("/root/.openclaw/workspace/SEOClaw/backend/app")

NEVER_FIRED = [
    "depth.excessive", "hreflang.inconsistent_with_lang", "hreflang.self_reference_missing",
    "hreflang.suspicious_target", "hreflang.x_default_missing", "icp.filing_missing",
    "lang.missing", "lang.not_html_lang", "meta.chinese_semantic_incomplete",
    "mobile.landing_page_missing", "og.basic_missing", "og.image_broken",
    "orphan.page", "robots.baiduspider_not_allowed", "schema.missing",
    "title.chinese_too_long", "title.pixel_overflow", "viewport.missing",
    "viewport.not_responsive", "wechat.sogou_not_indexable",
]


def page_fields() -> set[str]:
    """Page 模型声明的字段。"""
    src = (BACKEND / "models.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Page":
            out = set()
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    out.add(stmt.target.id)
            return out
    return set()


def facts_written() -> set[str]:
    """全库被写入的 site_facts 键。"""
    pat = re.compile(r'(?:site_facts|facts)\s*\[\s*["\'](\w+)["\']\s*\]\s*=')
    out: set[str] = set()
    for p in BACKEND.rglob("*.py"):
        if "__pycache__" in str(p):
            continue
        out.update(pat.findall(p.read_text(encoding="utf-8", errors="replace")))
    return out


def rule_source(code: str) -> tuple[pathlib.Path, str] | None:
    for p in BACKEND.rglob("*.py"):
        if "__pycache__" in str(p):
            continue
        src = p.read_text(encoding="utf-8", errors="replace")
        if f'"{code}"' in src or f"'{code}'" in src:
            return p, src
    return None


def main() -> int:
    fields = page_fields()
    written = facts_written()
    extract_src = (BACKEND / "extract.py").read_text(encoding="utf-8", errors="replace")

    print(f"Page 字段 {len(fields)} 个 · site_facts 已写入键 {len(written)} 个\n")
    dead, alive = [], []
    for code in NEVER_FIRED:
        found = rule_source(code)
        if not found:
            alive.append((code, "源码里找不到，判据不够"))
            continue
        path, src = found
        reasons = []

        # 1. Page 字段：规则读了 page.X，但 Page 没有 X
        for attr in sorted(set(re.findall(r'page\.(\w+)', src))):
            if attr not in fields and attr not in {"url", "status_code", "error", "is_html"}:
                reasons.append(f"读 page.{attr} 但 Page 模型无此字段")

        # 2. facts 键：规则读 ctx.site_facts.get('X')，但全库没人写 X
        for key in sorted(set(re.findall(r'site_facts\.get\(["\'](\w+)["\']\)', src))):
            if key not in written:
                reasons.append(f"读 site_facts[{key}] 但全库零写入")

        # 3. og 字段是否真的被 extract 采集
        for attr in ("og_image", "og_title", "og_description"):
            if f"page.{attr}" in src and f"page.{attr} =" not in extract_src:
                reasons.append(f"读 page.{attr} 但 extract.py 从不赋值")

        (dead if reasons else alive).append((code, "; ".join(sorted(set(reasons))) or "字段与采集都在", path.name))

    print("=" * 72)
    print(f"🔴 真死规则：{len(dead)} 条")
    print("=" * 72)
    for code, why, f in dead:
        print(f"  {code:<38} {why}")
        print(f"  {'':<38} ({f})")

    print()
    print("=" * 72)
    print(f"🟢 不是死规则（字段与采集都在，只是 107 站没碰上）：{len(alive)} 条")
    print("=" * 72)
    for code, why, f in alive:
        print(f"  {code:<38} {why}")

    print()
    print("结论：注册表列着但结构性不可能触发的规则，应该")
    print("      （a）在注册时挡掉，或（b）显式标注「数据层不支持」。")
    print("      否则用户看 seoclaw.cli rules 会以为这些在查——与 og:image 同类。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())