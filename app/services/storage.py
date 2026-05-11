from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import BinaryIO

from app.config import Settings
from app.domain.models import RiskEvent


class LocalStorage:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.ensure_dirs()

    def save_upload(self, source: BinaryIO, original_name: str) -> Path:
        suffix = Path(original_name).suffix or ".bin"
        filename = f"{uuid.uuid4().hex}{suffix}"
        target = self.settings.upload_dir / filename
        with target.open("wb") as f:
            shutil.copyfileobj(source, f)
        return target

    def allocate_clip_path(self, suffix: str = ".wav") -> Path:
        filename = f"{uuid.uuid4().hex}{suffix}"
        return self.settings.clip_dir / filename

    def allocate_normalized_path(self, suffix: str = ".wav") -> Path:
        filename = f"{uuid.uuid4().hex}{suffix}"
        return self.settings.normalized_dir / filename

    def allocate_enhanced_path(self, suffix: str = ".wav") -> Path:
        filename = f"{uuid.uuid4().hex}{suffix}"
        return self.settings.enhanced_dir / filename

    def save_event(self, event: RiskEvent) -> Path:
        target = self.settings.event_dir / f"{event.id}.json"
        with target.open("w", encoding="utf-8") as f:
            json.dump(event.to_dict(), f, ensure_ascii=False, indent=2)
        return target
