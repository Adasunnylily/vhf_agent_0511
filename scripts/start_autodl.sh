#!/usr/bin/env bash
set -euo pipefail

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

if [ -f ".env" ]; then
  set -a
  . ./.env
  set +a
fi

exec uvicorn app.main:app --host "${HOST}" --port "${PORT}"
