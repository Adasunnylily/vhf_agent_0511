from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteEventRepository:
    """List-like SQLite store so existing pipelines keep their append/extend API."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    business_type TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    review_status TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at DESC)"
            )

    def append(self, event: Dict[str, object]) -> None:
        self.extend([event])

    def extend(self, events: Iterable[Dict[str, object]]) -> None:
        with self._lock, self._connect() as connection:
            for raw_event in events:
                event = self._normalize(dict(raw_event))
                connection.execute(
                    """
                    INSERT INTO events (
                        event_id, created_at, source_type, risk_level,
                        business_type, action_type, review_status, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(event_id) DO UPDATE SET
                        created_at=excluded.created_at,
                        source_type=excluded.source_type,
                        risk_level=excluded.risk_level,
                        business_type=excluded.business_type,
                        action_type=excluded.action_type,
                        review_status=excluded.review_status,
                        payload_json=excluded.payload_json
                    """,
                    (
                        event["event_id"],
                        event["created_at"],
                        event["source_type"],
                        event["risk_level"],
                        event["business_type"],
                        event["action_type"],
                        event["review_status"],
                        json.dumps(event, ensure_ascii=False),
                    ),
                )

    def list(self, limit: Optional[int] = None) -> List[Dict[str, object]]:
        query = "SELECT payload_json FROM events ORDER BY created_at DESC"
        params: tuple[object, ...] = ()
        if limit is not None:
            query += " LIMIT ?"
            params = (int(limit),)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def get(self, event_id: str) -> Optional[Dict[str, object]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def update_review_status(self, event_id: str, review_status: str) -> Optional[Dict[str, object]]:
        event = self.get(event_id)
        if not event:
            return None
        event["review_status"] = review_status
        self.append(event)
        return event

    def __iter__(self) -> Iterator[Dict[str, object]]:
        return iter(self.list())

    def __reversed__(self) -> Iterator[Dict[str, object]]:
        return iter(self.list())

    def __len__(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM events").fetchone()
        return int(row["count"]) if row else 0

    def _normalize(self, event: Dict[str, object]) -> Dict[str, object]:
        event_id = str(event.get("event_id") or event.get("id") or f"evt_{uuid.uuid4().hex[:12]}")
        event["event_id"] = event_id
        event["id"] = event_id
        event.setdefault("created_at", utc_now_iso())
        event.setdefault("source_type", "unknown")
        event.setdefault("risk_level", "INFO")
        event.setdefault("business_type", self._business_type(event))
        event.setdefault("action_type", "manual_review")
        event.setdefault("review_status", "pending")
        event.setdefault("evidence", [])
        event.setdefault("suggestion", "")
        event.setdefault("broadcast_text", "")
        event.setdefault("ais_context", {})
        return event

    @staticmethod
    def _business_type(event: Dict[str, object]) -> str:
        level = str(event.get("risk_level") or "")
        action = str(event.get("action_type") or "")
        if level in {"L1", "L2", "L3"}:
            return "emergency_risk"
        if action == "auto_reply":
            return "routine_report"
        if action in {"manual_business", "manual_review"}:
            return "other_business"
        return "other_business"
