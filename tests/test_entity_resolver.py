import json
import tempfile
import unittest
from pathlib import Path

from app.services.entity_resolver import EntityResolver


class EntityResolverRegistryTests(unittest.TestCase):
    def _resolver(self, directory: str) -> EntityResolver:
        root = Path(directory)
        registry = root / "registry.json"
        registry.write_text(
            json.dumps(
                {
                    "ships": [
                        {"canonical": "锦龙228", "aliases": ["锦龙二二八"]},
                        {"canonical": "锦华662", "aliases": ["警花662"]},
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        lexicon = root / "lexicon.json"
        lexicon.write_text(
            json.dumps(
                {
                    "ships": [
                        {"canonical": "锦龙228", "aliases": ["锦龙二二八"]},
                        {"canonical": "虚构船999", "aliases": ["虚构船"]},
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        resolver = EntityResolver(
            lexicon,
            vessel_registry_path=registry,
            ship_min_score=0.90,
            ship_min_margin=0.06,
        )
        resolver.set_dynamic_lexicon(
            {
                "ships": [
                    {"canonical": "锦华662", "aliases": ["警花662"], "metadata": {"ship_id": "known"}},
                    {"canonical": "错误船123", "aliases": ["错误船"], "metadata": {"ship_id": "unknown"}},
                ]
            }
        )
        return resolver

    def test_known_alias_matches_reviewed_ship(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self._resolver(directory).resolve("警花662，请讲")

        ships = [candidate for candidate in result.candidates if candidate.entity_type == "ship"]
        self.assertEqual(["锦华662"], [candidate.canonical for candidate in ships])

    def test_unknown_ship_is_not_eligible_for_ais_link(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self._resolver(directory).resolve("错误船，请讲")

        self.assertFalse(any(candidate.entity_type == "ship" for candidate in result.candidates))


if __name__ == "__main__":
    unittest.main()
