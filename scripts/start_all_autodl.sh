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

echo "Starting UI gateway on :8766..."
nohup bash scripts/start_ui_prototype.sh > logs/ui.log 2>&1 &
sleep 1

echo "== health checks =="
curl -sS "http://127.0.0.1:8000/healthz" | head -c 200
echo
curl -sS "http://127.0.0.1:8766/api/config/public" | head -c 200
echo
echo "Done. Logs: logs/backend.log logs/ui.log"
