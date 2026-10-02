#!/usr/bin/env bash
# 真重抓：上一轮所谓「v3 重抓」其实没跑。
#
# 根因：run_fp_batch.sh 里有 `[ -s "$OUT/$name.json" ] && { ok=..; continue; }`
# —— 见到已有文件就跳过。而 reports/fp_json/ 里 19 个文件的时间戳是
# 09-29 20:19~20:31，而 extract.py 的修复是 09-30 00:41。
# 也就是说：批次一路报「完成 19 站」，实际一站新数据都没抓。
#
# 这个坑的性质很恶劣：**它不报错，输出还很好看**（"完成：成功 19 站"），
# 我差点拿一个「什么都没重做」的结果当修复后数据汇报给你。
set -u
cd /root/.openclaw/workspace/SEOClaw || exit 1

pkill -f run_fp_batch 2>/dev/null
pkill -f finalize_fp 2>/dev/null
pkill -f verify_findings 2>/dev/null
sleep 2

# 归档旧数据，绝不原地覆盖——留证据以便对比
[ -d reports/fp_json ] && rm -rf reports/fp_json_prev && mv reports/fp_json reports/fp_json_prev
mkdir -p reports/fp_json

echo "清空完成，$(date +%H:%M:%S) 开始真重抓"
bash tools/run_fp_batch.sh > /tmp/fp_true.log 2>&1
echo "抓取结束 $(date +%H:%M:%S)：$(ls -1 reports/fp_json/*.json 2>/dev/null | wc -l) 站" >> /tmp/fp_true.log
echo done > /tmp/fp_true.done
