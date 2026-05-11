from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List


def normalize_text(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[\s,，.。:：;；!?！？、\"'“”‘’（）()\[\]【】{}<>《》\-_/\\|~`^]+", "", text)
    return text


def edit_distance(a: str, b: str) -> int:
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def similarity(a: str, b: str) -> float:
    a = normalize_text(a)
    b = normalize_text(b)
    longest = max(len(a), len(b))
    if longest == 0:
        return 1.0
    return max(0.0, 1.0 - edit_distance(a, b) / longest)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a human review queue from multiple ASR detail CSV outputs.")
    parser.add_argument("--details", nargs="+", required=True, type=Path, help="*_details.csv files from ASR runs")
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def read_detail(path: Path) -> Dict[str, Dict[str, str]]:
    model_name = path.name.replace("_details.csv", "")
    rows = {}
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            key = row.get("id") or row.get("audio_path")
            if not key:
                continue
            rows[key] = {
                "model": model_name,
                "audio_path": row.get("audio_path", ""),
                "prediction": row.get("prediction", ""),
            }
    return rows


def main() -> None:
    args = parse_args()
    grouped: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for detail_path in args.details:
        for key, item in read_detail(detail_path).items():
            grouped[key].append(item)

    review_rows = []
    for key, items in grouped.items():
        predictions = [item["prediction"] for item in items]
        pairs = [
            similarity(predictions[i], predictions[j])
            for i in range(len(predictions))
            for j in range(i + 1, len(predictions))
        ]
        agreement = sum(pairs) / len(pairs) if pairs else 1.0
        longest_prediction = max(predictions, key=len) if predictions else ""
        row = {
            "id": key,
            "audio_path": items[0].get("audio_path", ""),
            "agreement": f"{agreement:.6f}",
            "suggested_reference": longest_prediction,
            "human_reference": "",
            "review_priority": "high" if agreement < 0.75 else "medium" if agreement < 0.9 else "low",
        }
        for item in items:
            row[f"prediction__{item['model']}"] = item["prediction"]
        review_rows.append(row)

    review_rows.sort(key=lambda row: float(row["agreement"]))
    fieldnames = []
    for row in review_rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(review_rows)
    print(f"wrote {len(review_rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
