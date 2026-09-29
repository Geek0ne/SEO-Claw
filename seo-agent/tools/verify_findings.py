#!/usr/bin/env python3
"""
独立回源核对器 —— M0 误报回归验收。**读 JSON，不读 markdown。**

为什么必须重写
--------------
第一版读 markdown 报告，结果 44 条里 36 条判成「存疑」，只拿到 8 条可判定，
算出的 75% 是噪声不是测量。根因：**markdown 会按根因聚合**，一行只剩
「影响 N 个页面」，**URL 被丢掉了**，核对器没法回源。JSON 保留每条 issue 的 url。

为什么判定逻辑要独立写
--------------------
拿规则自己的代码去「验证」规则等于自己给自己判卷：规则错了，复现出来的也是错的。
这里**完全不 import app.audit 下的任何代码**，只用原始正则读 live HTML。

三档判定，不只有对/错：
- true_positive  属实，且确实是用户该管的问题
- noisy          属实，但不该让用户管（噪音规则：Google 不看/可选增强）
- false_positive 不属实（漏看、解析错、页面已变）
- unknown        取不到页面 / 需人工判断，不计入分母
"""
from __future__ import annotations

import concurrent.futures as cf
import glob
import html as htmllib
import json
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

UA = "Mozilla/5.0 (compatible; SEOAgentAudit/1.0; +https://example.com/bot)"
_cache: dict[str, str | None] = {}


def fetch(url: str, timeout: int = 20) -> str | None:
    if url in _cache:
        return _cache[url]
    out = None
    try:
        r = subprocess.run(
            ["curl", "-sL", "--max-time", str(timeout), "-A", UA, url],
            capture_output=True, text=True, timeout=timeout + 5,
        )
        if r.stdout and "<html" in r.stdout.lower():
            out = r.stdout
    except Exception:
        out = None
    _cache[url] = out
    return out


def _tags(h: str, pat: str) -> list[str]:
    return re.findall(pat, h, re.I | re.S)


def _strip(s: str) -> str:
    return htmllib.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def _attr(tag: str, name: str) -> str | None:
    m = re.search(rf'\b{name}\s*=\s*["\']([^"\']*)["\']', tag, re.I)
    if m:
        return m.group(1)
    m = re.search(rf'\b{name}\s*=\s*([^\s>]+)', tag, re.I)
    return m.group(1) if m else None


def _meta(h: str, key: str) -> str | None:
    for tag in _tags(h, r"<meta[^>]*>"):
        k = (_attr(tag, "property") or _attr(tag, "name") or "").strip().lower()
        if k == key.lower():
            c = _attr(tag, "content")
            if c:
                return c.strip()
    return None


def _title(h: str) -> str | None:
    m = re.search(r"<title[^>]*>(.*?)</title>", h, re.I | re.S)
    return _strip(m.group(1)) if m else None


def _visible_text(h: str) -> str:
    return _strip(re.sub(r"<(script|style|nav|footer)[^>]*>.*?</\1>", " ", h, flags=re.I | re.S))


@dataclass
class Verdict:
    state: str
    note: str = ""


