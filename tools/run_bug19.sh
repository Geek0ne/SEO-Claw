#!/usr/bin/env bash
# 重扫那批被 sitemap 索引判定 bug 误报的站，验证修复在真实站点上生效。
# 单测只证了 mock 场景；真站才是判据。
set -u
cd "$(dirname "$0")/../backend" || exit 1
OUT="../reports/bugfix"
mkdir -p "$OUT"
ok=0; still=0
while read -r host; do
    [ -z "$host" ] && continue
    echo "[$host]"
    PYTHONPATH=../.deps:. timeout 90 python3 -m seoclaw.cli scan \
        "https://$host/" --max-pages 1 --rps 1.5 \
        --no-verify-canonical --json > "$OUT/$host.json.tmp" 2>/dev/null
    if python3 -c "
import json,sys
try:
    d=json.load(open('$OUT/$host.json.tmp'))
    sys.exit(0 if d.get('pages_crawled',0)>0 else 1)
except Exception: sys.exit(1)
" 2>/dev/null; then
        mv "$OUT/$host.json.tmp" "$OUT/$host.json"
        has=$(python3 -c "
import json
d=json.load(open('$OUT/$host.json'))
print('YES' if any(i['code']=='sitemap.missing' for i in d.get('issues',[])) else 'NO')
" 2>/dev/null)
        if [ "$has" = "YES" ]; then
            echo "    仍报缺 sitemap ❌"; still=$((still+1))
        else
            echo "    不报了 ✅"; ok=$((ok+1))
        fi
    else
        echo "    抓取失败"; rm -f "$OUT/$host.json.tmp"
    fi
    echo "$ok $still" > "$OUT/progress.txt"
done < /tmp/bug19.txt
echo "=== 完：修好 $ok 站，仍误报 $still 站"
