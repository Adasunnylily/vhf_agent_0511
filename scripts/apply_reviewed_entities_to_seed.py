from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Dict, List


def read_json(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {"ships": [], "locations": [], "manual_aliases": {"ships": [], "locations": []}}
    return json.loads(path.read_text(encoding="utf-8"))


def should_accept(row: Dict[str, str], min_score: int) -> bool:
    accept_gt = (row.get("accept_gt") or "").strip().lower()
    if accept_gt in {"1", "yes", "y", "true", "accept", "通过", "是"}:
        return True
    if accept_gt in {"0", "no", "n", "false", "reject", "拒绝", "否"}:
        return False
    if (row.get("suggested_action") or "").strip() != "accept":
        return False
    try:
        return int(float(row.get("score") or 0)) >= min_score
    except ValueError:
        return False


def add_unique(items: List[object], value: str) -> bool:
    value = value.strip()
    if not value:
        return False
    existing = {str(item).strip() for item in items}
    if value in existing:
        return False
    items.append(value)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply reviewed entity candidates into seed JSON.")
    parser.add_argument("--review-csv", required=True, type=Path)
    parser.add_argument("--seed", type=Path, default=Path("data/bootstrap/nbzh_seed_entities.json"))
    parser.add_argument("--out", type=Path, default=Path("data/bootstrap/nbzh_seed_entities.json"))
    parser.add_argument("--min-score", type=int, default=80)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    seed = read_json(args.seed)
    seed.setdefault("ships", [])
    seed.setdefault("locations", [])
    seed.setdefault("manual_aliases", {"ships": [], "locations": []})

    added = {"ships": 0, "locations": 0}
    with args.review_csv.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if not should_accept(row, args.min_score):
                continue
            entity_type = (row.get("entity_type") or "").strip()
            canonical = (row.get("canonical_gt") or row.get("candidate") or "").strip()
            if entity_type == "ship":
                if add_unique(seed["ships"], canonical):  # type: ignore[arg-type]
                    added["ships"] += 1
            elif entity_type == "location":
                if add_unique(seed["locations"], canonical):  # type: ignore[arg-type]
                    added["locations"] += 1

    print(f"[summary] would add ships={added['ships']} locations={added['locations']}")
    if args.dry_run:
        return

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(seed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[ok] wrote: {args.out}")


if __name__ == "__main__":
    main()
