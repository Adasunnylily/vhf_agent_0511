#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"

echo "== healthz =="
curl -sS "$BASE_URL/healthz" | sed 's/^/  /'
echo

echo "== events =="
curl -sS "$BASE_URL/api/events" | sed 's/^/  /'
echo

echo "== analytics summary =="
curl -sS "$BASE_URL/api/analytics/summary" | sed 's/^/  /'
echo

echo "== inspection areas =="
curl -sS "$BASE_URL/api/inspection/areas" | sed 's/^/  /'
echo

echo "== knowledge search (VTS) =="
curl -sS "$BASE_URL/api/knowledge/search?q=VTS" | sed 's/^/  /'
echo

echo "Smoke checks completed."
