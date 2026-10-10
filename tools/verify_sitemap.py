#!/usr/bin/env python3
"""回源核对 sitemap.missing —— 逐个回访报告里 tried_paths 列出的路径。

关键：**遍历所有 tried_paths**，不是只看第一个。
（上一版 verify_batch2.py 循环里第一行就 return 了，
只看第一个路径就下结论 —— 又是一次「没测到 ≠ 通过」。）

判据：body 里含 <urlset 或 <sitemapindex> 才是真 sitemap。
返回 HTML（软 404 / 首页回退）不算。
"""
import glob
import json
import subprocess
import sys
import collections

UA = "Mozilla/5.0 (compatible; SEO-ClawVerifier/1.0)"
TRUE, FALSE, UNSURE = "true", "false", "unsure"


def fetch(url, timeout=12):
    try:
        r = subprocess.run(
            ["curl", "-sL", "--compressed", "-m", str(timeout),
             "-A", UA, "--max-filesize", "8000000", url],
            capture_output=True, timeout=timeout + 10,
        )
        return r.stdout.decode("utf-8", "replace"), r.returncode
    except Exception:
        return "", -1


def inspect(url):
    body, rc = fetch(url)
    if not body:
        return "empty", UNSURE
    low = body[:4000].lower()
    if "<urlset" in low:
        return "真 sitemap（urlset）", FALSE   # 规则漏报 → 这是误报
    if "<sitemapindex" in low:
        return "真 sitemap（sitemapindex）", FALSE
    if low.lstrip().startswith("<?xml") or "<html" in low or "<!doctype" in low:
        kind = "HTML（软 404 或首页回退）" if "<html" in low or "<!doctype" in low else "XML 但不是 sitemap"
        return f"{kind}，{len(body)} 字节", TRUE
    return f"无法识别，{len(body)} 字节", UNSURE


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    targets = []
    for f in sorted(glob.glob("reports/batch200/*.json")):
        d = json.load(open(f))
        for iss in d.get("issues", []):
            if iss.get("code") == "sitemap.missing":
                targets.append((d["domain"], iss))

    print(f"=== sitemap.missing：{len(targets)} 条待核，抽 {min(limit, len(targets))} 个站\n")
    tally = collections.Counter()
    for domain, iss in targets[:limit]:
        tried = (iss.get("evidence") or {}).get("tried_paths") or []
        if not tried:
            tally[UNSURE] += 1
            print(f"  ?? {domain:<26} 报告没带 tried_paths")
            continue
        # 逐个回访**所有**试过的路径，任何一个是真 sitemap 就是误报
        found, checked = None, []
        for t in tried:
            desc, verdict = inspect(t["url"])
            checked.append(f"{t['url'].split('/', 3)[-1][:26]}→{t.get('status')}/{desc}")
            if verdict == FALSE:
                found = t["url"]
                break
        if found:
            tally[FALSE] += 1
            print(f"  误报  {domain:<26} ❗{found} 是真 sitemap")
            print(f"        试过：{', '.join(checked[:4])}")
        else:
            v = TRUE if all("HTML" in c for c in checked) else UNSURE
            tally[v] += 1
            mark = {TRUE: "真问题", UNSURE: "存疑 "}.get(v, "?")
            print(f"  {mark} {domain:<26} {len(tried)} 个路径都不是 sitemap")
            print(f"        {', '.join(checked[:3])}")

    print(f"\n=== 小结：真问题 {tally[TRUE]} · 误报 {tally[FALSE]} · 存疑 {tally[UNSURE]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
