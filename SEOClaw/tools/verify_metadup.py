#!/usr/bin/env python3
"""回源核对 meta.duplicate —— 按规则的**真实判据**（跨页面）。

前两版核对器都查错了对象：
1. verify_batch2.py 数「同一页里有几个 <meta description>」——
   规则 `MetaDuplicate` 走的是 `ctx.meta_index`，是**跨页面**比对。
2. verify_fixed.py 里我直接标 None「暂不支持」——等于没核。

真判据（base/__init__.py）：
    for desc, urls in ctx.meta_index.items():
        if len(urls) < 2: continue
        yield site_issue({"meta_description": desc, "url_count": len(urls),
                          "sample_urls": urls[:10]})

所以核对方式是：拿 evidence 里的 meta_description 和 sample_urls，
回访其中**两个以上** URL，看它们是不是真的用同一个 description。

只回访一个不算数——那只能证明这一页有，看不出「重复」。
"""
import collections
import glob
import html as html_mod
import json
import re
import subprocess
import sys

UA = "Mozilla/5.0 (compatible; SEOClawVerifier/1.0)"
TRUE, FALSE, UNSURE = "true", "false", "unsure"
_DESC_RE = re.compile(
    r"<meta[^>]+name=[\"']description[\"'][^>]*content=[\"']([^\"']*)[\"']",
    re.I,
)
_DESC_ALT_RE = re.compile(
    r"<meta[^>]+content=[\"']([^\"']*)[\"'][^>]*name=[\"']description[\"']",
    re.I,
)


def fetch_desc(url, timeout=15):
    """回访一个 URL，返回它的 description（没找到返回 None）。

    ⚠️ 两件事必须跟 crawler 对齐，否则我核的不是它抓的那份东西：

    1. `Accept-Language: zh-CN` —— crawler 带这个头，接了翻译的站点
       （Discourse / bellroy / airbnb）会把整页机器翻译成中文再返回。
       我不带 → 拿到英文 → 和报告里的中文描述对不上 → 误判「误报」。
    2. HTML 实体解码 —— `PagerDuty&#x27;s` vs `PagerDuty's`。

    这两条都不是规则的错，是我 curl 的时候少做了功课。
    """
    try:
        r = subprocess.run(
            ["curl", "-sL", "--compressed", "-m", str(timeout), "-A", UA,
             "-H", "Accept-Language: zh-CN,zh;q=0.9",
             "--max-filesize", "3000000", url],
            capture_output=True, timeout=timeout + 8,
        )
        html = r.stdout.decode("utf-8", "replace")
    except Exception:
        return None, "timeout"
    if not html:
        return None, "empty"
    m = _DESC_RE.search(html) or _DESC_ALT_RE.search(html)
    if not m:
        return None, "ok"
    return html_mod.unescape(m.group(1)).strip(), "ok"


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    targets = []
    for f in sorted(glob.glob("reports/batch200/*.json")):
        d = json.load(open(f))
        for iss in d.get("issues", []):
            if iss.get("code") == "meta.duplicate":
                targets.append((d["domain"], iss))

    print(f"=== meta.duplicate（跨页面判据）：{len(targets)} 条待核，"
          f"抽 {min(limit, len(targets))}\n", flush=True)
    tally = collections.Counter()
    for domain, iss in targets[:limit]:
        ev = iss.get("evidence") or {}
        claimed = (ev.get("meta_description") or "").strip()
        urls = ev.get("sample_urls") or []
        count = ev.get("url_count")
        if not claimed or len(urls) < 2:
            tally[UNSURE] += 1
            print(f"  ?? {domain:<24} 证据不足（描述或 sample_urls 不全）", flush=True)
            continue

        # 回访 sample_urls，看有几个真的带着同一个 description
        matched, detail = 0, []
        for u in urls[:4]:
            desc, status = fetch_desc(u)
            if status != "ok":
                detail.append(f"{u.split('/', 3)[-1][:20]}:{status}")
                continue
            same = desc is not None and desc.strip() == claimed
            matched += 1 if same else 0
            detail.append(f"{u.split('/', 3)[-1][:20]}:"
                          f"{'同' if same else ('空' if desc is None else '不同')}")

        if matched >= 2:
            tally[TRUE] += 1
            print(f"  真问题 {domain:<22} {matched} 个页面确实共用同一 description"
                  f"（规则称 {count} 页）", flush=True)
            print(f"          {' | '.join(detail)}", flush=True)
        elif matched == 1:
            tally[UNSURE] += 1
            print(f"  存疑   {domain:<22} 只回访到 1 个，共用无法证实"
                  f"（规则称 {count} 页）", flush=True)
            print(f"          {' | '.join(detail)}", flush=True)
        else:
            tally[FALSE] += 1
            print(f"  误报   {domain:<22} 回访的页面都没有这个 description", flush=True)
            print(f"          {' | '.join(detail)}", flush=True)

    print(f"\n=== 小结：真问题 {tally[TRUE]} · 误报 {tally[FALSE]} · 存疑 {tally[UNSURE]}",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())