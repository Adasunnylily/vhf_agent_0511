from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Any, Dict, Iterable, List, Optional


CAPABILITY_NAMES = {
    "perception": "感知",
    "cognition": "认知",
    "execution": "执行",
    "memory": "记忆",
    "learning": "学习",
}


def _round(value: Optional[float]) -> Optional[float]:
    return round(value, 4) if value is not None else None


def _percentile(values: List[float], percentile: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return ordered[index]


def calculate_agent_metrics(records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    rows = list(records)
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("capability") or "")].append(row)

    dimensions: Dict[str, Dict[str, Any]] = {}
    dimension_scores: List[float] = []
    for capability, name in CAPABILITY_NAMES.items():
        items = grouped.get(capability, [])
        completed = [item for item in items if item.get("status") in {"success", "failed"}]
        successes = [item for item in completed if item.get("status") == "success"]
        latencies = [float(item["latency_ms"]) for item in items if isinstance(item.get("latency_ms"), (int, float))]
        confidences = [float(item["confidence"]) for item in items if isinstance(item.get("confidence"), (int, float))]
        expected = [item for item in items if isinstance(item.get("metadata"), dict) and "expected" in item["metadata"]]
        correct = [item for item in expected if item["metadata"].get("expected") == item["metadata"].get("actual")]
        success_rate = len(successes) / len(completed) if completed else None
        accuracy = len(correct) / len(expected) if expected else None
        score = accuracy if accuracy is not None else success_rate
        if score is not None:
            dimension_scores.append(score)
        dimensions[capability] = {
            "name": name,
            "record_count": len(items),
            "coverage": bool(items),
            "success_rate": _round(success_rate),
            "label_accuracy": _round(accuracy),
            "average_confidence": _round(mean(confidences) if confidences else None),
            "average_latency_ms": _round(mean(latencies) if latencies else None),
            "p50_latency_ms": _round(_percentile(latencies, 0.50)),
            "p95_latency_ms": _round(_percentile(latencies, 0.95)),
            "score": _round(score),
        }

    traced_events = {str(row.get("event_id")) for row in rows if row.get("event_id")}
    return {
        "schema_version": "1.0",
        "record_count": len(rows),
        "run_count": len({str(row.get("run_id")) for row in rows if row.get("run_id")}),
        "event_count": len(traced_events),
        "dimension_coverage": sum(1 for value in dimensions.values() if value["coverage"]),
        "overall_score": _round(mean(dimension_scores) if dimension_scores else None),
        "dimensions": dimensions,
        "notes": "缺失数据保持为空，不使用模拟分数填充。overall_score仅汇总有有效样本的维度。",
    }
