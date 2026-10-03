#!/usr/bin/env python3
"""回源核对 sitemap.missing —— 逐个回访 tried_paths，逐行落盘。

上一轮教训：
1. 只看第一个 tried_path 就下结论 → 必须遍历全部。
2. 长时间闷头跑、中断就全丢 → 逐行 flush + 后台跑。
"""
import glob
import json
import subprocess
import sys

UA = "Mozilla/5.0 (compatible; SEOClawVerifier/1.0)"


def out(s):
    print(s, flush=True)


def classify(url, timeout=8):
    try:
        r = subprocess.run(
            ["curl", "-sL", "--compressed", "-m", str(timeout), "-A", UA, url],
            capture_output=True, timeout=timeout + 5,
        )
        b = r.stdout.decode("utf-8", "replace")
    except Exception:
        return "timeout", 0
    low = b[:5000].lower()
    if "<urlset" in low or "<sitemapindex" in low:
        return "SITEMAP", len(b)
    if "<html" in low or "<!doctype" in low:
        return "html", len(b)
    if not b:
        return "empty", 0
    return "other", len(b)


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    targets = []
    for f in sorted(glob.glob("reports/batch200/*.json")):
        d = json.load(open(f))
        for iss in d.get("issues", []):
            if iss.get("code") == "sitemap.missing":
                targets.append((d["domain"], iss))

    out(f"=== sitemap.missing：{len(targets)} 条待核，抽 {min(limit, len(targets))} 个站\n")
    true_n = false_n = 0
    for domain, iss in targets[:limit]:
        tried = (iss.get("evidence") or {}).get("tried_paths") or []
        notes, found = [], None
        for t in tried:
            kind, n = classify(t["url"])
            path = t["url"].split("/", 3)[-1][:22]
            notes.append(f"{path}:{t.get('status')}/{kind}")
            out(f"    · {domain} {path} → {kind} ({n}B)")   # 逐行落盘
            if kind == "SITEMAP":
                found = t["url"]
                break
        if found:
            false_n += 1
            out(f"  误报  {domain:<24} ❗ 真 sitemap: {found}\n")
        else:
            true_n += 1
            out(f"  真问题 {domain:<24} {' | '.join(notes[:5])}\n")

    out(f"=== 小结：真问题 {true_n} · 误报 {false_n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
