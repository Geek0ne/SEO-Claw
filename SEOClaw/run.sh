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
  # ⚠️ migrate 必须带 -c migrations/alembic.ini：alembic.ini 在 migrations/ 下，
  # 不在 cwd（backend/）。我今天为这个白跑了 4 次（alembic 不在 PATH →
  # python3 -m alembic 说没模块 → 从 backend 跑说没有 script_location）。
  # 踩一次的坑就该写进脚本，不然下个会话还要再摸一遍。
  migrate) shift; exec python3 -m alembic -c migrations/alembic.ini "$@" ;;
  rules)   shift; exec python3 -m seoclaw.cli rules "$@" ;;
  scan)    shift; exec python3 -m seoclaw.cli scan "$@" ;;
  *)       exec "$@" ;;
esac
