#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Dict, List, Optional, Set

import pandas as pd


def norm_excel_col(raw: object) -> Optional[str]:
    if pd.isna(raw):
        return None
    text = str(raw).strip().replace(" ", "")
    if not text or text.lower() == "nan":
        return None
    return text


def candidate_audio_keys(excel_col: str) -> List[str]:
    """根据 Excel 列名生成可能的 wav stem 别名。"""
    keys: List[str] = []
    seen: Set[str] = set()

    def add(key: Optional[str]) -> None:
        if not key or key in seen:
            return
        seen.add(key)
        keys.append(key)

    add(excel_col)
    match = re.match(r"^(\d+)_(seg\d+)$", excel_col, re.I)
    if match:
        base = int(match.group(1))
        segnum = int(re.search(r"\d+", match.group(2)).group())
        add(f"{base:06d}__seg{segnum:03d}")
        add(f"{base:06d}_{segnum}")
        if segnum == 0:
            add(f"{base:06d}_0")
        add(f"{base:06d}")
        add(str(base))
        return keys
    match = re.match(r"^(\d+)_(\d+)$", excel_col)
    if match:
        base = int(match.group(1))
        segnum = int(match.group(2))
        add(f"{base:06d}__seg{segnum:03d}")
        add(f"{base:06d}_{segnum}")
        add(f"{base:06d}")
        add(str(base))
        return keys
    match = re.match(r"^(\d+)$", excel_col)
    if match:
        base = int(match.group(1))
        add(f"{base:06d}__seg000")
        add(f"{base:06d}")
        add(str(base))
        return keys
    return keys


def build_wav_index(audio_root: Path) -> Dict[str, Path]:
    index: Dict[str, Path] = {}
    for path in audio_root.rglob("*.wav"):
        stem = path.stem.strip().replace(" ", "")
        for key in candidate_audio_keys(stem):
            index.setdefault(key, path)
        index.setdefault(stem, path)
    return index


def resolve_audio_path(excel_col: str, wav_index: Dict[str, Path]) -> Optional[Path]:
    for key in candidate_audio_keys(excel_col):
        path = wav_index.get(key)
        if path is not None:
            return path
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
    audio_root: Path,
    only_useful: bool = True,
) -> List[Dict[str, str]]:
    df = pd.read_excel(xlsx_path, sheet_name="Sheet1", header=None)
    row_map = row_index_by_label(df)
    gt_row = next((key for key in row_map if "gt_transcript" in key), None)
    if gt_row is None:
        raise ValueError("标注文档缺少 gt_transcript 行")

    wav_index = build_wav_index(audio_root)
    rows: List[Dict[str, str]] = []
    seen_paths: set[str] = set()

    for col_idx in range(1, df.shape[1]):
        excel_col = norm_excel_col(df.iloc[0, col_idx])
        if not excel_col:
            continue
        audio_path = resolve_audio_path(excel_col, wav_index)
        if audio_path is None:
            continue
        if only_useful:
            useful = cell_text(df, row_map, "data_usefull", col_idx).lower()
            if useful != "yes":
                continue
        resolved = str(audio_path.resolve())
        if resolved in seen_paths:
            continue
        seen_paths.add(resolved)
        rows.append(
            {
                "sample_id": audio_path.stem.replace(" ", ""),
                "audio_path": resolved,
                "excel_col": excel_col,
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
        "--data-dir",
        type=Path,
        default=None,
        help="数据目录，需含 标注文档.xlsx 与 wav（或 音频分类/ 子目录）。",
    )
    parser.add_argument(
        "--xlsx",
        default=None,
        type=Path,
        help="标注 xlsx 路径；默认取 --data-dir/标注文档.xlsx",
    )
    parser.add_argument(
        "--audio-root",
        type=Path,
        default=None,
        help="音频搜索根目录；默认取 --data-dir",
    )
    parser.add_argument("--out", default="data/eval/segments_annotation_manifest.csv", type=Path)
    parser.add_argument("--include-all", action="store_true", help="Include rows even when data_usefull != yes.")
    args = parser.parse_args()

    default_data_dir = Path("/root/autodl-tmp/original/autodl-tmp/vhf_agent_0511/test_data_0614")
    data_dir = (args.data_dir or default_data_dir).expanduser().resolve()
    xlsx_raw = str(args.xlsx).strip() if args.xlsx is not None else ""
    xlsx_path = Path(xlsx_raw).expanduser().resolve() if xlsx_raw else (data_dir / "标注文档.xlsx")
    audio_root = (args.audio_root or data_dir).expanduser().resolve()

    rows = build_manifest_rows(xlsx_path, audio_root, only_useful=not args.include_all)
    write_manifest(rows, args.out.expanduser().resolve())
    print(f"[ok] xlsx={xlsx_path}")
    print(f"[ok] audio_root={audio_root}")
    print(f"[ok] wrote {len(rows)} rows -> {args.out}")


if __name__ == "__main__":
    main()
