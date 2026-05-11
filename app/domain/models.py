from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AudioSegment:
    id: str
    channel_id: str
    file_path: str
    clip_path: Optional[str]
    start_ms: int
    end_ms: int
    duration_ms: int
    text: str
    confidence: float
    keywords: List[str] = field(default_factory=list)
    engine: str = "demo"
    status: str = "processed"
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RiskEvent:
    id: str
    segment_id: str
    channel_id: str
    event_type: str
    risk_level: str
    summary: str
    evidence: List[str]
    suggestion: str
    broadcast_text: str
    action_type: str = "manual_review"
    requires_human_review: bool = True
    is_auto_reply: bool = False
    review_status: str = "pending"
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TaskState:
    id: str
    status: str
    channel_id: str
    filename: str
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    error: Optional[str] = None
    segments: List[Dict[str, Any]] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
