#!/usr/bin/env python3
"""回源核对剩下 4 条规则的每一条，不抽样。

前几轮的教训，都写进判据里了：
- 规则数出来的是**子集**，不要求相等，只要求「报的都被原文证实」
- **没测到 ≠ 不存在**：回访失败或页面是 JS 壳，一律算 UNSURE，不算误报
- curl 必须带 `Accept-Language: zh-CN`（crawler 带了，接翻译的站返回整页中文）
- HTML 实体要解码，否则 `&#x27;` 永远对不上

一次跑完，最后打一张总账。
"""
import collections
import glob
import html as html_mod
import json
import re
import subprocess
import sys

UA = "Mozilla/5.0 (compatible; SEO-ClawVerifier/1.0)"
TRUE, FALSE, UNSURE = "true", "false", "unsure"
MARK = {TRUE: "真问题", FALSE: "误报 ", UNSURE: "存疑 "}


def fetch(url, timeout=18):
    """回访页面。返回 (html, status)。跟 crawler 对齐语言头。"""
    try:
        r = subprocess.run(
            ["curl", "-sL", "--compressed", "-m", str(timeout), "-A", UA,
             "-H", "Accept-Language: zh-CN,zh;q=0.9",
             "-o", "/dev/stdout", "-w", "\n__STATUS__%{http_code}",
             "--max-filesize", "4000000", url],
            capture_output=True, timeout=timeout + 10,
        )
        out = r.stdout.decode("utf-8", "replace")
    except Exception:
        return "", 0
    m = re.search(r"__STATUS__(\d+)\s*$", out)
    status = int(m.group(1)) if m else 0
    return (out[:m.start()] if m else out), status


# ---------- 各规则的判据 ----------

def v_title_too_short(html, ev, status):
    """规则 evidence 自带 title/length/min —— 拿原文 <title> 对一遍。"""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if not m:
        return f"原文里没有 <title>（状态 {status}），判不了", UNSURE
    real = html_mod.unescape(re.sub(r"\s+", " ", m.group(1))).strip()
    want_title = (ev.get("title") or "").strip()
    want_len, want_min = ev.get("length"), ev.get("min")
    detail = f"原文 title={real[:40]!r}（{len(real)} 字），规则称 {want_len} 字 < {want_min}"
    if want_len is None or want_min is None:
        return detail + "，证据缺阈值", UNSURE
    same = real[:40] == want_title[:40] or len(real) == want_len
    ok = same and len(real) < want_min
    return detail, (TRUE if ok else FALSE)


def v_soft404(html, ev, status):
    """200 + 正文极短。回访不到（超时/403）就不算误报。"""
    if status == 0:
        return "回访失败", UNSURE
    if status != 200:
        return f"回访状态 {status} ≠ 规则称的 200，说明站点变了或我被挡了", UNSURE
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    words = len(re.findall(r"\w+", text, re.UNICODE))
    want = ev.get("word_count")
    detail = f"回访 200，正文 {words} 词（规则称 {want}）"
    if want is None:
        return detail + "，证据缺计数", UNSURE
    # 正文确实这么少 → 规则的前��提成立；但「软 404」本身仍需人判断
    ok = words < 60
    return detail + ("，" if ok else "，页面现在内容充足"), \
        (TRUE if ok else UNSURE)


def v_mixed_content(html, ev, status):
    """https 页面里引 http:// 资源。"""
    n = len(re.findall(r"(?:src|href)\s*=\s*[\"']http://", html, re.I))
    want = len(ev.get("offending_resources") or [])
    return f"原文里 http:// 资源 {n} 处（规则列了 {want} 条）", \
        (TRUE if n > 0 else FALSE)


def v_alt_generic(html, ev, status):
    """alt 写成 logo/image/图片 这类通用词。"""
    generic = {"logo", "image", "img", "picture", "photo", "图片", "图像",
               "照片", "untitled", "placeholder", "icon", "banner", "1", "2", "3"}
    alts = re.findall(r"<img\b[^>]*\balt\s*=\s*[\"']([^\"']*)[\"']", html, re.I)
    bad = [a for a in alts if a.strip().lower() in generic]
    want = ev.get("generic_count")
    return f"原文 alt 共 {len(alts)} 个，其中通用词 {len(bad)} 个（规则称 {want}）", \
        (TRUE if bad else FALSE)


VERIFIERS = {
    "title.too_short": v_title_too_short,
    "soft404": v_soft404,
    "http.mixed_content": v_mixed_content,
    "img.alt.generic": v_alt_generic,
}


def main():
    only = sys.argv[1:] or list(VERIFIERS)
    grand = collections.Counter()
    for code in only:
        fn = VERIFIERS.get(code)
        if not fn:
            print(f"没 {code} 的核对器")
            continue
        issues = []
        for f in sorted(glob.glob("reports/batch200/*.json")):
            d = json.load(open(f))
            for iss in d.get("issues", []):
                if iss.get("code") == code:
                    issues.append((d["domain"], iss))
        if not issues:
            print(f"=== {code}：这批报告里没有它的样本\n", flush=True)
            continue
        tally = collections.Counter()
        print(f"=== {code}：{len(issues)} 条，逐条回源\n", flush=True)
        for domain, iss in issues:
            html, status = fetch(iss["url"])
            if not html:
                tally[UNSURE] += 1
                print(f"  {MARK[UNSURE]} {domain:<24} 回访没拿到内容", flush=True)
                continue
            detail, verdict = fn(html, iss.get("evidence") or {}, status)
            tally[verdict] += 1
            print(f"  {MARK[verdict]} {domain:<24} {detail}", flush=True)
        for k in (TRUE, FALSE, UNSURE):
            grand[k] += tally[k]
        print(f"--- {code} 小结：真问题 {tally[TRUE]} · 误报 {tally[FALSE]} "
              f"· 存疑 {tally[UNSURE]}\n", flush=True)

    print(f"=== 总账：真问题 {grand[TRUE]} · 误报 {grand[FALSE]} · 存疑 {grand[UNSURE]}",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())