#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8000/healthz}"
TIMEOUT_SEC="${2:-120}"

for second in $(seq 1 "$TIMEOUT_SEC"); do
  http_code="$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 1 "$BASE_URL" 2>/dev/null || echo "000")"
  if [ "$http_code" = "200" ]; then
    echo "Backend ready after ${second}s (${BASE_URL})"
    exit 0
  fi
  sleep 1
done

echo "Backend not ready after ${TIMEOUT_SEC}s (${BASE_URL})" >&2
exit 1
