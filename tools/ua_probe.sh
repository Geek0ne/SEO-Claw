#!/usr/bin/env bash
# UA 对照实验：只变 UA，host 与跟随重定向都固定。
# 动机：gymshark.com 健康分 0.0，五条 code 的 r 全部 ≈1.0，同时命中五项
# 不像站点真差，像是抓取整体失败。需要区分「UA 被挡」还是「域名/重定向问题」。
#
# ⚠️ 前三版实验全部作废，教训写在这里：
#   1) UA 在命令行内联时被转义，$ua 取空 → 等于用空 UA 请求，403/301/200 混着出
#   2) 同时变了 UA 和 host（gymshark.com vs www.）→ 混淆实验，结论下早了
#   3) 一次只跑单 host，被超时 kill
# 这次：UA 用单引号字面量写在脚本内、host 与 -L 固定、每格独立超时。
BOT='Mozilla/5.0 (compatible; SEOAgentBot/0.1; +https://example.com/bot) Python-httpx'
BROWSER='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

for spec in "gymshark.com|$BOT|bot" \
            "gymshark.com|$BROWSER|browser" \
            "www.gymshark.com|$BOT|bot" \
            "www.gymshark.com|$BROWSER|browser"; do
    host=${spec%%|*}
    rest=${spec#*|}
    ua=${rest%|*}
    lbl=${rest##*|}
    out="/tmp/uaprobe_${host}_${lbl}.html"
    code=$(timeout 20 curl -sL -o "$out" -w '%{http_code}' -A "$ua" "https://$host/" 2>/dev/null)
    sz=$(wc -c < "$out" 2>/dev/null | tr -d ' ')
    t=$(grep -o -m1 '<title[^>]*>[^<]*' "$out" 2>/dev/null | sed 's/<[^>]*>//' | head -c 44)
    printf '%-20s %-8s code=%-4s bytes=%-9s title=%s\n' "$host" "$lbl" "$code" "$sz" "${t:-NONE}"
done
echo "--- 结论判读 ---"
echo "若 bot 与 browser 的 title 都 NONE → 域名/重定向问题，与 UA 无关"
echo "若 browser 有 title 而 bot NONE     → UA 被识别挡了"
