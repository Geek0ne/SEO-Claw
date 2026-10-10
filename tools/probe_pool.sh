#!/usr/bin/env bash
# 候选池可达性预检 —— 并行版
#
# 为什么必须先预检（第三次踩同一个坑）：
#   v1：站点表里混进 shell 脚本 → 24 站「1 页 1 条 100.0 分」，一格没报错
#   v2：手挑 47 个头部流量站 → 预检 3 个 000 + 1 个 403（Cloudflare 人机校验）
#   抓取脚本对「连不通」和「站点没做 SEO」的处理是一样的：都写出一份
#   1 页 1 条的报告。分不清这两种，测出来的准确率就是自欺欺人。
#
# 输出两栏：可达清单（进抓取）与不可达清单（写进报告的排除说明，不进分母）
set -u
ROOT=/root/.openclaw/workspace/SEO-Claw
POOL="$ROOT/tools/fp_pool.txt"
OUT_OK=/tmp/pool_ok.txt
OUT_NO=/tmp/pool_fail.txt
: > "$OUT_OK"; : > "$OUT_NO"

probe_one() {
    h="$1"
    f="/tmp/probe_html_$$_${h}.html"
    # 跟随重定向、15s 超时、带常规浏览器 UA（抓取器的 Python-httpx UA
    # 会被部分站点直接拒，这个已知问题在 v2 预检里表现为成片 000）
    read -r code t < <(curl -sL -o "$f" -w '%{http_code} %{time_total}' \
        --max-time 15 \
        -A 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36' \
        "https://$h/" 2>/dev/null || echo "000 15.0")
    sz=$(wc -c < "$f" 2>/dev/null | tr -d ' ')
    rm -f "$f"
    case "$code" in
        200|301|302) echo "OK $h $code $sz" >> "$OUT_OK" ;;
        *)           echo "NO $h $code $sz" >> "$OUT_NO" ;;
    esac
}
export -f probe_one
export OUT_OK OUT_NO

grep -v '^#' "$POOL" | grep -v '^[[:space:]]*$' | sed 's/[[:space:]]*$//' | sort -u \
  | xargs -P 12 -I{} bash -c 'probe_one "$@"' _ {}

echo "可达 $(wc -l < "$OUT_OK") / 不可达 $(wc -l < "$OUT_NO") / 共 $(( $(wc -l < "$OUT_OK") + $(wc -l < "$OUT_NO") ))"
echo "--- 不可达明细（按状态码分布）---"
awk '{print $3}' "$OUT_NO" | sort | uniq -c | sort -rn
echo "--- 可达里字节数偏小的（可能是 JS 壳或落地页，抓取价值低）---"
awk '$4 < 20000 {print $2, $4"B"}' "$OUT_OK" | head -20
