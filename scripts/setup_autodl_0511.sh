#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"

"${PYTHON_BIN}" -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
python -m pip install -r requirements-server.txt

if [ ! -f ".env" ]; then
  cp .env.0511.example .env
fi

mkdir -p outputs/asr_eval_0511

echo "0511 environment is ready."
echo "Edit .env if needed, then run: bash scripts/start_autodl.sh"
