from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Iterable, List


def parse_float(value: str) -> float | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def quantile(values: List[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
    return ordered[index]


def count_filled(rows: Iterable[dict], field: str) -> int:
    return sum(1 for row in rows if (row.get(field) or "").strip())


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize ASR prelabel / human annotation CSV progress.")
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    with args.csv.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    total = len(rows)
    label_counter = Counter((row.get("primary_label_gt") or "unlabeled").strip() or "unlabeled" for row in rows)
    auto_label_counter = Counter((row.get("primary_label_auto") or "unknown").strip() or "unknown" for row in rows)
    quality_counter = Counter((row.get("audio_quality_gt") or "unlabeled").strip() or "unlabeled" for row in rows)
    comm_counter = Counter((row.get("comm_type_gt") or "unlabeled").strip() or "unlabeled" for row in rows)
    priorities = Counter((row.get("review_priority") or "unmarked").strip() or "unmarked" for row in rows)

    ttft = [value for value in (parse_float(row.get("stream_ttft_ms", "")) for row in rows) if value is not None]
    final_latency = [
        value for value in (parse_float(row.get("stream_final_latency_ms", "")) for row in rows) if value is not None
    ]

    summary = {
        "csv": str(args.csv),
        "total_rows": total,
        "human_labeled_rows": count_filled(rows, "primary_label_gt"),
        "transcript_gt_rows": count_filled(rows, "transcript_gt"),
        "ship_entity_rows": count_filled(rows, "ship_entities_gt"),
        "location_entity_rows": count_filled(rows, "location_entities_gt"),
        "label_distribution_gt": dict(label_counter),
        "label_distribution_auto": dict(auto_label_counter),
        "communication_type_distribution": dict(comm_counter),
        "audio_quality_distribution": dict(quality_counter),
        "review_priority_distribution": dict(priorities),
        "stream_perf_rows": len(ttft),
        "stream_ttft_ms_median": median(ttft) if ttft else None,
        "stream_ttft_ms_p90": quantile(ttft, 0.9),
        "stream_final_latency_ms_median": median(final_latency) if final_latency else None,
        "stream_final_latency_ms_p90": quantile(final_latency, 0.9),
    }

    text = json.dumps(summary, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
