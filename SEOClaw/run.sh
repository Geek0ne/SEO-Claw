#!/usr/bin/env bash
# SEOClaw 本机运行入口
#
# 为什么有 PYTHONPATH：这台机器的系统 Python 是 PEP 668 托管的，且
# python3 -m venv 建不出带 pip 的环境（缺 ensurepip）。依赖是用
# `pip install --target ./.deps` 装到项目目录的，所以每次调用都要带前缀。
# 写成脚本就是为了下个会话不用重新摸一遍。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$ROOT/.deps:$ROOT/backend"
cd "$ROOT/backend"
case "${1:-}" in
  test|"") shift || true; exec python3 -m pytest tests/ -q "$@" ;;
  rules)   shift; exec python3 -m seoclaw.cli rules "$@" ;;
  scan)    shift; exec python3 -m seoclaw.cli scan "$@" ;;
  *)       exec "$@" ;;
esac
