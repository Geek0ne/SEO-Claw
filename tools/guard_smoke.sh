#!/usr/bin/env bash
# 真容器验收：四道闸是不是**真的**活着
#
# ⚠️ 为什么要这个脚本，而不是靠单测？
# 单测测的是「函数被调用时返回什么」。这个脚本测的是
# **「一个真跑起来的容器，面对真 HTTP 请求，会不会真的拦」**。
# 路由没挂上、装饰器位置错、依赖没装 —— 这些单测全绿，线上照样裸奔。
#
# 用法：
#   ./tools/guard_smoke.sh              # 自己建镜像 + 起容器 + 测 + 清理
#   KEEP=1 ./tools/guard_smoke.sh       # 测完不删容器，方便手工复现
#
# 退出码 0 = 四道闸全部按预期。1 = 有闸没拦住（**别急着上线**）。

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="seoclaw:guard-smoke"
CONTAINER="seoclaw_guard_smoke"
PORT="${PORT:-8911}"
# ⚠️ 必须是一个**能解析**的域名。
# 我第一版写的是 blocked.example —— .example 是保留 TLD，解析不出来，
# 于是请求在 SSRF 的 DNS 校验那一步就被拒了，返回 400。
# 而 400 也是「被拒」，看起来像黑名单生效了，**实际上压根没走到黑名单**。
# 测没测到目标，和目标真通过，长得一模一样。这个坑写进代码里，别再踩第二次。
DENY_TARGET="example.com"
LOOKALIKE="notexample.com"
SAFE_TARGET="example.org"

BASE="http://127.0.0.1:${PORT}/api/v1/web/quick-scan"
PASS=0
FAIL=0

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok()   { PASS=$((PASS+1)); printf '  ✅ %-34s %s\n' "$1" "$2"; }
bad()  { FAIL=$((FAIL+1)); printf '  ❌ %-34s %s (期望 %s)\n' "$1" "$2" "$3"; }

# 每次换一个 X-Forwarded-For —— 限流按 IP 算，
# 不换 IP 的话限流会把后面所有用例一起干掉，测出来的全是 429。
#
# ⚠️ **必须用文件记计数器，不能用 shell 变量。**
# 我第一版写的是 `ip_seq=$((ip_seq+1)); echo ....$ip_seq`，
# 而调用方式是 `post "$url" "$(next_ip)"` —— 命令替换会开**子 shell**，
# 子 shell 里加的变量出不来，主 shell 的 ip_seq 永远停在 20。
# 于是 11 个用例全部用了同一个 IP，burst=3，第 4 个开始齐刷刷 429。
#
# 限流器拦得完全正确，错的是我把靶子换错了 —— 而这种错误长得很像
# 「限流太激进」或者「黑名单没生效」，能把我带偏一整天。
IPFILE="$(mktemp)"
echo 20 > "$IPFILE"
cleanup() {
  rm -f "$IPFILE"
  if [ "${KEEP:-0}" != "1" ]; then docker rm -f "$CONTAINER" >/dev/null 2>&1 || true; fi
}
next_ip() {
  local n
  n=$(($(cat "$IPFILE") + 1))
  echo "$n" > "$IPFILE"
  echo "198.51.100.$n"
}

# post <url> [xff] -> HTTP 状态码
post() {
  local url="$1" xff="${2:-$(next_ip)}"
  curl -s -m 20 -o /dev/null -w '%{http_code}' \
    -X POST "$BASE" \
    -H 'Content-Type: application/json' \
    -H "X-Forwarded-For: ${xff}" \
    -d "{\"url\": \"${url}\"}"
}

expect() {  # expect <用例名> <实际> <期望>
  if [ "$2" = "$3" ]; then ok "$1" "$2"; else bad "$1" "$2" "$3"; fi
}


# ---------------------------------------------------------------- 建容器
say "1/3  建镜像"
docker build -q -t "$IMAGE" "$REPO" || { echo "构建失败"; exit 1; }

docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
docker run -d --name "$CONTAINER" \
  -p "127.0.0.1:${PORT}:8000" \
  -e "SEO_DENYLIST=${DENY_TARGET}" \
  "$IMAGE" >/dev/null || { echo "起容器失败"; exit 1; }

printf '  等服务就绪'
for _ in $(seq 1 40); do
  if curl -fsS -m 2 "http://127.0.0.1:${PORT}/api/v1/health" >/dev/null 2>&1; then
    printf ' ✅\n'; break
  fi
  printf '.'; sleep 1
done
if ! curl -fsS -m 2 "http://127.0.0.1:${PORT}/api/v1/health" >/dev/null 2>&1; then
  echo; echo "服务 40 秒没起来，先看日志："; docker logs --tail 30 "$CONTAINER"; exit 1
fi

# ---------------------------------------------------------------- 四道闸
say "2/3  闸 1 · SSRF —— 偷 IAM 凭据 / 打内网"
expect "云元数据 169.254.169.254" "$(post 'http://169.254.169.254/latest/meta-data/iam/security-credentials/')" "400"
expect "回环 127.0.0.1:8000"       "$(post 'http://127.0.0.1:8000/api/v1/health')"                 "400"
expect "私有网段 10.0.0.1"          "$(post 'http://10.0.0.1/')"                                    "400"
expect "file:// 本地文件"           "$(post 'file:///etc/passwd')"                                   "400"
expect "Redis 端口"                "$(post 'http://10.0.0.1:6379/')"                               "400"

say "3/3  闸 2 · 黑名单 —— 别拿我当打手"
expect "黑名单本体 ${DENY_TARGET}"        "$(post "https://${DENY_TARGET}/")"       "403"
expect "子域 www.${DENY_TARGET}"          "$(post "https://www.${DENY_TARGET}/")"   "403"
expect "相似域名不该误伤 ${LOOKALIKE}"    "$(post "https://${LOOKALIKE}/")"         "202"
expect "无关域名不该误伤 ${SAFE_TARGET}"  "$(post "https://${SAFE_TARGET}/")"       "202"

say "3/3  闸 3 · 限流 —— 一个人狂刷"
# 同一个 IP 连打 6 次，burst=3 → 第 4 次起必须 429
codes=""
for _ in $(seq 1 6); do codes="$codes $(post 'https://example.org/' '203.0.113.77')"; done
if echo "$codes" | tr ' ' '\n' | grep -q '429'; then
  ok "同一 IP 连打 6 次" "出现 429（$codes）"
else
  bad "同一 IP 连打 6 次" "无 429" "至少一次 429"
fi

say "3/3  闸 4 · 并发 —— 一群人各刷一次"
# 并发上限 2 → 连打 3 次必须撞出 503。
# ⚠️ 这三条必须**几乎同时**发出去，靠的是同一个 IP 连续提交累积占用。
c2=""
for _ in $(seq 1 4); do c2="$c2 $(post 'https://example.org/' '203.0.113.88')"; done
if echo "$c2" | tr ' ' '\n' | grep -q '503\|429'; then
  ok "同一 IP 连打 4 次" "撞出上限（$c2）"
else
  bad "同一 IP 连打 4 次" "无 503/429" "至少一次 503"
fi

# ---------------------------------------------------------------- 收口
say "结果"
printf '  通过 %d / 失败 %d\n\n' "$PASS" "$FAIL"
if [ "$FAIL" -eq 0 ]; then
  echo "  四道闸全部按预期。容器不是被测出来的，是**打**出来的。"
else
  echo "  ⚠️  有闸没拦住。别上线，先查。"
fi
[ "${KEEP:-0}" = "1" ] && echo "  KEEP=1：容器 sc_smoke 还留着，docker logs $CONTAINER"
exit $(( FAIL > 0 ? 1 : 0 ))
