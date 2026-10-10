#!/usr/bin/env python3
"""量 soft404 判定该不该改，以及该改成什么。

当前状况
--------
我把 52 条 soft404 从 unknown 转成了 noisy，结果严格准确率从 96.8% 掉到
83.7%。原因很清楚：严格准确率 = 属实 ÷ 可判定，noisy 留在分母里但不算分。
每转一条存疑就得为它挨一次扣分。

**但这不代表我该回退。** 关键是要弄清楚：这些页面到底是「不是软 404」
（false_positive）还是「确实是软 404 但用户不用管」（noisy）？
这两个是不同的事实，不能靠哪个对数字好看来选。

核心疑点
--------
规则的 content_is_thin 来自 page.text，而 _extract_text 明确剥掉 nav/footer：
    doc.xpath("//script|//style|//nav|//footer|//header|//noscript")
所以「导航重的页面」正文数必然被压到 300 词以下。japanpost.jp 首页有
223 条站内出链，静态正文只有 74 字符——那不是空页面。

怎么判
------
正面取证：**把导航也算进去，看这个页面到底有没有内容。**
  - 全量可见文本（含导航页脚）很大 → 页面有内容，「薄」是抽取口径的
    假象 → 不是软 404 → false_positive
  - 全量可见文本也很小，且出链很少 → 真·空页面 → true_positive
  - 中间地带 → unknown

另外有一条更硬的：站点根 URL 定义上不可能是软 404——它是全站入口，
到处都链向它。kaggle.com/、japanpost.jp/、mashable.com/ 都在这一类。
"""
from __future__ import annotations

import concurrent.futures as cf
import glob
import json
import re
import subprocess
import sys
from urllib.parse import urlparse

UA = "Mozilla/5.0 (compatible; SEOAgentAudit/1.0; +https://example.com/bot)"


def fetch(url: str) -> str | None:
    try:
        r = subprocess.run(
            ["curl", "-sL", "--max-time", "20", "-A", UA, url],
            capture_output=True, text=True, timeout=25,
        )
        return r.stdout if r.stdout and "<html" in r.stdout.lower() else None
    except Exception:
        return None


def stripped_text(h: str) -> str:
    """模拟 trafilatura 的口径：剥掉 nav/footer 等。"""
    t = re.sub(r"<(script|style|nav|footer|header|noscript)\b[^>]*>.*?</\1>", " ", h,
               flags=re.I | re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t)).strip()


def full_text(h: str) -> str:
    """全量可见文本：只去掉 script/style，导航页脚都留着。"""
    t = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", h, flags=re.I | re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t)).strip()


rows = []
for p in sorted(glob.glob("reports/fp_json_v3/*.json")):
    d = json.load(open(p, encoding="utf-8"))
    for iss in d.get("issues", []):
        if iss["code"] == "soft404" and iss.get("url"):
            rows.append((d["domain"], iss["url"], iss.get("evidence") or {}))

print(f"soft404 带 url 共 {len(rows)} 条\n")


def work(r):
    dom, url, ev = r
    h = fetch(url)
    if h is None:
        return dom, url, ev, None
    path = urlparse(url).path.rstrip("/")
    return dom, url, ev, {
        "stripped": len(stripped_text(h)),
        "full": len(full_text(h)),
        "links": len(re.findall(r"<a\b[^>]*href\s*=", h, re.I)),
        "is_root": path in ("", "/"),
    }


with cf.ThreadPoolExecutor(max_workers=8) as ex:
    res = [x for x in ex.map(work, rows)]

ok = [x for x in res if x[3]]
print(f"能取到页面 {len(ok)} / {len(rows)}\n")

buckets = {"root": 0, "full>=800": 0, "full<800&links<10": 0, "灰区": 0}
print(f"{'判定':<20}{'条数':>5}   说明")
for dom, url, ev, m in sorted(ok, key=lambda x: -x[3]["full"]):
    if m is None:
        continue
    if m["is_root"]:
        verdict, why = "根 URL", "站点入口，定义上不是软 404"
        buckets["root"] += 1
    elif m["full"] >= 800:
        verdict, why = "有内容", f"含导航 {m['full']} 字符，薄是抽取口径"
        buckets["full>=800"] += 1
    elif m["full"] < 800 and m["links"] < 10:
        verdict, why = "疑似真空", f"全量 {m['full']} 字符 + 仅 {m['links']} 出链"
        buckets["full<800&links<10"] += 1
    else:
        verdict, why = "灰区", f"全量 {m['full']} / 出链 {m['links']}"
        buckets["灰区"] += 1
    print(f"  {dom:24} {verdict:<8} 剥后{m['stripped']:6} 全量{m['full']:7} "
          f"出链{m['links']:4}  {why}")

print("\n=== 汇总 ===")
for k, v in buckets.items():
    print(f"  {k:<22} {v}")