# 每条规则的独立判定。刻意不复用 app.audit 的任何代码。
def verify(code: str, url: str, h: str | None, ev: dict[str, Any]) -> Verdict:
    if h is None:
        return Verdict("unknown", "取不到页面")

    if code == "title.missing":
        return Verdict("true_positive", "无 <title>") if _title(h) is None else Verdict("false_positive", "有 title")

    if code in ("title.too_short", "title.too_long"):
        t = _title(h)
        if t is None:
            return Verdict("false_positive", "无 title")
        n = len(t)
        # ⚠️ 中文标题阈值不同（30 vs 60），必须自己判断，不能硬编码 60。
        # 我第一版核对器写死 60，把 csdn.net 的中文长标题误判成「规则误报」，
        # 其实规则判对了——是我的测量工具错了。
        cjk = sum(1 for c in t if ord(c) > 0x2E80)
        is_cjk = cjk > 0 and cjk / max(len(t), 1) >= 0.3
        lo, hi = ev.get("min", 15), ev.get("max", 30 if is_cjk else 60)
        hit = n < lo if code == "title.too_short" else n > hi
        if not hit:
            return Verdict("false_positive", f"len={n} 阈值[{lo},{hi}]")
        # 站名/品牌名：词数少 + 全大写开头 + 无功能词 → 属实但不该让用户改
        words = [w for w in t.split() if w]
        stop = {"a", "an", "the", "of", "for", "to", "in", "on", "and", "or",
                "with", "from", "at", "by", "is", "are", "best", "top", "guide"}
        namey = 0 < len(words) <= 3 and not (set(w.lower() for w in words) & stop) \
            and all(w[:1].isupper() or w.isupper() for w in words if w[:1].isalpha())
        return Verdict("noisy", f"title={t!r} len={n}，疑似站名") if namey \
            else Verdict("true_positive", f"title={t!r} len={n}")

    if code in ("meta.missing", "meta.too_short", "meta.too_long", "meta.duplicate"):
        d = _meta(h, "description")
        if code == "meta.missing":
            return Verdict("true_positive", "无 description") if d is None else Verdict("false_positive", "有 description")
        if d is None:
            return Verdict("false_positive", "无 description，前提不成立")
        n = len(d)
        if code == "meta.too_short":
            return Verdict("true_positive", f"len={n}") if n < 50 else Verdict("false_positive", f"len={n}")
        if code == "meta.too_long":
            return Verdict("true_positive", f"len={n}") if n > 160 else Verdict("false_positive", f"len={n}")
        return Verdict("unknown", f"len={n}")

    if code == "canonical.missing":
        has = re.search(r"<link[^>]+rel\s*=\s*[\"']?canonical", h, re.I)
        return Verdict("true_positive", "无 canonical") if not has else Verdict("false_positive", "有 canonical")

    if code == "canonical.conflict":
        m = re.search(r"<link[^>]+rel\s*=\s*[\"']?canonical[^>]*>", h, re.I)
        if not m:
            return Verdict("false_positive", "无 canonical")
        href = (_attr(m.group(0), "href") or "").rstrip("/")
        same = href.lower() in (url.rstrip("/").lower(), "")
        return Verdict("false_positive", f"canonical 与自身一致: {href[:50]}") if same \
            else Verdict("unknown", f"canonical={href[:50]}，是否冲突取决于是否同内容")

    if code == "h1.missing":
        return Verdict("true_positive", "无 h1") if not _tags(h, r"<h1[\s>]") else Verdict("false_positive", "有 h1")

    if code == "h1.multiple":
        texts = [_strip(x) for x in _tags(h, r"<h1[^>]*>(.*?)</h1>")]
        if len(texts) <= 1:
            return Verdict("false_positive", f"h1={len(texts)}")
        uniq = len({t.lower() for t in texts if t})
        # 多个 h1 且内容互不相同 → Google 不惩罚，属噪音
        return Verdict("noisy", f"h1={len(texts)} 去重={uniq}") if uniq == len(texts) \
            else Verdict("true_positive", f"h1={len(texts)} 含重复({uniq})")

    if code == "img.alt.missing":
        miss = [t for t in _tags(h, r"<img[^>]*>") if _attr(t, "alt") is None]
        if not miss:
            return Verdict("false_positive", "全部有 alt")
        deco = sum(1 for t in miss if re.search(r'class\s*=\s*["\'][^"\']*(logo|avatar|icon)', t, re.I))
        return Verdict("noisy", f"{len(miss)} 张无 alt，其中装饰图 {deco}") if deco else \
            Verdict("true_positive", f"{len(miss)} 张无 alt")

    if code == "og.basic_missing":
        miss = [k for k in ("og:title", "og:description", "og:image") if _meta(h, k) is None]
        return Verdict("noisy", f"缺 {miss}，仅影响分享卡片") if miss else Verdict("false_positive", "og 齐全")

    if code == "noindex.present":
        r = (_meta(h, "robots") or "").lower()
        return Verdict("unknown", f"robots={r!r}，是否有意需业务判断") if "noindex" in r \
            else Verdict("false_positive", f"robots={r!r}")

    if code == "soft404":
        return Verdict("unknown", f"正文 {len(_visible_text(h))} 字，需人工看内容")

    if code == "schema.missing":
        return Verdict("noisy", "无 JSON-LD（可选增强）") if "ld+json" not in h.lower() \
            else Verdict("false_positive", "有 JSON-LD")

    if code == "lang.missing":
        m = re.search(r"<html[^>]*>", h, re.I)
        lv = _attr(m.group(0), "lang") if m else None
        return Verdict("false_positive", f"lang={lv!r}") if lv else Verdict("true_positive", "html 无 lang")

    if code == "lang.not_html_lang":
        return Verdict("unknown", "需按语种判定书写体系")

    if code == "viewport.missing":
        return Verdict("true_positive", "无 viewport") if _meta(h, "viewport") is None else Verdict("false_positive", "有 viewport")

    if code == "viewport.not_responsive":
        v = (_meta(h, "viewport") or "")
        bad = []
        if re.search(r"user-scalable\s*=\s*no", v, re.I):
            bad.append("user-scalable=no")
        if re.search(r"width\s*=\s*\d{3,}", v, re.I):
            bad.append("固定像素宽度")
        return Verdict("true_positive", f"viewport={v!r} {bad}") if bad else Verdict("false_positive", f"viewport={v!r}")

    if code == "title.pixel_overflow":
        t = _title(h)
        if t is None:
            return Verdict("false_positive", "无 title")
        # 独立估算像素宽：CJK 约 14px/字，其余约 7.5px/字
        w = sum(14 if ord(c) > 0x2E80 else 7.5 for c in t)
        return Verdict("true_positive", f"约 {w:.0f}px > 580") if w > 580 else Verdict("false_positive", f"约 {w:.0f}px")

    if code == "title.duplicate":
        return Verdict("unknown", "需跨页比对")

    if code == "sitemap.missing":
        return Verdict("unknown", "需回源 /sitemap.xml 与 robots 声明")

    if code == "http.mixed_content":
        # 协议相对 URL（//host/x）在 https 页面上不构成混合内容，
        # 所以只作提示、不计入准确率分母。
        n = len(re.findall(r'(?:src|href)\s*=\s*["\']//', h, re.I))
        return Verdict("unknown", f"协议相对 URL {n} 处，需看页面协议")

    if code == "link.noanchor":
        bad = [t for t in _tags(h, r"<a\b[^>]*>.*?</a>") if not _strip(t) and "aria-label" not in t and "title=" not in t]
        return Verdict("true_positive", f"{len(bad)} 个空链接") if bad else Verdict("false_positive", "无空链接")

    if code.startswith("hreflang."):
        has = re.search(r'rel\s*=\s*["\'][^"\']*alternate', h, re.I) and "hreflang" in h.lower()
        if code == "hreflang.missing":
            return Verdict("unknown", "多语言站需判断是否该有")
        return Verdict("false_positive", "有 hreflang") if has else Verdict("true_positive", "确实无 hreflang 声明")

    return Verdict("unknown", f"核对器未覆盖 {code}")


