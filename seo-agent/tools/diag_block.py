import sys, glob, json
from collections import Counter

sys.path.insert(0, '.deps')
sys.path.insert(0, 'backend')
sys.path.insert(0, 'tools')

import verify_findings as vf  # 正常 import，不要用 importlib 手工加载

MARKERS = (
    "access denied", "just a moment", "checking your browser",
    "enable javascript and cookies", "cf-browser-verification",
    "attention required", "request unsuccessful", "captcha",
)

rows = []
for p in sorted(glob.glob('reports/fp_json_v3/*.json')):
    d = json.load(open(p))
    for iss in d.get('issues', []):
        u = iss.get('url')
        if not u:
            continue
        h = vf.fetch(u)
        if h is None:
            continue
        body = h.lower()
        by_marker = any(m in body for m in MARKERS)
        text = vf._visible_text(h)
        ntags = len(vf._tags(h, r"<(p|li|td|h[1-6])\b"))
        by_thin = (len(text) < 200 and ntags < 3)
        if by_marker or by_thin:
            rows.append((iss['code'], by_marker, by_thin, len(text), ntags, len(h)))

only_marker = [r for r in rows if r[1] and not r[2]]
only_thin = [r for r in rows if r[2] and not r[1]]
both = [r for r in rows if r[1] and r[2]]

print("被判反爬(取不到)的样本数:", len(rows))
print(f"  真反爬 markers 命中: {len(only_marker) + len(both)}")
print(f"  只因「极薄页」被判:  {len(only_thin)}   <-- 可能是误伤")
print(f"  两者都命中:          {len(both)}")

print("\n--- 只被「极薄页」条件命中的（最可疑）---")
for r in only_thin[:15]:
    print(f"  {r[0]:26} 可见文本{r[3]:5} 字符  块级标签{r[4]:3}  HTML{r[5]}B")
print(f"  ...共 {len(only_thin)} 条")

print("\n--- 只被 markers 命中的（应该是真反爬）---")
for r in only_marker[:10]:
    print(f"  {r[0]:26} 可见文本{r[3]:5} 字符  HTML{r[5]}B")
print(f"  ...共 {len(only_marker)} 条")

print("\n--- 受影响的 code 分布（极薄页那一批）---")
for code, n in Counter(r[0] for r in only_thin).most_common():
    print(f"  {code:26} {n}")
