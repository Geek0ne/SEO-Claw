#!/usr/bin/env bash
# 评分权重校准专用抓取 —— 与 run_fp_batch.sh 的区别只有两点：
#
#   1. --max-pages 25（误报回归用 5）
#   2. 目标目录 reports/calib_json（不覆盖误报回归数据）
#
# 为什么要单独一批：SEVERITY_WEIGHT / SCORE_SCALE 的扣分系数是
# 「受影响页面占比」。5 页样本下占比只能取 0.2 的整数倍，单个 critical
# 问题就吃掉 30 分——实测 gymshark 健康分 3.0 纯粹是采样产物。
# 用这种样本反推权重，等于把采样噪声固化成「看起来校准过的新值」。
#
# ⚠️ 与 rerun_true.sh 同一个坑：见那个文件顶部说明。
#    「文件已存在就跳过」不报错、输出还很好看。这里同样先归档。
set -u
ROOT=/root/.openclaw/workspace/SEOClaw
cd "$ROOT" || exit 1

PAGES="${PAGES:-25}"
if [ "${KEEP_CALIB:-0}" != "1" ] && [ -d reports/calib_json ]; then
    mv reports/calib_json "reports/calib_json_bak_$(date +%H%M%S)"
fi
mkdir -p reports/calib_json

# ⚠️ 孤儿 .tmp 抢救：上一轮脚本在 mv 之前被 kill（nohup 挂在工具调用
# 的进程组里，工具会话结束整个进程组被回收），留下抓取完成但没转正的
# .tmp。jvns.ca 那一站白抓了——不报错、不续跑，输出还停在「=== jvns.ca」。
# 这里启动时先扫一遍：合法就提升，非法就丢。
python3 - <<'PY'
import glob, json, os
for tmp in glob.glob("reports/calib_json/*.json.tmp"):
    dst = tmp[:-4]
    try:
        ok = json.load(open(tmp, encoding="utf-8")).get("pages_crawled", 0) > 0
    except Exception:
        ok = False
    os.replace(tmp, dst) if ok else os.remove(tmp)
    print(f"  续跑：{'提升' if ok else '丢弃'} {os.path.basename(dst)}")
PY

echo "开始校准抓取（${PAGES} 页/站）$(date +%H:%M:%S)"
while read -r host; do
    case "$host" in \#*|"") continue ;; esac
    out="reports/calib_json/${host//\//_}.json"
    if [ -s "$out" ]; then echo "跳过 $host（已存在）"; continue; fi
    echo "=== $host"
    # ⚠️ 必须在 backend/ 下跑：PYTHONPATH 里的 `.` 指的是 app 包所在目录。
    # 第一版把 cwd 设成仓库根，29 站全 FAIL，报 ModuleNotFoundError: No
    # module named 'app'——而且脚本照常打印「FAIL（超时/被封/非 HTML）」，
    # 跟站点挂了长得一模一样。又一次「不报错、输出好看」的坑。
    ( cd "$ROOT/backend" && PYTHONPATH="$ROOT/.deps:." timeout 300 python3 -m seoclaw.cli scan \
        "https://$host/" --max-pages "$PAGES" --rps 1.5 \
        --no-verify-canonical --json ) > "$out.tmp" 2>>/tmp/calib_err.log

    if python3 -c "
import json,sys
try:
    d=json.load(open('$out.tmp'))
    sys.exit(0 if d.get('pages_crawled',0)>0 else 1)
except Exception: sys.exit(1)
" 2>/dev/null; then
        mv "$out.tmp" "$out"
        n=$(python3 -c "import json;print(len(json.load(open('$out')).get('issues',[])))" 2>/dev/null)
        p=$(python3 -c "import json;print(json.load(open('$out')).get('pages_crawled'))" 2>/dev/null)
        echo "    OK  抓 $p 页  发现 $n 条"
    else
        echo "    FAIL（超时/被封/非 HTML）"; rm -f "$out.tmp"
    fi
done < tools/fp_sites.txt
echo "校准抓取结束 $(date +%H:%M:%S)：$(ls -1 reports/calib_json/*.json 2>/dev/null | wc -l) 站"
