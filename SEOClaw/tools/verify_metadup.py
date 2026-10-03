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


def norm(text):
    """比对前把实体和空白归一化。

    这轮又栽在这上：`PagerDuty&#x27;s` 解出来带实体、`&nbsp;` 是不换行空格。
    crawler 那边（lxml）解实体、规则里 `desc[:200]` 截断，
    我这边用 curl 正则裸抓，不归一化就对不上。
    """
    if not text:
        return ""
    t = html_mod.unescape(text)
    t = t.replace("\xa0", " ").replace("\u200b", "")
    return re.sub(r"\s+", " ", t).strip()


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
        matched, empty, detail = 0, 0, []
        for u in urls[:4]:
            desc, status = fetch_desc(u)
            if status != "ok":
                detail.append(f"{u.split('/', 3)[-1][:20]}:{status}")
                empty += 1
                continue
            if desc is None:
                # 这一页回访时**没有 description**。分两种：
                #  - 页面是 JS 壳（airbnb 只回 539 字节）／回访被挡 → 我根本没看到
                #  - 页面真有 description 但和规则记的不一样 → 页面变了
                # 两种都**不能判误报**。实测 airbnb.com 回源 539 字节、
                # kubernetes.io 的 releases 页面内容全变。
                empty += 1
                detail.append(f"{u.split('/', 3)[-1][:20]}:空")
                continue
                # ⚠️ 规则存的是 **200 字截断版**（base/__init__.py:229 `desc[:200]`），
            # 拿它跟现在原文的完整 description 全量比，比不上就是必然的。
            # 实测 www.automattic.com：规则记 199 字，原文 361 字，前缀完全相同。
            # 所以只能判「原文以规则记的内容开头」，不能判相等。
            same = (norm(desc) or "").startswith(norm(claimed) or "")
            matched += 1 if same else 0
            detail.append(f"{u.split('/', 3)[-1][:20]}:"
                          f"{'同' if same else '不同'}")

        if matched >= 2:
            tally[TRUE] += 1
            print(f"  真问题 {domain:<22} {matched} 个页面确实共用同一 description"
                  f"（规则称 {count} 页）", flush=True)
            print(f"          {' | '.join(detail)}", flush=True)
        elif empty >= len(urls[:4]):
            # 一个都没回访到 description → 我没测到，不是规则错
            tally[UNSURE] += 1
            print(f"  存疑   {domain:<22} {empty} 页回访没拿到 description，判不了"
                  f"（规则称 {count} 页）", flush=True)
            print(f"          {' | '.join(detail)}", flush=True)
        elif matched == 1:
            tally[UNSURE] += 1
            print(f"  存疑   {domain:<22} 只回访到 1 个，共用无法证实"
                  f"（规则称 {count} 页）", flush=True)
            print(f"          {' | '.join(detail)}", flush=True)
        else:
            tally[FALSE] += 1
            print(f"  误报   {domain:<22} 回访的页面都有 description 但都不是这个"
                  f"（规则称 {count} 页）", flush=True)
            print(f"          {' | '.join(detail)}", flush=True)

    print(f"\n=== 小结：真问题 {tally[TRUE]} · 误报 {tally[FALSE]} · 存疑 {tally[UNSURE]}",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())