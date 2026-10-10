#!/usr/bin/env bash
# 等批次抓取结束后，自动跑独立核对器并把结果落盘。
# 用途：别再用「状态查询刷屏」换进度——让结果自己到齐。
set -u
cd /root/.openclaw/workspace/SEO-Claw || exit 1

# 等批次结束（最多等 25 分钟）
for _ in $(seq 1 150); do
    pgrep -f run_fp_batch >/dev/null || break
    sleep 10
done

n=$(ls -1 reports/fp_json/*.json 2>/dev/null | wc -l)
echo "抓取完成：$n 站" > /tmp/final_report.txt
if [ "$n" -lt 20 ]; then
    echo "⚠️ 不足 20 站，结论仅供参考" >> /tmp/final_report.txt
fi

python3 tools/verify_findings.py "reports/fp_json/*.json" \
    > /tmp/final_verify.txt 2>/tmp/final_verify.err

{
    echo "=== 独立回源核对（修复后）==="
    cat /tmp/final_verify.txt
} >> /tmp/final_report.txt

echo "done" > /tmp/final_report.ready
