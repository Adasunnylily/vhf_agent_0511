from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class ReplacementRule:
    canonical: str
    aliases: List[str]


class LexiconCorrector:
    def __init__(self, config_path: Path, enabled: bool = True) -> None:
        self.config_path = config_path
        self.enabled = enabled
        self._rules: List[ReplacementRule] = []
        self._load()

    def _load(self) -> None:
        if not self.enabled:
            self._rules = []
            return
        if not self.config_path.exists():
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            default = {
                "ships": [
                    {"canonical": "锦龙008", "aliases": ["锦华662", "金堂南", "96008"]},
                    {"canonical": "警花662", "aliases": ["警官六六", "警花六六"]},
                ],
                "locations": [
                    {"canonical": "北仑主航道A3段", "aliases": ["主航道A3", "A3段"]},
                    {"canonical": "172号泊位", "aliases": ["16 172号泊位", "一七二号泊位"]},
                ],
            }
            self.config_path.write_text(
                json.dumps(default, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except Exception:
            self._rules = []
            return

        rules: List[ReplacementRule] = []
        for section in ("ships", "locations", "callsigns"):
            for item in data.get(section, []):
                canonical = str(item.get("canonical", "")).strip()
                aliases = [str(x).strip() for x in item.get("aliases", []) if str(x).strip()]
                if canonical and aliases:
                    rules.append(ReplacementRule(canonical=canonical, aliases=aliases))
        rules.sort(key=lambda x: len(x.canonical), reverse=True)
        self._rules = rules

    def correct(self, text: str) -> Tuple[str, List[Dict[str, str]]]:
        if not text or not self.enabled or not self._rules:
            return text, []
        corrected = text
        hits: List[Dict[str, str]] = []
        for rule in self._rules:
            for alias in sorted(rule.aliases, key=len, reverse=True):
                if alias and alias in corrected and alias != rule.canonical:
                    corrected = corrected.replace(alias, rule.canonical)
                    hits.append({"alias": alias, "canonical": rule.canonical})
        return corrected, hits
