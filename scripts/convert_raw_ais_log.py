#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


HEADER = [
    "ship_name",
    "mmsi",
    "callsign",
    "imo",
    "ship_type",
    "tonnage_t",
    "draft_m",
    "length_m",
    "width_m",
    "sog_kn",
    "cog_deg",
    "heading_deg",
    "lng",
    "lat",
    "destination",
    "position_label",
    "nav_status",
    "cargo_type",
    "eta",
    "ais_update_time",
    "ais_source",
]

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


@dataclass
class AISShipState:
    mmsi: str
    ship_name: str = ""
    callsign: str = ""
    imo: str = ""
    ship_type: str = ""
    draft_m: float = 0.0
    length_m: float = 0.0
    width_m: float = 0.0
    sog_kn: float = 0.0
    cog_deg: float = 0.0
    heading_deg: float = 0.0
    lng: Optional[float] = None
    lat: Optional[float] = None
    destination: str = ""
    nav_status: str = ""
    ais_update_time: str = ""
    ais_source: str = "raw_ais_log"
    position_count: int = 0
    extras: Dict[str, str] = field(default_factory=dict)

    def to_row(self) -> Dict[str, object]:
        name = self.ship_name.strip() or f"MMSI_{self.mmsi}"
        return {
            "ship_name": name,
            "mmsi": self.mmsi,
            "callsign": self.callsign,
            "imo": self.imo,
            "ship_type": self.ship_type or "未知",
            "tonnage_t": 0,
            "draft_m": self.draft_m,
            "length_m": self.length_m,
            "width_m": self.width_m,
            "sog_kn": round(self.sog_kn, 2),
            "cog_deg": round(self.cog_deg, 1),
            "heading_deg": round(self.heading_deg, 1),
            "lng": "" if self.lng is None else round(self.lng, 6),
            "lat": "" if self.lat is None else round(self.lat, 6),
            "destination": self.destination,
            "position_label": "AIS原始数据",
            "nav_status": self.nav_status or "AIS动态",
            "cargo_type": "",
            "eta": "",
            "ais_update_time": self.ais_update_time,
            "ais_source": self.ais_source,
        }


def open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="ignore", newline="")
    return path.open("r", encoding="utf-8", errors="ignore", newline="")


