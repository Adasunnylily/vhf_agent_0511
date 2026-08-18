import json
import tempfile
import unittest
from pathlib import Path

from app.services.agent_metrics import calculate_agent_metrics
from app.services.agent_trace import AgentTraceStore


class AgentTraceTests(unittest.TestCase):
    def test_jsonl_store_normalizes_filters_and_exports(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = AgentTraceStore(Path(tmpdir) / "agent.jsonl")
            stored = store.append(
                {
                    "run_id": "run-1",
                    "event_id": "event-1",
                    "capability": "perception",
                    "stage": "asr_completed",
                    "status": "success",
                    "latency_ms": 320,
                    "confidence": 0.91,
                    "output": {"text": "宁波交管"},
                }
            )

            self.assertEqual(stored["schema_version"], "1.0")
            self.assertEqual(len(store.list(event_id="event-1")), 1)
            self.assertEqual(store.list(capability="execution"), [])
            content, media_type = store.export(store.list(), "jsonl")
            self.assertEqual(media_type, "application/x-ndjson")
            self.assertEqual(json.loads(content)["event_id"], "event-1")

    def test_invalid_capability_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = AgentTraceStore(Path(tmpdir) / "agent.jsonl")
            with self.assertRaises(ValueError):
                store.append({"capability": "unknown", "stage": "bad"})

    def test_five_dimension_metrics_do_not_invent_missing_scores(self) -> None:
        records = [
            {
                "run_id": "run-1",
                "event_id": "event-1",
                "capability": "perception",
                "stage": "asr_completed",
                "status": "success",
                "latency_ms": 400,
                "confidence": 0.9,
                "metadata": {"expected": "报告", "actual": "报告"},
            },
            {
                "run_id": "run-1",
                "event_id": "event-1",
                "capability": "execution",
                "stage": "action_completed",
                "status": "failed",
                "latency_ms": 100,
            },
        ]

        result = calculate_agent_metrics(records)

        self.assertEqual(result["dimension_coverage"], 2)
        self.assertEqual(result["dimensions"]["perception"]["label_accuracy"], 1.0)
        self.assertEqual(result["dimensions"]["execution"]["success_rate"], 0.0)
        self.assertIsNone(result["dimensions"]["learning"]["score"])


if __name__ == "__main__":
    unittest.main()
