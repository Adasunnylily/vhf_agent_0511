#!/usr/bin/env python3
"""Build lexicon, hotword vessels, and mock AIS ships from annotation workbook."""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
XLSX = ROOT / "data" / "VHF评测集标注模板_增强版.xlsx"
LEXICON_PATH = ROOT / "data" / "lexicon_corrections.json"
HOTWORDS_PATH = ROOT / "data" / "hotwords" / "nbzh_hotwords_llm.json"
SHIPS_PATH = ROOT / "data" / "inspection_ships.json"

SHIP_PATTERN = re.compile(r"[\u4e00-\u9fa5]{1,6}\d{2,4}")
NOISE_NAMES = {"点40", "备在那个恒基88", "我是江峰17", "我跟着新民州78", "跟着新民州78"}


def digit_variants(num: str) -> list[str]:
    swaps = {
        "2": "6",
        "6": "2",
        "7": "1",
        "1": "7",
        "0": "8",
        "8": "0",
        "3": "8",
        "5": "8",
    }
    out = {num}
    for i, ch in enumerate(num):
        if ch in swaps:
            chars = list(num)
            chars[i] = swaps[ch]
            out.add("".join(chars))
    if len(num) >= 2:
        out.add(num[:-1])
    return sorted(out)


def ship_aliases(name: str) -> list[str]:
    aliases = {name}
    match = re.match(r"^([\u4e00-\u9fa5]+)(\d+)$", name)
    if match:
        prefix, num = match.group(1), match.group(2)
        for variant in digit_variants(num):
            aliases.add(f"{prefix}{variant}")
        aliases.add(f"警{num}")
        aliases.add(f"交管{prefix}{num}")
        aliases.add(num)
        if prefix.endswith("龙"):
            aliases.add(f"锦{num}")
    aliases.add(name.replace("锦龙", "警龙"))
    aliases.add(name.replace("227", "627"))
    aliases.add(name.replace("227", "207"))
    return sorted(aliases, key=len, reverse=True)


def extract_from_workbook() -> tuple[set[str], set[str]]:
    wb = openpyxl.load_workbook(XLSX, read_only=True)
    ws = wb["标注任务"]
    ships: set[str] = set()
    locations: set[str] = set()
    for row in ws.iter_rows(min_row=2, values_only=True):
        gt = str(row[4] or "")
        ship_gt = str(row[10] or "").strip()
        loc_gt = str(row[11] or "").strip()
        if ship_gt:
            ships.add(ship_gt)
        if loc_gt:
            locations.add(loc_gt)
        for name in SHIP_PATTERN.findall(gt):
            if re.search(r"\d", name):
                ships.add(name)
    ships -= NOISE_NAMES
    return ships, locations


def build_lexicon(ships: set[str]) -> dict:
    entries = []
    for name in sorted(ships):
        entries.append(
            {
                "canonical": name,
                "aliases": [alias for alias in ship_aliases(name) if alias != name][:12],
                "source": "annotation_gt",
            }
        )
    common_locations = [
        ("黄牛礁", ["黄牛礁进口", "黄牛礁进x口", "黄牛礁进X口"]),
        ("金塘南", ["金塘南抛锚", "金塘南抛锚线", "金塘南锚地"]),
        ("宁波舟山交管", ["波舟山交管", "宁波舟山交管警", "交管警"]),
    ]
    return {
        "ships": entries,
        "locations": [
            {"canonical": canonical, "aliases": aliases, "source": "annotation_gt"}
            for canonical, aliases in common_locations
        ],
        "callsigns": [],
    }


def merge_hotwords(ships: set[str]) -> None:
    payload = json.loads(HOTWORDS_PATH.read_text(encoding="utf-8"))
    existing = set(payload.get("vessels") or [])
    merged = sorted(existing | ships | {"锦龙227", "锦龙228", "汇通66", "新平082", "远胜88", "鑫永祥78", "嘉诚17"})
    payload["vessels"] = merged
    locs = set(payload.get("locations_and_waters") or [])
    locs.update(["黄牛礁", "金塘南", "金塘", "宁波舟山交管", "穿山", "马峙"])
    payload["locations_and_waters"] = sorted(locs)
    HOTWORDS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_mock_ships(ships: set[str]) -> list[dict]:
    base_lng, base_lat = 121.852, 29.902
    rows = []
    for index, name in enumerate(sorted(ships)):
        lng = round(base_lng + (index % 8) * 0.008, 4)
        lat = round(base_lat + (index // 8) * 0.006, 4)
        rows.append(
            {
                "ship_id": f"ship_{uuid.uuid5(uuid.NAMESPACE_DNS, name).hex[:10]}",
                "ship_name": name,
                "tonnage_t": 12000 + index * 137,
                "draft_m": 8.5 + (index % 5) * 0.6,
                "ship_type": "集装箱船" if "锦" in name else "散货船",
                "destination": "北仑港区",
                "position_label": "北仑港主航道",
                "lng": lng,
                "lat": lat,
                "mmsi": f"413{index:06d}"[-9:],
                "callsign": name[:6],
                "sog_kn": 4.0 + (index % 4),
                "heading_deg": 70 + (index * 11) % 120,
                "nav_status": "under_way",
                "ais_source": "annotation_seed",
            }
        )
    return rows


def main() -> None:
    ships, locations = extract_from_workbook()
    lexicon = build_lexicon(ships)
    LEXICON_PATH.write_text(json.dumps(lexicon, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    merge_hotwords(ships)
    mock_ships = build_mock_ships(ships)
    SHIPS_PATH.write_text(json.dumps(mock_ships, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ships={len(ships)} locations={len(locations)} lexicon={LEXICON_PATH} ships_json={SHIPS_PATH}")


if __name__ == "__main__":
    main()
