#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import random
import shutil
from pathlib import Path


PREFERRED_VESSELS = [
    "锦龙228",
    "锦华662",
    "中国银川",
    "新平082",
    "锦龙227",
    "汇通66",
    "兴泰77",
    "江丰9",
    "锦华996",
    "景隆669",
    "昌汇288",
    "甬港拖20",
    "南港拖26",
    "协海107",
    "港通66",
]

# GCJ-02 demo corridors placed over the navigable waters east/north of Beilun.
WATER_CORRIDORS = [
    ("北仑港外航道", [(121.858, 29.968), (121.900, 29.974), (121.943, 29.982)]),
    ("大榭进港航道", [(121.900, 29.951), (121.947, 29.962), (121.990, 29.958)]),
    ("金塘水道南口", [(121.940, 29.991), (121.982, 30.005), (122.025, 30.014)]),
]


def interpolate(points: list[tuple[float, float]], progress: float) -> tuple[float, float, float]:
    progress = max(0.0, min(0.999999, progress))
    scaled = progress * (len(points) - 1)
    index = min(len(points) - 2, int(scaled))
    fraction = scaled - index
    start = points[index]
    end = points[index + 1]
    lng = start[0] + (end[0] - start[0]) * fraction
    lat = start[1] + (end[1] - start[1]) * fraction
    heading = math.degrees(math.atan2(end[0] - start[0], end[1] - start[1])) % 360
    return lng, lat, heading


def generate_positions(names: list[str], seed: int) -> list[dict[str, object]]:
    rng = random.Random(seed)
    ships: list[dict[str, object]] = []
    ship_types = ["集装箱船", "散货船", "杂货船", "油船", "拖船"]
    for index, name in enumerate(names):
        label, corridor = WATER_CORRIDORS[index % len(WATER_CORRIDORS)]
        progress = (index // len(WATER_CORRIDORS) + 1) / (math.ceil(len(names) / len(WATER_CORRIDORS)) + 1)
        progress = max(0.08, min(0.92, progress + rng.uniform(-0.045, 0.045)))
        lng, lat, heading = interpolate(corridor, progress)
        lng += rng.uniform(-0.0014, 0.0014)
        lat += rng.uniform(-0.0010, 0.0010)
        ship_type = ship_types[index % len(ship_types)]
        draft = round(rng.uniform(4.2, 13.8), 1)
        tonnage = rng.randrange(3000, 32000, 100)
        speed = round(rng.uniform(3.5, 11.5), 1)
        mmsi = f"413{seed % 100:02d}{index + 1:04d}"
        ships.append(
            {
                "ship_id": f"mock_{index + 1:03d}",
                "ship_name": name,
                "tonnage_t": tonnage,
                "draft_m": draft,
                "ship_type": ship_type,
                "destination": "宁波舟山港",
                "position_label": label,
                "lng": round(lng, 6),
                "lat": round(lat, 6),
                "mmsi": mmsi,
                "callsign": "",
                "imo": "",
                "length_m": round(rng.uniform(70, 230), 1),
                "width_m": round(rng.uniform(14, 38), 1),
                "sog_kn": speed,
                "cog_deg": round(heading, 1),
                "heading_deg": round(heading, 1),
                "nav_status": "航行中",
                "cargo_type": "",
                "eta": "待定",
                "ais_update_time": "",
                "ais_source": "mock_water_corridor",
            }
        )
    return ships


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic mock AIS positions on Beilun water corridors.")
    parser.add_argument("--registry", default="data/hotwords/nbzh_vessel_registry.json")
    parser.add_argument("--out", default="data/inspection_ships.json")
    parser.add_argument("--count", type=int, default=15)
    parser.add_argument("--seed", type=int, default=20260622)
    parser.add_argument("--backup", action="store_true")
    args = parser.parse_args()

    registry = json.loads(Path(args.registry).read_text(encoding="utf-8"))
    allowed = [str(item.get("canonical") or "").strip() for item in registry.get("ships", [])]
    allowed_set = {name for name in allowed if name}
    selected = [name for name in PREFERRED_VESSELS if name in allowed_set]
    selected.extend(name for name in allowed if name not in selected)
    selected = selected[: max(1, args.count)]

    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.backup and output.exists():
        shutil.copy2(output, output.with_suffix(output.suffix + ".before_water_positions"))
    ships = generate_positions(selected, args.seed)
    output.write_text(json.dumps(ships, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"ships={len(ships)} out={output.resolve()}")


if __name__ == "__main__":
    main()
