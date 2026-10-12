#!/usr/bin/env python3
"""准确率核对：跑一批真站 → 拿真规则结果 → 逐条复核是否属实。

## 为什么走 HTTP 而不是直接调 scan_service

第一版我照印象写 `run_scan(session, *, site_id, url, markets, ...)`，
结果漏了 `session` 位置参数和 `markets`，还捏了个根本不存在的
`get_or_create_site`。今天在这上面栽过太多次。

而服务已经跑着、接口已经验过 —— **走 HTTP 就不用再猜任何签名**，
也顺带证明了「接口这条路」本身是通的。

## 这个脚本测什么

**精确率** = 报出来的问题里有多少条确实属实。

⚠️ **它不测召回率**。「该报的有没有漏」需要穷举所有可能问题，穷举不完。
把精确率说成「准确率」会误导人 —— 漏报的那一半根本不在分母里。

## 复核：不过解析层，直接回源 grep

每条能自动复核的问题，都**重新抓一次原始 HTML、用正则直接验**，而不是
拿提取层的字段当真值 —— 两边都用提取层等于自己判自己。

⚠️ **不能自动复核的**（`soft404` 像不像 404 页、`content.thin` 薄不薄、
`title.too_short` 写短是不是浪费）单独进 needs_human 桶，**绝不混进
分母**。混进去等于拿「看着像」充数，那个数字不能叫准确率。

⚠️ **「抓不到」不等于「问题属实」**：对方 403 / 超时 / JS 注入时，回源也
拿不到证据。这类记 `unreachable`，**同样不进分母** —— 宁可样本小，
不可假装。

用法：
    python scripts/accuracy_run.py --limit 5 --pages 2
    python scripts/accuracy_run.py --out docs/accuracy_report.json
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict, field
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "docs" / "accuracy_corpus_200.txt"
API = "http://127.0.0.1:8077/api/v1"
CACHE_DB = "/tmp/accuracy_raw.db"

# 抓取时的请求头。⚠️ 必须和 crawler 一致，否则接到的页面可能不同，
# 拿不同版本的 HTML 去复核同一个问题，结论就不成立了。
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (compatible; SEOAgentBot/0.1; "
                   "+https://seo.geek0ne.com/bot) Python-httpx"),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


# ══════════════════════════════════════════════════════════
# 复核器
# ══════════════════════════════════════════════════════════

# ⚠️ logo 型 <h1> 不算内容 H1。forever21 / nature / ifeng / smashingmagazine
# 都是把 logo 塞进 <h1 class="header__logo">，页面确实没有内容级 H1 ——
# 规则判「没有」是对的，是我第一版复核器「见到 <h1> 就算过」把尺子放得太松。
_LOGO_H1 = re.compile(r"logo|brand|wordmark|site-?name", re.I)


def r_has_h1(h):
    """⚠️ logo 型 H1 不算内容标题，**空 H1 也不算**。

    forever21/nature/ifeng/smashingmagazine 把 logo 塞进
    `<h1 class="header__logo">`；qzone 是 `<h1><i class="...logo"></i></h1>`；
    chinaz 是 `<h1><a><img src=...></h1>`。这三种页面确实没有内容级 H1，
    规则判「没有」是对的。
    """
    for m in re.finditer(r"<h1\b([^>]*)>(.*?)</h1>", h, re.I | re.S):
        attrs, inner = m.group(1), m.group(2)
        if _LOGO_H1.search(attrs) or _LOGO_H1.search(inner):
            continue
        text = re.sub(r"<[^>]+>", "", inner).strip()
        if text:
            return True
        # 内容只有一个 <img>/<svg>/<i> 且没有可读文字 → 仍是图标，不是标题
        if re.fullmatch(r"""\s*(?:<a[^>]*>)?\s*<(?:img|svg|i|span)\b[^>]*>\s*(?:</(?:img|svg|i|span)>)?\s*(?:</a>)?\s*""",
                        inner, re.I | re.S):
            continue
        if re.search(r"""<(?:img|svg|i)\b""", inner, re.I):
            continue
    return False
def r_has_title(h):
    """⚠️ 必须判**内容**，不能只判标签在不在。

    实跑抓到 ganji.com / ele.me：`<title></title>` —— 标签在，内容空。
    空的 title **就是没有 title**，规则判对了，是我第一版复核器
    「见到 <title 就放过」把它算成误报。
    """
    for m in re.finditer(r"<title\b[^>]*>(.*?)</title>", h, re.I | re.S):
        if m.group(1).strip():
            return True
    return False
def r_has_meta(h):
    """⚠️ 同 title：`<meta name="description" content="">` 是**空描述**，
    等于没有。gitlink / dedao / mailchimp 三条都是这个形态。"""
    for m in re.finditer(r"""<meta[^>]*>""", h, re.I):
        tag = m.group(0)
        if not re.search(r"""name\s*=\s*["']description["']""", tag, re.I):
            continue
        c = re.search(r"""content\s*=\s*["']([^"']*)["']""", tag, re.I)
        if c and c.group(1).strip():
            return True
    return False
def r_has_viewport(h): return bool(re.search(
    r"""<meta[^>]+name\s*=\s*["']viewport["']""", h, re.I))
def r_has_canonical(h): return bool(re.search(
    r"""rel\s*=\s*["']canonical["']""", h, re.I))
def r_has_lang(h):
    m = re.search(r"<html\b[^>]*>", h, re.I)
    return bool(m and re.search(r"""\blang\s*=\s*["'][a-z]""", m.group(0), re.I))
def r_img_no_alt(h):
    n = 0
    for m in re.finditer(r"<img\b[^>]*>", h, re.I):
        if not re.search(r"""\balt\s*=\s*["'][^"']*["']""", m.group(0), re.I):
            n += 1
    return n
def r_link_noanchor(h):
    """数「没有任何可读文本」的 <a>：包里只有 img/svg/图标，且没有 aria-label。

    ⚠️ 必须排除 aria-hidden 的图标链接：它们是 UI 图标（菜单、社交），
    本来就不该有文字锚。把它们算进「链接没文字」正是这条误报的主因。
    """
    n = 0
    for m in re.finditer(r"<a\b([^>]*)>(.*?)</a>", h, re.I | re.S):
        attrs, inner = m.group(1), m.group(2)
        if not re.search(r"\bhref\b", attrs, re.I):
            continue
        if re.search(r'aria-hidden\s*=\s*["\']true["\']', attrs, re.I):
            continue
        if re.search(r'aria-label\s*=\s*["\'][^"\']+["\']', attrs, re.I):
            continue
        text = re.sub(r"<[^>]+>", "", inner).strip()
        if not text and not re.search(r"alt\s*=\s*['\"][^'\"]+['\"]", inner, re.I):
            n += 1
    return n


def r_img_alt_missing(h):
    """数真正缺 alt 的 <img>。

    ⚠️ alt="" 是**合法的**（装饰性图片应当为空 alt），
    屏幕阅读器会跳过它。只有**根本没有 alt 属性**才是缺失。
    这两条混为一谈会让规则看起来在抓真问题，其实一半是装饰图。
    """
    n = 0
    for m in re.finditer(r"<img\b[^>]*>", h, re.I):
        if not re.search(r"\balt\s*=", m.group(0), re.I):
            n += 1
    return n


def r_noindex(h):     return bool(re.search(
    r"""<meta[^>]+name\s*=\s*["']robots["'][^>]*noindex""", h, re.I))


@dataclass(frozen=True, slots=True)
class V:
    fn: object
    #: fn 返回 True 表示「问题确实存在」
    problem_when_true: bool = True


VERIFIERS: dict[str, V] = {
    "h1.missing":        V(r_has_h1, problem_when_true=False),
    "title.missing":     V(r_has_title, problem_when_true=False),
    "meta.missing":      V(r_has_meta, problem_when_true=False),
    "viewport.missing":  V(r_has_viewport, problem_when_true=False),
    "canonical.missing": V(r_has_canonical, problem_when_true=False),
    "lang.missing":      V(r_has_lang, problem_when_true=False),
    "img.alt_missing":   V(r_img_no_alt),
    "link.noanchor":     V(r_link_noanchor),
    "img.alt.missing":   V(r_img_alt_missing),
    "noindex.present":   V(r_noindex),
}

AUTO = set(VERIFIERS)


# ══════════════════════════════════════════════════════════


def init_cache() -> None:
    con = sqlite3.connect(CACHE_DB)
    con.execute("CREATE TABLE IF NOT EXISTS raw("
                "url TEXT PRIMARY KEY, status INTEGER, body TEXT)")
    con.commit()
    con.close()


def cached_get(url: str) -> tuple[int, str] | None:
    con = sqlite3.connect(CACHE_DB)
    row = con.execute("SELECT status, body FROM raw WHERE url=?", (url,)).fetchone()
    con.close()
    return (row[0], row[1]) if row else None


def store(url: str, status: int, body: str) -> None:
    con = sqlite3.connect(CACHE_DB)
    con.execute("INSERT OR REPLACE INTO raw(url,status,body) VALUES(?,?,?)",
                (url, status, body[:2_000_000]))
    con.commit()
    con.close()


def fetch_raw(url: str) -> tuple[int, str] | None:
    """回源抓原始 HTML。⚠️ 抓不到返回 None —— 不能据此判「问题不存在」。"""
    hit = cached_get(url)
    if hit:
        return hit
    try:
        r = httpx.get(url, timeout=20, follow_redirects=True, headers=HEADERS)
    except Exception:
        return None
    body = r.text if r.status_code < 400 else ""
    store(url, r.status_code, body)
    return (r.status_code, body) if body else None


@dataclass
class Finding:
    domain: str
    code: str
    severity: str
    url: str
    verdict: str          # true / false / needs_human / unreachable
    note: str = ""


@dataclass
class SiteResult:
    domain: str
    status: str = "pending"
    pages: int = 0
    total_issues: int = 0
    auto_checked: int = 0
    true_pos: int = 0
    false_pos: int = 0
    human: int = 0
    unreachable: int = 0
    false_by_code: dict = field(default_factory=dict)
    error: str = ""
    elapsed: float = 0.0
    findings: list = field(default_factory=list)


def audit_site(domain: str, pages: int) -> SiteResult:
    res = SiteResult(domain=domain)
    t0 = time.monotonic()
    try:
        c = httpx.Client(timeout=180, trust_env=False)
        s = c.post(f"{API}/sites", json={"domain": domain, "markets": ["base"]})
        if s.status_code == 409:
            lst = c.get(f"{API}/sites").json()
            site_id = next(x["id"] for x in lst if x["domain"] == domain)
        else:
            s.raise_for_status()
            site_id = s.json()["id"]

        # ⚠️ 扫描偶发 500（并发写 SQLite 时 flush 失败 → PendingRollbackError）。
        # 实测两个并发扫描都正常，所以不是必现。**重试而不是降并发** ——
        # 降并发会让 200 站跑完的时间翻倍，而重试只多花几秒。
        for attempt in range(3):
            sc = c.post(f"{API}/sites/{site_id}/scan", json={"max_pages": pages})
            if sc.status_code < 500:
                break
            time.sleep(2 + attempt * 3)
        sc.raise_for_status()
        res.pages = sc.json().get("pages_crawled") or 0

        # ⚠️ 这个接口返回 {"total": N, "items": [...]}，不是裸数组。
        # 我第一版当数组用，三个站全炸在 `string indices must be integers`。
        page = c.get(f"{API}/sites/{site_id}/issues",
                     params={"limit": 200}).json()
        iss = page.get("items") or []
        res.total_issues = page.get("total", len(iss))

        for it in iss:
            code = it["code"]
            url = it.get("url") or f"https://www.{domain}/"
            f = Finding(domain=domain, code=code,
                        severity=it["severity"], url=url, verdict="needs_human")
            if code not in AUTO:
                res.human += 1
                res.findings.append(f)
                continue
            got = fetch_raw(url)
            if got is None:
                f.verdict = "unreachable"
                f.note = "回源抓不到（403/超时/JS 注入），无法证实也无法证伪"
                res.unreachable += 1
                res.findings.append(f)
                continue
            # ⚠️ pages 表不存原始 HTML，所以回源拿到的是**另一个时间点**的页面。
            # 站点在此期间改版 / 按地区返回不同内容，都会让「证据相反」变成
            # 假矛盾。这类只能标 inconclusive，**不能算误报** ——
            # 把无法判定的算成错，会让人去改本来正确的规则。
            _st, html = got
            v = VERIFIERS[code]
            val = v.fn(html)
            real = bool(val) if v.problem_when_true else not bool(val)
            res.auto_checked += 1
            if real:
                f.verdict = "true"
                res.true_pos += 1
            else:
                f.verdict = "false"
                res.false_pos += 1
                res.false_by_code[code] = res.false_by_code.get(code, 0) + 1
                f.note = f"回源 HTML 证据与判定相反（matched={val}）"
            res.findings.append(f)
        res.status = "ok"
        c.close()
    except Exception as exc:  # noqa: BLE001
        res.status = "error"
        res.error = f"{type(exc).__name__}: {exc}"[:200]
    res.elapsed = round(time.monotonic() - t0, 1)
    return res


def load_corpus(limit: int | None, path: Path | None = None) -> list[str]:
    f = path or CORPUS
    out = [line.strip() for line in f.read_text(encoding="utf-8").splitlines()
           if line.strip() and not line.startswith("#")]
    return out[:limit] if limit else out


def summarize(rs: list[SiteResult]) -> dict:
    ok = [r for r in rs if r.status == "ok"]
    tp = sum(r.true_pos for r in ok)
    fp = sum(r.false_pos for r in ok)
    hr = sum(r.human for r in ok)
    un = sum(r.unreachable for r in ok)
    checked = tp + fp
    by_code: Counter = Counter()
    for r in ok:
        for code, n in r.false_by_code.items():
            by_code[code] += n
    return {
        "sites_total": len(rs),
        "sites_ok": len(ok),
        "sites_error": len([r for r in rs if r.status != "ok"]),
        "pages_crawled": sum(r.pages for r in ok),
        "issues_reported": sum(r.total_issues for r in ok),
        "auto_checked": checked,
        "true_positive": tp,
        "false_positive": fp,
        "needs_human": hr,
        "unreachable": un,
        # ⚠️ 分母只含自动复核过的。needs_human 与 unreachable 不进分母。
        "precision": round(tp / checked, 4) if checked else None,
        "false_positive_by_code": dict(by_code.most_common()),
        "top_falses": by_code.most_common(10),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--pages", type=int, default=2)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", default=str(ROOT / "docs" / "accuracy_report.json"))
    ap.add_argument("--corpus", default=None,
                    help="语料文件路径；默认 200 站知名站语料")
    args = ap.parse_args()

    init_cache()
    corpus = Path(args.corpus) if args.corpus else CORPUS
    sites = load_corpus(args.limit, corpus)
    print(f"语料 {len(sites)} 站 / 每站 {args.pages} 页 / {args.workers} 并发", flush=True)

    results: list[SiteResult] = []
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for res in ex.map(lambda d: audit_site(d, args.pages), sites):
            results.append(res)
            done += 1
            print(f"[{done}/{len(sites)}] {res.domain:<28} {res.status:<6} "
                  f"pages={res.pages:<3} 自动复核={res.auto_checked:<3} "
                  f"真={res.true_pos:<3} 假={res.false_pos:<3} "
                  f"人工={res.human:<3} 不可达={res.unreachable}", flush=True)
            Path(args.out).write_text(json.dumps(
                {"summary": summarize(results),
                 "results": [asdict(r) for r in results]},
                ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== 汇总 ===")
    print(json.dumps(summarize(results), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())