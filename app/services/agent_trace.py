from __future__ import annotations

import csv
import io
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


CAPABILITIES = {"perception", "cognition", "execution", "memory", "learning"}
STATUSES = {"started", "success", "failed", "skipped"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentTraceStore:
    """Append-only JSONL audit trail for automated agent evaluation."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def append(self, record: Dict[str, Any]) -> Dict[str, Any]:
        normalized = self._normalize(record)
        line = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        return normalized

    def extend(self, records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [self.append(record) for record in records]

    def list(
        self,
        *,
        run_id: str = "",
        event_id: str = "",
        capability: str = "",
        stage: str = "",
        status: str = "",
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: List[Dict[str, Any]] = []
        with self._lock:
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        row = json.loads(line)
                    except (TypeError, json.JSONDecodeError):
                        continue
                    if run_id and row.get("run_id") != run_id:
                        continue
                    if event_id and row.get("event_id") != event_id:
                        continue
                    if capability and row.get("capability") != capability:
                        continue
                    if stage and row.get("stage") != stage:
                        continue
                    if status and row.get("status") != status:
                        continue
                    rows.append(row)
        return rows[-max(1, min(int(limit), 100000)) :]

    def export(self, rows: List[Dict[str, Any]], format_name: str) -> tuple[str, str]:
        if format_name == "json":
            return json.dumps(rows, ensure_ascii=False, indent=2), "application/json"
        if format_name == "csv":
            fields = [
                "schema_version", "log_id", "run_id", "event_id", "timestamp",
                "capability", "stage", "status", "source", "confidence",
                "latency_ms", "model", "prompt_version", "rule_version",
                "tool_name", "action", "error", "output", "evidence", "metadata",
            ]
            buffer = io.StringIO()
            writer = csv.DictWriter(buffer, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({
                    key: json.dumps(row.get(key), ensure_ascii=False)
                    if isinstance(row.get(key), (dict, list)) else row.get(key, "")
                    for key in fields
                })
            return buffer.getvalue(), "text/csv; charset=utf-8"
        return "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""), "application/x-ndjson"

    @staticmethod
    def _normalize(record: Dict[str, Any]) -> Dict[str, Any]:
        row = dict(record)
        capability = str(row.get("capability") or "").strip().lower()
        status = str(row.get("status") or "success").strip().lower()
        if capability not in CAPABILITIES:
            raise ValueError(f"unsupported capability: {capability}")
        if status not in STATUSES:
            raise ValueError(f"unsupported status: {status}")
        stage = str(row.get("stage") or "").strip()
        if not stage:
            raise ValueError("stage is required")
        return {
            "schema_version": "1.0",
            "log_id": str(row.get("log_id") or f"log_{uuid.uuid4().hex}"),
            "run_id": str(row.get("run_id") or row.get("task_id") or "default"),
            "event_id": str(row.get("event_id") or ""),
            "timestamp": str(row.get("timestamp") or utc_now_iso()),
            "capability": capability,
            "stage": stage,
            "status": status,
            "source": str(row.get("source") or "backend"),
            "confidence": row.get("confidence"),
            "latency_ms": row.get("latency_ms"),
            "model": str(row.get("model") or ""),
            "model_version": str(row.get("model_version") or ""),
            "prompt_version": str(row.get("prompt_version") or ""),
            "rule_version": str(row.get("rule_version") or ""),
            "dictionary_version": str(row.get("dictionary_version") or ""),
            "tool_name": str(row.get("tool_name") or ""),
            "action": str(row.get("action") or ""),
            "input_ref": str(row.get("input_ref") or ""),
            "output": row.get("output") if isinstance(row.get("output"), dict) else {},
            "evidence": row.get("evidence") if isinstance(row.get("evidence"), list) else [],
            "error": str(row.get("error") or ""),
            "metadata": row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
        }
