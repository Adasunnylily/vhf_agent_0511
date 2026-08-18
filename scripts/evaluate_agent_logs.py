#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.agent_metrics import calculate_agent_metrics


def main() -> int:
    parser = argparse.ArgumentParser(description="计算智能体感知、认知、执行、记忆、学习五维指标")
    parser.add_argument("--input", type=Path, default=ROOT / "data" / "agent_run_logs.jsonl")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    records = []
    if args.input.exists():
        for line in args.input.read_text(encoding="utf-8").splitlines():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    result = calculate_agent_metrics(records)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
