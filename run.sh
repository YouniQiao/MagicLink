#!/usr/bin/env bash
# MagicLink 本地开发启动脚本
#
# 用法：
#   ./run.sh                        # 默认 http://127.0.0.1:3030
#   ./run.sh 8080                   # 换端口
#   ./run.sh --port 8080            # 同上，写全一点
#   ./run.sh 8080 --host 0.0.0.0    # 想给同网段的手机看时（注意别在公网机器上这么开）
#   PORT=8080 ./run.sh              # 环境变量也行
#
# 取值的优先级：命令行 > 环境变量 > 默认（3030 / 127.0.0.1）。
#
# 抓取链接标题/图标需要出网。默认直连（httpx trust_env=False），因为 macOS 的
# 「系统代理设置」常指向没启动的 Clash，会让抓取以一个看不懂的 SSL 错误失败。
# 确实需要走代理时，显式指定：
#   MAGICLINK_PROXY=http://127.0.0.1:7890 ./run.sh
set -euo pipefail
cd "$(dirname "$0")"

usage() {
  cat <<'EOF'
用法: ./run.sh [端口] [选项]

  ./run.sh 8080                    换端口（位置参数最省事）
  -p, --port <端口>                 同上，写全一点
      --host <地址>                 默认 127.0.0.1；想给同网段的手机看用 0.0.0.0
  -h, --help                        这份说明

命令行没给的话看环境变量，再没有才用默认 3030：
  PORT=8080 ./run.sh
  PORT=8080 HOST=0.0.0.0 ./run.sh
EOF
}

# 参数解析。不认识的参数一律**报错退出**，不能默默忽略 ——
# 以前 ./run.sh 8080 会被无视、照旧在 3030 上起（而 3030 若被占着，
# 得到的是一个跟端口毫不相干的报错，很难看出问题在哪）。
PORT="${PORT:-3030}"
HOST="${HOST:-127.0.0.1}"
POSITIONAL=0

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help)
      usage; exit 0 ;;
    -p|--port)
      [ $# -ge 2 ] || { echo "错误：$1 后面要跟一个端口号（./run.sh --help）" >&2; exit 2; }
      PORT="$2"; shift 2 ;;
    --host)
      [ $# -ge 2 ] || { echo "错误：--host 后面要跟一个地址（./run.sh --help）" >&2; exit 2; }
      HOST="$2"; shift 2 ;;
    --port=*)
      PORT="${1#*=}"; shift ;;
    --host=*)
      HOST="${1#*=}"; shift ;;
    -*)
      echo "错误：不认识的选项「$1」（./run.sh --help 看用法）" >&2; exit 2 ;;
    *)
      if [ "$POSITIONAL" -ge 1 ]; then
        echo "错误：多余的参数「$1」——端口只能给一个（./run.sh --help 看用法）" >&2; exit 2
      fi
      PORT="$1"; POSITIONAL=1; shift ;;
  esac
done

case "$PORT" in
  ''|*[!0-9]*)
    echo "错误：端口得是数字，收到的是「${PORT}」" >&2; exit 2 ;;
esac
if [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
  echo "错误：端口要在 1–65535 之间，收到的是 $PORT" >&2; exit 2
fi
if [ -z "$HOST" ]; then
  echo "错误：--host 不能是空的" >&2; exit 2
fi

if [ ! -d .venv ]; then
  echo "缺少虚拟环境，请先执行："
  echo "  uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt"
  echo "（没有 uv 就用 python3 -m venv .venv，再 .venv/bin/python -m pip install -r requirements.txt）"
  exit 1
fi

# 端口被占时别让 uvicorn 自己报一段看不懂的栈 —— 先说清楚，再给出下一步。
if command -v lsof >/dev/null 2>&1; then
  BUSY="$(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null | head -1 || true)"
  if [ -n "$BUSY" ]; then
    echo "端口 $PORT 已被占用（PID ${BUSY}）。换个端口，或先停掉它：" >&2
    echo "  ./run.sh $((PORT + 1))" >&2
    echo "  kill $BUSY" >&2
    exit 1
  fi
fi

# IPv6 地址在 URL 里必须加方括号（http://[::1]:3030），否则那行提示是坏的、没法直接点
HOST_IN_URL="$HOST"
case "$HOST" in
  *:*) HOST_IN_URL="[${HOST}]" ;;
esac

echo "· 服务地址：http://${HOST_IN_URL}:${PORT}"
if [ "$HOST" = "0.0.0.0" ]; then
  echo "  （绑在所有网卡上，同网段的其他设备可以用本机 IP 访问）"
fi
if [ -n "${MAGICLINK_PROXY:-}" ]; then
  echo "· 抓取走代理：${MAGICLINK_PROXY}"
else
  echo "· 抓取直连（如需代理：MAGICLINK_PROXY=http://127.0.0.1:7890 ./run.sh ${PORT}）"
fi

exec .venv/bin/python -m uvicorn app.main:app --host "$HOST" --port "$PORT" --reload