def parse_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_int(value: str, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def signed(raw: int, bits: int) -> int:
    limit = 1 << bits
    if raw >= limit // 2:
        return raw - limit
    return raw


def coordinate_candidates(raw: str, axis: str) -> List[float]:
    value = parse_float(raw, math.nan)
    if math.isnan(value):
        return []
    raw_int = int(value)
    bits = 28 if axis == "lng" else 27
    candidates = [
        value,
        value / 1_000_000.0,
        value / 600_000.0,
        signed(raw_int, bits) / 600_000.0,
        value / 600.0,
        signed(raw_int, 18 if axis == "lng" else 17) / 600.0,
    ]
    low, high = (-180.0, 180.0) if axis == "lng" else (-90.0, 90.0)
    return [item for item in candidates if low <= item <= high]


def choose_coordinate(raw: str, axis: str, bbox: Optional[Tuple[float, float, float, float]]) -> Optional[float]:
    candidates = coordinate_candidates(raw, axis)
    if not candidates:
        return None
    if bbox:
        min_lng, min_lat, max_lng, max_lat = bbox
        low, high = (min_lng, max_lng) if axis == "lng" else (min_lat, max_lat)
        for item in candidates:
            if low <= item <= high:
                return item
    # Prefer normal decimal degrees over tiny near-zero decoded fallbacks.
    candidates.sort(key=lambda item: (abs(item) < 1.0, abs(item)))
    return candidates[0]


def normalize_speed(raw: str) -> float:
    speed = parse_float(raw)
    if speed > 60:
        return speed / 10.0
    return speed


def normalize_angle(raw: str) -> float:
    angle = parse_float(raw)
    if angle > 360 and angle <= 3600:
        return angle / 10.0
    return angle if 0 <= angle <= 360 else 0.0


def row_timestamp(parts: List[str]) -> str:
    if len(parts) >= 2:
        return parts[-3] if len(parts) >= 3 else parts[-1]
    return ""


def update_static(parts: List[str], states: Dict[str, AISShipState]) -> None:
    if len(parts) < 3:
        return
    msg_type = parse_int(parts[0])
    mmsi = parts[2].strip()
    if not mmsi:
        return
    state = states.setdefault(mmsi, AISShipState(mmsi=mmsi))
    if msg_type == 5 and len(parts) >= 19:
        state.imo = parts[4].strip()
        state.callsign = parts[5].strip()
        state.ship_name = parts[6].strip() or state.ship_name
        state.ship_type = parts[7].strip() or state.ship_type
        state.length_m = parse_float(parts[8]) + parse_float(parts[9])
        state.width_m = parse_float(parts[10]) + parse_float(parts[11])
        state.draft_m = parse_float(parts[17])
        state.destination = parts[18].strip()
    elif msg_type == 24 and len(parts) >= 5:
        partno = parse_int(parts[3])
        if partno == 0:
            state.ship_name = parts[4].strip() or state.ship_name
        elif partno == 1:
            state.ship_type = parts[4].strip() or state.ship_type
            if len(parts) > 6:
                state.callsign = parts[6].strip() or state.callsign
    state.ais_update_time = row_timestamp(parts)


def update_position(
    parts: List[str],
    states: Dict[str, AISShipState],
    bbox: Optional[Tuple[float, float, float, float]],
) -> None:
    if len(parts) < 10:
        return
    msg_type = parse_int(parts[0])
    mmsi = parts[2].strip()
    if not mmsi:
        return
    layout = {
        1: (7, 8, 5, 9, 10, 3),
        2: (7, 8, 5, 9, 10, 3),
        3: (7, 8, 5, 9, 10, 3),
        18: (6, 7, 5, 8, 9, None),
        19: (6, 7, 5, 8, 9, None),
        27: (6, 7, 8, 9, None, 5),
    }.get(msg_type)
    if not layout:
        return
    lon_idx, lat_idx, sog_idx, cog_idx, heading_idx, nav_idx = layout
    if len(parts) <= max(lon_idx, lat_idx, sog_idx, cog_idx):
        return
    lng = choose_coordinate(parts[lon_idx], "lng", bbox)
    lat = choose_coordinate(parts[lat_idx], "lat", bbox)
    if lng is None or lat is None:
        return
    if bbox:
        min_lng, min_lat, max_lng, max_lat = bbox
        if not (min_lng <= lng <= max_lng and min_lat <= lat <= max_lat):
            return
    state = states.setdefault(mmsi, AISShipState(mmsi=mmsi))
    state.lng = lng
    state.lat = lat
    state.sog_kn = normalize_speed(parts[sog_idx])
    state.cog_deg = normalize_angle(parts[cog_idx])
    if heading_idx is not None and len(parts) > heading_idx:
        state.heading_deg = normalize_angle(parts[heading_idx])
    if nav_idx is not None and len(parts) > nav_idx:
        state.nav_status = parts[nav_idx].strip()
    state.ais_update_time = row_timestamp(parts)
    state.position_count += 1


def read_name_map(path: Optional[Path]) -> Dict[str, str]:
    if not path:
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = csv.DictReader(handle)
        return {
            str(row.get("mmsi") or "").strip(): str(row.get("ship_name") or row.get("name") or "").strip()
            for row in rows
            if str(row.get("mmsi") or "").strip() and str(row.get("ship_name") or row.get("name") or "").strip()
        }


def convert(
    input_path: Path,
    output_path: Path,
    bbox: Optional[Tuple[float, float, float, float]],
    name_map_path: Optional[Path],
    limit: int,
) -> Dict[str, int]:
    states: Dict[str, AISShipState] = {}
    name_map = read_name_map(name_map_path)
    total = 0
    with open_text(input_path) as handle:
        reader = csv.reader(handle)
        for parts in reader:
            if not parts:
                continue
            total += 1
            msg_type = parse_int(parts[0], -1)
            if msg_type in {5, 24}:
                update_static(parts, states)
            elif msg_type in {1, 2, 3, 18, 19, 27}:
                update_position(parts, states, bbox)
            if limit and total >= limit:
                break

    for mmsi, ship_name in name_map.items():
        if mmsi in states:
            states[mmsi].ship_name = ship_name

    rows = [state.to_row() for state in states.values() if state.lng is not None and state.lat is not None]
    rows.sort(key=lambda row: str(row["mmsi"]))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADER)
        writer.writeheader()
        writer.writerows(rows)
    return {"raw_rows": total, "ships": len(rows), "named_ships": sum(1 for row in rows if not str(row["ship_name"]).startswith("MMSI_"))}


def parse_bbox(value: str) -> Optional[Tuple[float, float, float, float]]:
    if not value:
        return None
    parts = [float(item.strip()) for item in value.split(",")]
    if len(parts) != 4:
        raise ValueError("--bbox must be min_lng,min_lat,max_lng,max_lat")
    return parts[0], parts[1], parts[2], parts[3]


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert raw decoded AIS CSV log(.gz) to VHF agent AIS import CSV.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--out", type=Path, default=Path("data/ais_today_import.csv"))
    parser.add_argument("--bbox", default="", help="Optional min_lng,min_lat,max_lng,max_lat filter, e.g. 121.7,29.7,122.2,30.1")
    parser.add_argument("--ship-name-map", type=Path, default=None, help="Optional CSV with mmsi,ship_name columns")
    parser.add_argument("--limit", type=int, default=0, help="Read only first N raw rows for quick tests")
    args = parser.parse_args()
    summary = convert(args.input, args.out, parse_bbox(args.bbox), args.ship_name_map, args.limit)
    print(f"raw_rows={summary['raw_rows']} ships={summary['ships']} named_ships={summary['named_ships']} out={args.out}")


if __name__ == "__main__":
    main()
