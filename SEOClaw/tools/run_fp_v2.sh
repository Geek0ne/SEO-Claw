#!/usr/bin/env bash
# 第二批误报回归 —— 与 run_fp_batch.sh 同口径，站点表换成 fp_sites_v2.txt
#
# ⚠️ 三个坑都踩过了，这里逐条对应：
#   1) PYTHONPATH 的 `.` 指 app 包 → 必须在 backend/ 下跑（cwd 错位 29 站全 FAIL）
#   2) nohup 挂在工具调用的进程组里会被连带回收 → 用 setsid 脱离
#   3) 启动时先扫孤儿 .tmp，合法就提升 → 中断后可续跑
set -u
ROOT=/root/.openclaw/workspace/SEOClaw
cd "$ROOT" || exit 1
OUT=reports/fp_json_v2
[ -d "$OUT" ] && mv "$OUT" "${OUT}_bak_$(date +%H%M%S)"
mkdir -p "$OUT"

python3 - <<'PY'
import glob, json, os
for tmp in glob.glob("reports/fp_json_v2/*.json.tmp"):
    dst = tmp[:-4]
    try:
        ok = json.load(open(tmp, encoding="utf-8")).get("pages_crawled", 0) > 0
    except Exception:
        ok = False
    os.replace(tmp, dst) if ok else os.remove(tmp)
    print(f"  续跑：{'提升' if ok else '丢弃'} {os.path.basename(dst)}")
PY

echo "开始第二批抓取（5 页/站）$(date +%H:%M:%S)"
ok=0; fail=0
while read -r host; do
    case "$host" in \#*|"") continue ;; esac
    out="$OUT/${host//\//_}.json"
    if [ -s "$out" ]; then ok=$((ok+1)); continue; fi
    echo "=== $host"
    ( cd "$ROOT/backend" && PYTHONPATH="$ROOT/.deps:." timeout 120 python3 -m app.cli scan \
        "https://$host/" --max-pages 5 --rps 1.5 \
        --no-verify-canonical --json ) > "$out.tmp" 2>>/tmp/fp_v2_err.log
    if python3 -c "
import json,sys
try:
    d=json.load(open('$out.tmp')); sys.exit(0 if d.get('pages_crawled',0)>0 else 1)
except Exception: sys.exit(1)
" 2>/dev/null; then
        mv "$out.tmp" "$out"; ok=$((ok+1))
        python3 -c "
import json; d=json.load(open('$out'))
print('    OK  %d 页  %d 条  分 %.1f' % (d['pages_crawled'], len(d.get('issues',[])), d.get('health_score') or 0))
" 2>/dev/null || echo "    OK"
    else
        fail=$((fail+1)); rm -f "$out.tmp"
        echo "    FAIL"
    fi
done < tools/fp_sites_v2.txt
echo "第二批结束 $(date +%H:%M:%S)：成功 $ok / 失败 $fail"
