#!/usr/bin/env bash
# MagicLink 本地开发启动脚本
#
# 抓取链接标题/图标需要出网。默认直连（httpx trust_env=False），因为 macOS 的
# 「系统代理设置」常指向没启动的 Clash，会让抓取以一个看不懂的 SSL 错误失败。
# 确实需要走代理时，显式指定：
#   MAGICLINK_PROXY=http://127.0.0.1:7890 ./run.sh
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-3030}"
HOST="${HOST:-127.0.0.1}"

if [ ! -d .venv ]; then
  echo "缺少虚拟环境，请先执行："
  echo "  uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt"
  echo "（没有 uv 就用 python3 -m venv .venv，再 .venv/bin/python -m pip install -r requirements.txt）"
  exit 1
fi

if [ -n "${MAGICLINK_PROXY:-}" ]; then
  echo "· 抓取走代理：${MAGICLINK_PROXY}"
else
  echo "· 抓取直连（如需代理：MAGICLINK_PROXY=http://127.0.0.1:7890 PORT=$PORT ./run.sh）"
fi

exec .venv/bin/python -m uvicorn app.main:app --host "$HOST" --port "$PORT" --reload
