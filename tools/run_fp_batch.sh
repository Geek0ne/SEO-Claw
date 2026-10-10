#!/usr/bin/env bash
# 批量扫描真实站点，用于 M0 误报回归验收。
#
# 两个坑（都踩过）：
# 1) 串行而非并行：并发打 24 个站等于自己开 ban 名单，测出来的准确率会因
#    「大量抓取失败」而失真。宁可慢，也要干净样本。
# 2) **必须输出 JSON，不能用 markdown**：markdown 会按根因聚合，聚合后一行
#    只剩「影响 N 个页面」，**URL 丢了**，核对器就没法回源，导致 80% 的结论
#    变成「存疑」。第一版就是这么废掉的。
#
# 站点清单里的 # 注释行必须跳过：第一版没跳，把注释当域名扫了，
# 白白产出 4 份垃圾报告，还把「完成数」虚报到 11。
set -u

cd "$(dirname "$0")/../backend" || exit 1
SITES="../tools/fp_sites.txt"
OUT="../reports/fp_json"
mkdir -p "$OUT"

ok=0; fail=0
while read -r host; do
    host=$(echo "$host" | sed 's/#.*//' | tr -d '[:space:]')
    [ -z "$host" ] && continue
    name=$(echo "$host" | tr '/.' '__')
    [ -s "$OUT/$name.json" ] && { ok=$((ok+1)); continue; }

    echo "=== $host"
    PYTHONPATH=../.deps:. timeout 90 python3 -m seoclaw.cli scan \
        "https://$host/" --max-pages 5 --rps 1.5 \
        --no-verify-canonical --json > "$OUT/$name.json.tmp" 2>/dev/null

    if python3 -c "
import json,sys
try:
    d=json.load(open('$OUT/$name.json.tmp'))
    sys.exit(0 if d.get('pages_crawled',0)>0 else 1)
except Exception: sys.exit(1)
" 2>/dev/null; then
        mv "$OUT/$name.json.tmp" "$OUT/$name.json"
        n=$(python3 -c "import json;print(len(json.load(open('$OUT/$name.json')).get('issues',[])))" 2>/dev/null)
        echo "    OK  发现 $n 条"
        ok=$((ok+1))
    else
        echo "    FAIL（超时/被封/非 HTML）"
        rm -f "$OUT/$name.json.tmp"
        fail=$((fail+1))
    fi
done < "$SITES"

echo "=== 完成：成功 $ok 站，失败 $fail 站"
