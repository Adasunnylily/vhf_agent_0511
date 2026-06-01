#!/usr/bin/env bash
set -euo pipefail

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
PYTHON_BIN="${PYTHON_BIN:-}"

if [ -z "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3 || command -v python || true)"
fi
if [ -z "$PYTHON_BIN" ] && [ -x "/root/miniconda3/bin/python" ]; then
  PYTHON_BIN="/root/miniconda3/bin/python"
fi
if [ -z "$PYTHON_BIN" ]; then
  echo "Python runtime not found. Set PYTHON_BIN explicitly." >&2
  exit 1
fi

if [ -f ".env" ]; then
  set -a
  . ./.env
  set +a
fi

exec "$PYTHON_BIN" -m uvicorn app.main:app --host "${HOST}" --port "${PORT}"
