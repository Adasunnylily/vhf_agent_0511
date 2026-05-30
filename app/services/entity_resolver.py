from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


def normalize_entity_text(text: str) -> str:
    text = (text or "").strip().lower()
    text = text.replace("（", "(").replace("）", ")")
    return re.sub(r"[\s,，.。:：;；!?！？、\"'“”‘’()\[\]【】{}<>《》\-_/\\|~`^#]+", "", text)


@dataclass(frozen=True)
class EntityCandidate:
    entity_type: str
    canonical: str
    matched_text: str
    score: float
    reason: str
    source: str = "lexicon"
    metadata: Dict[str, object] = None  # type: ignore[assignment]

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        if payload.get("metadata") is None:
            payload["metadata"] = {}
        return payload


@dataclass(frozen=True)
class EntityResolution:
    original_text: str
    resolved_text: str
    candidates: List[EntityCandidate]

    def to_dict(self) -> Dict[str, object]:
        return {
            "original_text": self.original_text,
            "resolved_text": self.resolved_text,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


class EntityResolver:
    """Resolve maritime ship/location entities with a lexicon plus fuzzy candidates."""

    def __init__(self, lexicon_path: Path, enabled: bool = True, min_score: float = 0.82) -> None:
        self.lexicon_path = lexicon_path
        self.enabled = enabled
        self.min_score = min_score
        self._entries: List[Tuple[str, str, List[str], str, Dict[str, object]]] = []
        self._dynamic_entries: List[Tuple[str, str, List[str], str, Dict[str, object]]] = []
        self._loaded = False

    def resolve(self, text: str) -> EntityResolution:
        if not self.enabled or not text:
            return EntityResolution(original_text=text, resolved_text=text, candidates=[])
        self._ensure_loaded()
        if not self._entries:
            return EntityResolution(original_text=text, resolved_text=text, candidates=[])

        candidates = self._match_candidates(text)
        resolved_text = self._apply_safe_replacements(text, candidates)
        return EntityResolution(
            original_text=text,
            resolved_text=resolved_text,
            candidates=candidates,
        )

    def set_dynamic_lexicon(self, payload: Dict[str, List[Dict[str, object]]]) -> None:
        self._dynamic_entries = self._payload_to_entries(payload, default_source="ais_active")

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        path = self.lexicon_path
        if not path.exists() and Path("data/lexicon_corrections.json").exists():
            path = Path("data/lexicon_corrections.json")
        if not path.exists():
            return

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return

        self._entries = self._payload_to_entries(payload, default_source="lexicon")

    def _payload_to_entries(
        self,
        payload: Dict[str, List[Dict[str, object]]],
        default_source: str,
    ) -> List[Tuple[str, str, List[str], str, Dict[str, object]]]:
        entries: List[Tuple[str, str, List[str], str, Dict[str, object]]] = []
        for section, entity_type in (("ships", "ship"), ("locations", "location"), ("callsigns", "callsign")):
            for item in payload.get(section, []):
                canonical = str(item.get("canonical", "")).strip()
                if not canonical:
                    continue
                aliases = [str(alias).strip() for alias in item.get("aliases", []) if str(alias).strip()]
                values = sorted(set([canonical, *aliases]), key=len, reverse=True)
                source = str(item.get("source") or default_source)
                metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
                entries.append((entity_type, canonical, values, source, metadata))  # type: ignore[arg-type]
        return entries

    def _match_candidates(self, text: str) -> List[EntityCandidate]:
        normalized_text = normalize_entity_text(text)
        found: Dict[Tuple[str, str], EntityCandidate] = {}

        for entity_type, canonical, aliases, source, metadata in [*self._dynamic_entries, *self._entries]:
            best: Optional[EntityCandidate] = None
            for alias in aliases:
                candidate = self._score_alias(text, normalized_text, canonical, alias, entity_type, source, metadata)
                if candidate and (best is None or candidate.score > best.score):
                    best = candidate
            if best and best.score >= self.min_score:
                key = (best.entity_type, best.canonical)
                previous = found.get(key)
                if previous is None or best.score > previous.score:
                    found[key] = best

        return sorted(found.values(), key=lambda item: item.score, reverse=True)[:8]

    def _score_alias(
        self,
        raw_text: str,
        normalized_text: str,
        canonical: str,
        alias: str,
        entity_type: str,
        source: str,
        metadata: Dict[str, object],
    ) -> Optional[EntityCandidate]:
        normalized_alias = normalize_entity_text(alias)
        if not normalized_alias:
            return None
        if alias and alias in raw_text:
            return EntityCandidate(entity_type, canonical, alias, 1.0, "exact", source, metadata)
        if normalized_alias in normalized_text:
            return EntityCandidate(entity_type, canonical, alias, 0.96, "normalized_exact", source, metadata)

        score = self._best_window_similarity(normalized_text, normalized_alias)
        if source == "ais_active" and score >= max(0.76, self.min_score - 0.06):
            score = min(0.95, score + 0.04)
        if score >= self.min_score:
            return EntityCandidate(entity_type, canonical, alias, score, "fuzzy", source, metadata)
        return None

    def _best_window_similarity(self, text: str, alias: str) -> float:
        if not text or not alias:
            return 0.0
        alias_len = len(alias)
        min_len = max(2, alias_len - 2)
        max_len = min(len(text), alias_len + 2)
        best = 0.0
        for size in range(min_len, max_len + 1):
            for start in range(0, max(1, len(text) - size + 1)):
                window = text[start : start + size]
                score = SequenceMatcher(None, window, alias).ratio()
                if score > best:
                    best = score
        return best

    def _apply_safe_replacements(self, text: str, candidates: Iterable[EntityCandidate]) -> str:
        resolved = text
        fuzzy_hints: List[str] = []
        for candidate in sorted(candidates, key=lambda item: len(item.matched_text), reverse=True):
            if candidate.reason == "fuzzy" and candidate.source == "ais_active" and candidate.score >= 0.86:
                fuzzy_hints.append(candidate.canonical)
                continue
            if candidate.reason not in {"exact", "normalized_exact"} or candidate.score < 0.96:
                continue
            if candidate.canonical == candidate.matched_text:
                continue
            if candidate.matched_text in resolved:
                resolved = resolved.replace(candidate.matched_text, candidate.canonical)
        if fuzzy_hints:
            resolved = f"{resolved}（AIS候选：{'、'.join(sorted(set(fuzzy_hints))[:3])}）"
        return resolved
