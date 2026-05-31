#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-/Users/adasunnylily/Documents/New project/vhf-agent-0511}"
BRANCH="${BRANCH:-rollback-0521-1620}"
REMOTE="${REMOTE:-origin}"

SERVER_HOST="${SERVER_HOST:-connect.nmb2.seetacloud.com}"
SERVER_PORT="${SERVER_PORT:-32375}"
SERVER_USER="${SERVER_USER:-root}"
SERVER_REPO_DIR="${SERVER_REPO_DIR:-/root/autodl-tmp/original/autodl-tmp/vhf_agent_0511}"
SERVER_START_SCRIPT="${SERVER_START_SCRIPT:-scripts/start_autodl.sh}"

COMMIT_MSG="${1:-chore: sync latest local changes}"

echo "[1/5] Local repo: $REPO_DIR"
cd "$REPO_DIR"

echo "[2/5] Stage + commit (if needed)"
git add app/api.py app/main.py app/services/demo_inspection.py app/services/event_repository.py app/services/knowledge_repository.py ui_prototype || true
if ! git diff --cached --quiet; then
  git commit -m "$COMMIT_MSG"
else
  echo "No staged changes to commit."
fi

echo "[3/5] Push branch: $BRANCH"
git push -u "$REMOTE" "$BRANCH"

echo "[4/5] SSH pull + restart"
ssh -p "$SERVER_PORT" "$SERVER_USER@$SERVER_HOST" "
set -e
cd '$SERVER_REPO_DIR'
git fetch --all
git checkout '$BRANCH'
git pull --ff-only '$REMOTE' '$BRANCH'
pkill -f 'uvicorn app.main:app' || true
nohup bash '$SERVER_START_SCRIPT' > /tmp/vhf_agent_start.log 2>&1 &
sleep 2
echo 'Server restart command sent.'
"

echo "[5/5] Done. Next: run server smoke checks."
echo "ssh -p $SERVER_PORT $SERVER_USER@$SERVER_HOST \"cd $SERVER_REPO_DIR && bash scripts/server_smoke_check.sh\""
