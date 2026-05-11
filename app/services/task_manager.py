from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Callable, Dict, Optional

from app.domain.models import TaskState


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class InMemoryTaskManager:
    def __init__(self) -> None:
        self._tasks: Dict[str, TaskState] = {}
        self._lock = threading.Lock()

    def create(self, filename: str, channel_id: str) -> TaskState:
        task = TaskState(
            id=f"task_{uuid.uuid4().hex[:12]}",
            status="queued",
            channel_id=channel_id,
            filename=filename,
        )
        with self._lock:
            self._tasks[task.id] = task
        return task

    def get(self, task_id: str) -> Optional[TaskState]:
        with self._lock:
            return self._tasks.get(task_id)

    def update(self, task_id: str, **fields: object) -> Optional[TaskState]:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            for key, value in fields.items():
                setattr(task, key, value)
            task.updated_at = utc_now_iso()
            return task

    def run_async(self, task_id: str, runner: Callable[[], None]) -> None:
        def wrapped() -> None:
            self.update(task_id, status="running")
            try:
                runner()
            except Exception as exc:
                self.update(task_id, status="failed", error=str(exc))

        thread = threading.Thread(target=wrapped, daemon=True)
        thread.start()
