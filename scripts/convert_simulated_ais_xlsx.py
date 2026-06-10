#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


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


SHIP_TYPE_MAP = {
    "拖船": "拖船",
    "港作拖船": "拖船",
    "引航船": "引航船",
    "集装箱船": "集装箱船",
    "集装箱支线船": "集装箱船",
    "散货船": "散货船",
    "油船": "油船",
    "成品油船": "油船",
    "化学品船": "化学品船",
    "多用途船": "多用途船",
    "挖泥船": "工程船",
    "工程船": "工程船",
    "供水船": "港作船",
    "供油船": "港作船",
    "大件运输船": "货船",
}


def clean(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def parse_coord(value: object) -> float:
    text = clean(value)
    for token in ["°E", "°N", "°", "E", "N"]:
        text = text.replace(token, "")
    return float(text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert simulated Beilun AIS xlsx to VHF Agent AIS import CSV.")
    parser.add_argument("xlsx", type=Path)
    parser.add_argument("--sheet", default="船舶数据表")
    parser.add_argument("--out", type=Path, default=Path("data/bootstrap/beilun_simulated_ais_import.csv"))
    parser.add_argument("--limit", type=int, default=15, help="Max ships to export for a concise demo map; use 0 for all.")
    args = parser.parse_args()

    source = pd.read_excel(args.xlsx, sheet_name=args.sheet)
    if args.limit > 0:
        source = source.head(args.limit)
    rows = []
    for _, item in source.iterrows():
        raw_type = clean(item.get("船舶类型"))
        speed = float(item.get("航速(kn)") or 0)
        rows.append({
            "ship_name": clean(item.get("中文船名")),
            "mmsi": clean(item.get("MMSI")),
            "callsign": clean(item.get("英文船名")),
            "imo": clean(item.get("IMO")),
            "ship_type": SHIP_TYPE_MAP.get(raw_type, raw_type or "未知"),
            "tonnage_t": clean(item.get("总吨")),
            "draft_m": clean(item.get("吃水(m)")),
            "length_m": clean(item.get("船长(m)")),
            "width_m": clean(item.get("船宽(m)")),
            "sog_kn": clean(item.get("航速(kn)")),
            "cog_deg": "",
            "heading_deg": "",
            "lng": parse_coord(item.get("经度")),
            "lat": parse_coord(item.get("纬度")),
            "destination": "宁波北仑山附近水域",
            "position_label": "北仑山模拟AIS",
            "nav_status": "航行中" if speed > 1 else "静止/锚泊",
            "cargo_type": raw_type,
            "eta": "",
            "ais_update_time": "2026-05-08",
            "ais_source": "simulated_beilun_xlsx",
        })

    args.out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=HEADER).to_csv(args.out, index=False, encoding="utf-8-sig")
    lngs = [row["lng"] for row in rows]
    lats = [row["lat"] for row in rows]
    print(
        f"rows={len(rows)} out={args.out} "
        f"bbox={min(lngs):.4f},{min(lats):.4f},{max(lngs):.4f},{max(lats):.4f}"
    )


if __name__ == "__main__":
    main()
