#!/usr/bin/env bash
# 在临时数据库上跑全部测试——不会碰开发库（magiclink.db）。
#
# 用法：./tests/run_all.sh
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${TEST_PORT:-3099}"
TMPDB="$(mktemp -d)/test.db"
LOG="$(mktemp)"
BASE="http://127.0.0.1:${PORT}"

cleanup() {
  [ -n "${SRV_PID:-}" ] && kill "$SRV_PID" 2>/dev/null || true
}
trap cleanup EXIT

echo "· 临时库：$TMPDB"
MAGICLINK_DB="$TMPDB" .venv/bin/python manage.py init >/dev/null

MAGICLINK_DB="$TMPDB" .venv/bin/python -m uvicorn app.main:app \
  --host 127.0.0.1 --port "$PORT" > "$LOG" 2>&1 &
SRV_PID=$!

for _ in $(seq 1 40); do
  curl -sf "${BASE}/api/health" >/dev/null 2>&1 && break
  sleep 0.25
done
curl -sf "${BASE}/api/health" >/dev/null || { echo "服务启动失败："; cat "$LOG"; exit 1; }

rc=0
for t in test_api test_contract test_reorder test_team_perms test_public test_gitcode test_concurrency; do
  echo
  echo "════════════════════════════════════════════"
  echo "  $t"
  echo "════════════════════════════════════════════"
  MAGICLINK_BASE="$BASE" .venv/bin/python "tests/$t.py" || rc=1
done

echo
if [ "$rc" -eq 0 ]; then
  echo "✅ 全部测试通过"
else
  echo "❌ 有测试未通过（服务日志：${LOG}）"
fi
exit "$rc"
