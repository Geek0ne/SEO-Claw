#!/usr/bin/env bash
# 批量扫 200 个真实站点，用于重测准确率。
#
# 串行而不是并行：并发打几十个站等于自己开 ban 名单，
# 测出来的「准确率」会因为大量抓取失败而失真。宁可慢。
#
# 必须输出 JSON：markdown 会按根因聚合，聚合后 URL 丢了，
# 核对器没法回源，80% 的结论会变成「存疑」。
set -u

cd "$(dirname "$0")/../backend" || exit 1
SITES="${SITES:-/tmp/sites.txt}"
OUT="${OUT:-../reports/batch200}"
mkdir -p "$OUT"

ok=0; fail=0; total=0
while read -r host; do
    host=$(echo "$host" | sed 's/#.*//' | tr -d '[:space:]')
    [ -z "$host" ] && continue
    total=$((total+1))
    name=$(echo "$host" | tr '/.' '__')

    # 断点续跑：已经扫完的直接跳过
    if [ -s "$OUT/$name.json" ]; then ok=$((ok+1)); continue; fi

    echo "[$total] $host"
    PYTHONPATH=../.deps:. timeout 60 python3 -m seoclaw.cli scan \
        "https://$host/" --max-pages 3 --rps 1.5 \
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
        echo "    ok  $n 条"
        ok=$((ok+1))
    else
        echo "    fail"
        rm -f "$OUT/$name.json.tmp"
        fail=$((fail+1))
    fi
    # 每站一个进度文件，防止会话中断后彻底失联
    echo "$ok $fail" > "$OUT/progress.txt"
done < "$SITES"

echo "=== 完：成功 $ok 站，失败 $fail 站"
