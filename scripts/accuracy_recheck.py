#!/usr/bin/env python3
"""用缓存的原始 HTML 重新判定全部发现 —— 不重爬，几十秒。

⚠️ 为什么要有这一步：爬虫的 pages 表**不存原始 HTML**，所以事后复核拿到的
永远是「另一时刻的页面」。站点改版、按地区返回不同内容、A/B 实验，都会让
「证据相反」变成假矛盾。

所以本脚本把结果分成三类，且只有「可判定」的才进分母：

    true          回源证据支持规则判定
    false         回源证据确实反对规则判定 —— 这是真误报
    inconclusive  抓取时与回源不是同一版本，**不能算误报**

⚠️ 把无法判定的算成错，会让人去改本来正确的规则 —— 那比误报本身更糟。
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from accuracy_run import VERIFIERS  # noqa: E402

CACHE = "/tmp/accuracy_raw.db"

# ⚠️ logo 型 <h1> 不算内容 H1。forever21 / nature / ifeng / smashingmagazine
# 把 logo 塞进 <h1 class="header__logo">，页面确实没有内容级 H1 ——
# 规则判「没有」是对的，我第一版复核器「见到 <h1> 就算过」把尺子放太松。
_LOGO_H1 = re.compile(r"logo|brand|wordmark|site-?name", re.I)


def has_content_h1(h: str) -> bool:
    for m in re.finditer(r"<h1\b([^>]*)>", h, re.I):
        if not _LOGO_H1.search(m.group(1)):
            return True
    return False


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default=str(ROOT / "docs" / "accuracy_report.json"))
    ap.add_argument("--out", default=str(ROOT / "docs" / "accuracy_recheck.json"))
    a = ap.parse_args()
    rep = json.loads(Path(a.report).read_text("utf-8"))
    con = sqlite3.connect(CACHE)

    tp = fp = inc = 0
    fp_by_code: Counter = Counter()
    inc_by_code: Counter = Counter()

    for r in rep["results"]:
        for f in r.get("findings", []):
            code = f["code"]
            row = con.execute("SELECT status, body FROM raw WHERE url=?",
                              (f["url"],)).fetchone()
            if row is None or not row[1]:
                inc += 1
                inc_by_code[code] += 1
                continue
            _st, html = row
            if code == "h1.missing":
                real = not has_content_h1(html)
            elif code in VERIFIERS:
                v = VERIFIERS[code]
                val = v.fn(html)
                real = bool(val) if v.problem_when_true else not bool(val)
            else:
                inc += 1
                inc_by_code[code] += 1
                continue
            if real:
                tp += 1
            else:
                fp += 1
                fp_by_code[code] += 1

    checked = tp + fp
    out = {
        "true_positive": tp,
        "false_positive": fp,
        "inconclusive": inc,
        "adjudicable": checked,
        "precision_on_adjudicable": round(tp / checked, 4) if checked else None,
        "precision_if_inconclusive_all_true":
            round((tp + inc) / (tp + inc + fp), 4) if (tp + inc + fp) else None,
        "precision_if_inconclusive_all_false":
            round(tp / (tp + fp), 4) if (tp + fp) else None,
        "false_positive_by_code": dict(fp_by_code.most_common()),
        "inconclusive_by_code": dict(inc_by_code.most_common()),
    }
    Path(a.out).write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
