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

    def __init__(
        self,
        lexicon_path: Path,
        enabled: bool = True,
        min_score: float = 0.82,
        vessel_registry_path: Optional[Path] = None,
        ship_min_score: float = 0.90,
        ship_min_margin: float = 0.06,
    ) -> None:
        self.lexicon_path = lexicon_path
        self.enabled = enabled
        self.min_score = min_score
        self.vessel_registry_path = vessel_registry_path
        self.ship_min_score = ship_min_score
        self.ship_min_margin = ship_min_margin
        self._allowed_ship_names: set[str] = set()
        self._registry_entries: List[Tuple[str, str, List[str], str, Dict[str, object]]] = []
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
        candidates = self._filter_ship_candidates(candidates)
        resolved_text = self._apply_safe_replacements(text, candidates)
        return EntityResolution(
            original_text=text,
            resolved_text=resolved_text,
            candidates=candidates,
        )

    def set_dynamic_lexicon(self, payload: Dict[str, List[Dict[str, object]]]) -> None:
        self._ensure_registry_loaded()
        self._dynamic_entries = self._payload_to_entries(payload, default_source="ais_active")

    def is_allowed_ship_name(self, ship_name: str) -> bool:
        self._ensure_registry_loaded()
        return not self._allowed_ship_names or ship_name.strip() in self._allowed_ship_names

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self._ensure_registry_loaded()
        path = self.lexicon_path
        if not path.exists() and Path("data/lexicon_corrections.json").exists():
            path = Path("data/lexicon_corrections.json")
        if not path.exists():
            self._entries = list(self._registry_entries)
            return

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return

        self._entries = [
            *self._registry_entries,
            *self._payload_to_entries(payload, default_source="lexicon"),
        ]

    def _ensure_registry_loaded(self) -> None:
        if self._allowed_ship_names or self.vessel_registry_path is None:
            return
        path = self.vessel_registry_path
        project_registry = Path("data/hotwords/nbzh_vessel_registry.json")
        if not path.exists() and project_registry.exists():
            path = project_registry
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        for item in payload.get("ships", []) if isinstance(payload, dict) else []:
            if isinstance(item, str):
                canonical = item.strip()
            elif isinstance(item, dict):
                canonical = str(item.get("canonical") or "").strip()
            else:
                canonical = ""
            if canonical:
                self._allowed_ship_names.add(canonical)
        self._registry_entries = self._payload_to_entries(payload, default_source="controlled_registry")

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
                if entity_type == "ship" and self._allowed_ship_names and canonical not in self._allowed_ship_names:
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

    def _filter_ship_candidates(self, candidates: List[EntityCandidate]) -> List[EntityCandidate]:
        ships = [candidate for candidate in candidates if candidate.entity_type == "ship"]
        others = [candidate for candidate in candidates if candidate.entity_type != "ship"]
        if not ships:
            return candidates
        ships.sort(key=lambda item: item.score, reverse=True)
        best = ships[0]
        if best.score < self.ship_min_score:
            return others
        if len(ships) > 1 and best.score - ships[1].score < self.ship_min_margin:
            return others
        return sorted([best, *others], key=lambda item: item.score, reverse=True)[:8]

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
        if entity_type == "ship" and (len(normalized_alias) < 3 or normalized_alias.isdigit()):
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
            if candidate.canonical != candidate.matched_text and candidate.matched_text in resolved:
                resolved = resolved.replace(candidate.matched_text, candidate.canonical)
            for entity_type, canonical, aliases, _, _ in [*self._dynamic_entries, *self._entries]:
                if entity_type != candidate.entity_type or canonical != candidate.canonical:
                    continue
                for alias in sorted(aliases, key=len, reverse=True):
                    if alias != canonical and alias in resolved:
                        resolved = resolved.replace(alias, canonical)
        if fuzzy_hints:
            resolved = f"{resolved}（AIS候选：{'、'.join(sorted(set(fuzzy_hints))[:3])}）"
        return resolved
