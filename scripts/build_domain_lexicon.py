from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, Iterable, List, Set


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def basic_aliases(term: str) -> Set[str]:
    term = normalize_space(term)
    aliases: Set[str] = set()
    if not term:
        return aliases

    aliases.add(term.replace(" ", ""))
    aliases.add(term.replace("（", "(").replace("）", ")"))
    aliases.add(term.replace("(", "（").replace(")", "）"))
    aliases.add(term.replace("#", "号"))
    aliases.add(term.replace("号", ""))
    aliases.add(term.replace("-", ""))
    aliases.add(term.replace(",", "，"))
    aliases.add(term.replace("，", ","))
    aliases.add(re.sub(r"[()（）]", "", term))

    if re.search(r"[A-Za-z]", term):
        aliases.add(term.upper())
        aliases.add(term.lower())
        aliases.add(term.title())
        aliases.add(term.replace(" ", "").upper())

    return {x for x in aliases if x and x != term}


def merge_manual_aliases(base: Dict[str, Dict[str, Set[str]]], manual_list: Iterable[Dict[str, object]], section: str) -> None:
    for item in manual_list:
        canonical = normalize_space(str(item.get("canonical", "")))
        if not canonical:
            continue
        aliases = {normalize_space(str(x)) for x in item.get("aliases", []) if normalize_space(str(x))}
        if canonical not in base[section]:
            base[section][canonical] = set()
        base[section][canonical].update(a for a in aliases if a and a != canonical)


def build(seed_path: Path, lexicon_out: Path, hotwords_out: Path) -> None:
    seed = json.loads(seed_path.read_text(encoding="utf-8"))

    canonical_map: Dict[str, Dict[str, Set[str]]] = {
        "ships": {},
        "locations": {},
        "callsigns": {},
    }

    for section in ("ships", "locations"):
        for term in seed.get(section, []):
            canonical = normalize_space(str(term))
            if not canonical:
                continue
            canonical_map[section].setdefault(canonical, set()).update(basic_aliases(canonical))

    manual = seed.get("manual_aliases", {})
    merge_manual_aliases(canonical_map, manual.get("ships", []), "ships")
    merge_manual_aliases(canonical_map, manual.get("locations", []), "locations")

    lexicon = {
        "ships": [
            {"canonical": canonical, "aliases": sorted(list(aliases))}
            for canonical, aliases in sorted(canonical_map["ships"].items())
            if aliases
        ],
        "locations": [
            {"canonical": canonical, "aliases": sorted(list(aliases))}
            for canonical, aliases in sorted(canonical_map["locations"].items())
            if aliases
        ],
        "callsigns": [],
    }

    lexicon_out.parent.mkdir(parents=True, exist_ok=True)
    lexicon_out.write_text(json.dumps(lexicon, ensure_ascii=False, indent=2), encoding="utf-8")

    hotwords: List[str] = []
    for section in ("ships", "locations"):
        hotwords.extend(normalize_space(str(x)) for x in seed.get(section, []) if normalize_space(str(x)))
    hotwords.extend(item["canonical"] for item in lexicon["ships"])
    hotwords.extend(item["canonical"] for item in lexicon["locations"])
    hotwords = sorted(set(hotwords), key=lambda x: (len(x), x), reverse=True)

    hotwords_out.parent.mkdir(parents=True, exist_ok=True)
    hotwords_out.write_text("\n".join(hotwords) + "\n", encoding="utf-8")

    print(f"[ok] lexicon -> {lexicon_out}")
    print(f"[ok] hotwords -> {hotwords_out} ({len(hotwords)} items)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build maritime lexicon corrections and hotwords from seed entities.")
    parser.add_argument(
        "--seed",
        type=Path,
        default=Path("data/bootstrap/nbzh_seed_entities.json"),
        help="seed entities json path",
    )
    parser.add_argument(
        "--lexicon-out",
        type=Path,
        default=Path("data/lexicon_corrections.json"),
        help="output lexicon json path",
    )
    parser.add_argument(
        "--hotwords-out",
        type=Path,
        default=Path("data/hotwords/nbzh_hotwords.txt"),
        help="output hotwords txt path",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build(args.seed, args.lexicon_out, args.hotwords_out)


if __name__ == "__main__":
    main()

