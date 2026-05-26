from __future__ import annotations

import argparse
import csv
import re
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, Iterable, List, Tuple
from zipfile import ZipFile


DIGIT_MAP = str.maketrans(
    {
        "零": "0",
        "〇": "0",
        "一": "1",
        "幺": "1",
        "二": "2",
        "两": "2",
        "三": "3",
        "四": "4",
        "五": "5",
        "六": "6",
        "七": "7",
        "八": "8",
        "九": "9",
    }
)


def normalize_name(text: str) -> str:
    text = (text or "").strip()
    text = text.translate(DIGIT_MAP)
    text = text.upper()
    text = text.replace("（", "(").replace("）", ")")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[，,。:：;；、\"'“”‘’\[\]【】{}<>《》_/\\|~`^]+", "", text)
    text = text.replace("#", "号")
    return text


def read_text_terms(path: Path) -> List[str]:
    if not path or not path.exists():
        return []
    terms: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if value and not value.startswith("#"):
            terms.append(value)
    return terms


def read_xlsx_terms(path: Path) -> List[str]:
    if not path.exists():
        return []
    terms: List[str] = []
    with ZipFile(path) as z:
        names = z.namelist()
        shared_strings: List[str] = []
        ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall("a:si", ns):
                parts = [node.text or "" for node in si.findall(".//a:t", ns)]
                shared_strings.append("".join(parts).strip())

        for name in names:
            if not (name.startswith("xl/worksheets/sheet") and name.endswith(".xml")):
                continue
            root = ET.fromstring(z.read(name))
            for cell in root.findall(".//a:c", ns):
                value_node = cell.find("a:v", ns)
                if value_node is None or value_node.text is None:
                    continue
                value = value_node.text.strip()
                if cell.get("t") == "s":
                    index = int(value)
                    value = shared_strings[index] if index < len(shared_strings) else ""
                value = value.strip()
                if value and value not in {"中文船名", "船名"}:
                    terms.append(value)
    return terms


def build_lookup(terms: Iterable[str]) -> Dict[str, str]:
    lookup: Dict[str, str] = {}
    for term in terms:
        term = str(term).strip()
        if not term:
            continue
        key = normalize_name(term)
        if key and key not in lookup:
            lookup[key] = term
    return lookup


def best_fuzzy_match(candidate: str, lookup: Dict[str, str], threshold: float) -> Tuple[str, float]:
    normalized = normalize_name(candidate)
    if not normalized:
        return "", 0.0
    best_key = ""
    best_score = 0.0
    for key in lookup:
        if abs(len(key) - len(normalized)) > 2:
            continue
        score = SequenceMatcher(None, normalized, key).ratio()
        if score > best_score:
            best_key = key
            best_score = score
    if best_score >= threshold:
        return lookup[best_key], best_score
    return "", best_score


def match_candidate(
    candidate: str,
    entity_type: str,
    ship_lookup: Dict[str, str],
    location_lookup: Dict[str, str],
    ship_fuzzy_threshold: float,
    location_fuzzy_threshold: float,
) -> Tuple[str, str, float]:
    normalized = normalize_name(candidate)
    lookup = ship_lookup if entity_type == "ship" else location_lookup
    if normalized in lookup:
        return lookup[normalized], "exact", 1.0

    if entity_type == "ship":
        canonical, score = best_fuzzy_match(candidate, lookup, ship_fuzzy_threshold)
        return (canonical, "fuzzy", score) if canonical else ("", "", score)

    canonical, score = best_fuzzy_match(candidate, lookup, location_fuzzy_threshold)
    return (canonical, "fuzzy", score) if canonical else ("", "", score)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Auto-label entity candidate review CSV with known ship/location lists.")
    parser.add_argument("--review-csv", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--ship-xlsx", type=Path, default=Path("/Users/adasunnylily/Downloads/智能体大赛/船名.xlsx"))
    parser.add_argument("--extra-ships", type=Path, default=Path("data/bootstrap/known_ships_extra_0526.txt"))
    parser.add_argument("--locations", type=Path, default=Path("data/bootstrap/known_locations_0526.txt"))
    parser.add_argument("--ship-fuzzy-threshold", type=float, default=0.94)
    parser.add_argument("--location-fuzzy-threshold", type=float, default=0.92)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ship_terms = [*read_xlsx_terms(args.ship_xlsx), *read_text_terms(args.extra_ships)]
    location_terms = read_text_terms(args.locations)
    ship_lookup = build_lookup(ship_terms)
    location_lookup = build_lookup(location_terms)

    with args.review_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    for field in ["auto_match_type", "known_source", "match_score"]:
        if field not in fieldnames:
            fieldnames.append(field)

    labeled = 0
    for row in rows:
        entity_type = (row.get("entity_type") or "").strip()
        candidate = (row.get("candidate") or "").strip()
        if entity_type not in {"ship", "location"} or not candidate:
            continue
        canonical, match_type, score = match_candidate(
            candidate,
            entity_type,
            ship_lookup,
            location_lookup,
            args.ship_fuzzy_threshold,
            args.location_fuzzy_threshold,
        )
        if not canonical:
            row.setdefault("auto_match_type", "")
            row.setdefault("known_source", "")
            row.setdefault("match_score", f"{score:.3f}" if score else "")
            continue
        row["canonical_gt"] = canonical
        row["accept_gt"] = "yes"
        row["auto_match_type"] = match_type
        row["known_source"] = "ship_xlsx_or_extra" if entity_type == "ship" else "known_locations"
        row["match_score"] = f"{score:.3f}"
        labeled += 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[ok] rows={len(rows)} labeled={labeled} -> {args.out}")
    print(f"[info] known ships={len(ship_lookup)} locations={len(location_lookup)}")


if __name__ == "__main__":
    main()