FIELD = {"true_positive": "tp", "false_positive": "fp", "noisy": "noisy", "unknown": "unknown"}


@dataclass
class Stat:
    tp: int = 0
    fp: int = 0
    noisy: int = 0
    unknown: int = 0
    samples: list[str] = field(default_factory=list)


def main(argv: list[str]) -> int:
    paths: list[str] = []
    for a in argv[1:]:
        paths.extend(sorted(glob.glob(a)) if "*" in a else [a])
    if not paths:
        print("用法: verify_findings.py reports/fp_json/*.json", file=sys.stderr)
        return 2

    rows: list[tuple[str, str, str, dict]] = []
    for p in paths:
        site = p.rsplit("/", 1)[-1][:-5]
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        for iss in d.get("issues", []):
            rows.append((iss.get("code", "?"), iss.get("url", ""), site, iss.get("evidence") or {}))

    print(f"站点 {len(paths)} 个，发现项 {len(rows)} 条，开始回源核对…\n", file=sys.stderr)

    def work(r):
        code, url, site, ev = r
        if not url:
            return (code, site, "unknown", "无 url（站点级规则）", ev)
        v = verify(code, url, fetch(url), ev)
        return (code, site, v.state, v.note, ev)

    results: list[tuple[str, str, str, str, dict]] = []
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for i, out in enumerate(ex.map(work, rows), 1):
            results.append(out)
            if i % 40 == 0:
                print(f"  …{i}/{len(rows)}", file=sys.stderr)

    stats: dict[str, Stat] = defaultdict(Stat)
    for code, site, state, note, _ev in results:
        s = stats[code]
        f = FIELD.get(state, "unknown")
        setattr(s, f, getattr(s, f) + 1)
        if state in ("false_positive", "noisy") and len(s.samples) < 3:
            s.samples.append(f"{site}: {note}")

    print(f"\n{'规则':<32}{'报':>4}{'属实':>5}{'噪音':>5}{'误报':>5}{'存疑':>5}  {'准确率'}")
    print("-" * 76)
    tot = Stat()
    for code in sorted(stats, key=lambda c: -(stats[c].tp + stats[c].fp + stats[c].noisy)):
        s = stats[code]
        dec = s.tp + s.fp + s.noisy
        acc = f"{s.tp / dec * 100:.0f}%" if dec else "—"
        if dec and s.noisy:
            acc += f" (+{s.noisy / dec * 100:.0f}% 噪音)"
        print(f"{code:<32}{s.tp+s.fp+s.noisy+s.unknown:>4}{s.tp:>5}{s.noisy:>5}{s.fp:>5}{s.unknown:>5}  {acc}")
        for k in ("tp", "fp", "noisy", "unknown"):
            setattr(tot, k, getattr(tot, k) + getattr(s, k))

    dec = tot.tp + tot.fp + tot.noisy
    print("-" * 76)
    print(f"站点 {len(paths)} · 报告 {len(results)} 条 · 可判定 {dec} 条 · 存疑 {tot.unknown} 条")
    print(f"  属实 {tot.tp} · 属实但噪音 {tot.noisy} · 真误报 {tot.fp}")
    if dec:
        print(f"\n  严格准确率 {tot.tp / dec * 100:.1f}%  (PLAN 要求 ≥90%)")
        print(f"  含噪音容忍 {(tot.tp + tot.noisy) / dec * 100:.1f}%")

    act = [(c, s) for c, s in stats.items() if s.fp or s.noisy]
    if act:
        print("\n=== 需要处置 ===")
        for c, s in sorted(act, key=lambda x: -(x[1].fp + x[1].noisy)):
            if s.samples:
                print(f"\n{c}  (误报 {s.fp} / 噪音 {s.noisy})")
                for x in s.samples:
                    print(f"    - {x}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
