#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p logs

echo "Stopping old backend/UI..."
pkill -f "uvicorn app.main:app" 2>/dev/null || true
pkill -f "ui_prototype/server.py" 2>/dev/null || true
sleep 1

echo "Starting backend on :8000..."
nohup bash scripts/start_autodl.sh > logs/backend.log 2>&1 &
bash scripts/wait_for_backend.sh "http://127.0.0.1:8000/healthz" 120

UI_PORT="${VHF_UI_PORT:-8766}"
UI_ALIAS_PORT="${VHF_UI_ALIAS_PORT:-18766}"

echo "Starting UI gateway on :${UI_PORT}..."
nohup env VHF_UI_PORT="${UI_PORT}" bash scripts/start_ui_prototype.sh > logs/ui.log 2>&1 &
sleep 1

if [ "${UI_ALIAS_PORT}" != "${UI_PORT}" ]; then
  echo "Starting UI gateway alias on :${UI_ALIAS_PORT}..."
  nohup env VHF_UI_PORT="${UI_ALIAS_PORT}" bash scripts/start_ui_prototype.sh > logs/ui_alias.log 2>&1 &
  sleep 1
fi

echo "== health checks =="
curl -sS "http://127.0.0.1:8000/healthz" | head -c 200
echo
curl -sS "http://127.0.0.1:${UI_PORT}/api/config/public" | head -c 200
echo
if [ "${UI_ALIAS_PORT}" != "${UI_PORT}" ]; then
  curl -sS -o /dev/null -w "UI alias :${UI_ALIAS_PORT} -> %{http_code}\n" "http://127.0.0.1:${UI_ALIAS_PORT}/maritime_ai_agent.html"
fi
echo "Done. Logs: logs/backend.log logs/ui.log logs/ui_alias.log"
