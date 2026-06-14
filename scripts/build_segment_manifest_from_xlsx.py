#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd


def norm_sample_stem(raw: object) -> Optional[str]:
    if pd.isna(raw):
        return None
    text = str(raw).strip()
    if not text or text.lower() == "nan":
        return None
    match = re.match(r"^(\d+)_(seg\d+)$", text, re.I)
    if match:
        base = int(match.group(1))
        segnum = int(re.search(r"\d+", match.group(2)).group())
        return f"{base:06d}__seg{segnum:03d}"
    match = re.match(r"^(\d+)_(\d+)$", text)
    if match:
        return f"{int(match.group(1)):06d}__seg{int(match.group(2)):03d}"
    match = re.match(r"^(\d+)$", text)
    if match:
        return f"{int(match.group(1)):06d}__seg000"
    return None


def row_index_by_label(df: pd.DataFrame) -> Dict[str, int]:
    mapping: Dict[str, int] = {}
    for row_idx in range(len(df)):
        label = df.iloc[row_idx, 0]
        if pd.isna(label):
            continue
        mapping[str(label).strip()] = row_idx
    return mapping


def cell_text(df: pd.DataFrame, row_map: Dict[str, int], row_key: str, col_idx: int) -> str:
    row_idx = row_map.get(row_key)
    if row_idx is None:
        return ""
    value = df.iloc[row_idx, col_idx]
    if pd.isna(value):
        return ""
    return str(value).strip()


def build_manifest_rows(
    xlsx_path: Path,
    segments_root: Path,
    only_useful: bool = True,
) -> List[Dict[str, str]]:
    df = pd.read_excel(xlsx_path, sheet_name="Sheet1", header=None)
    row_map = row_index_by_label(df)
    gt_row = next((key for key in row_map if "gt_transcript" in key), None)
    if gt_row is None:
        raise ValueError("标注文档缺少 gt_transcript 行")

    wav_index = {path.stem: path for path in segments_root.rglob("*.wav")}
    rows: List[Dict[str, str]] = []
    seen: set[str] = set()

    for col_idx in range(1, df.shape[1]):
        excel_col = df.iloc[0, col_idx]
        sample_id = norm_sample_stem(excel_col)
        if not sample_id:
            continue
        audio_path = wav_index.get(sample_id)
        if audio_path is None:
            continue
        if only_useful:
            useful = cell_text(df, row_map, "data_usefull", col_idx).lower()
            if useful != "yes":
                continue
        if sample_id in seen:
            continue
        seen.add(sample_id)
        rows.append(
            {
                "sample_id": sample_id,
                "audio_path": str(audio_path.resolve()),
                "excel_col": "" if pd.isna(excel_col) else str(excel_col).strip(),
                "transcript_gt": cell_text(df, row_map, gt_row, col_idx),
                "primary_label_gt": cell_text(df, row_map, "primary_label_gt", col_idx),
                "risk_subtype_gt": cell_text(df, row_map, "risk_subtype_gt(是否emergency yes/no)", col_idx),
                "data_usefull": cell_text(df, row_map, "data_usefull", col_idx),
            }
        )
    return rows


def write_manifest(rows: List[Dict[str, str]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "sample_id",
        "audio_path",
        "excel_col",
        "transcript_gt",
        "primary_label_gt",
        "risk_subtype_gt",
        "data_usefull",
    ]
    with out_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build segment manifest CSV from 标注文档.xlsx.")
    parser.add_argument(
        "--xlsx",
        default="/root/autodl-tmp/0515-vhf-agent/vts_agent/test_results/_segments/标注文档.xlsx",
        type=Path,
    )
    parser.add_argument("--segments-root", type=Path, default=None)
    parser.add_argument("--out", default="data/eval/segments_annotation_manifest.csv", type=Path)
    parser.add_argument("--include-all", action="store_true", help="Include rows even when data_usefull != yes.")
    args = parser.parse_args()

    xlsx_path = args.xlsx.expanduser().resolve()
    segments_root = (args.segments_root or xlsx_path.parent).expanduser().resolve()
    rows = build_manifest_rows(xlsx_path, segments_root, only_useful=not args.include_all)
    write_manifest(rows, args.out.expanduser().resolve())
    print(f"[ok] wrote {len(rows)} rows -> {args.out}")


if __name__ == "__main__":
    main()
