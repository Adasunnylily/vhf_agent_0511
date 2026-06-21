#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class AudioItem:
    path: Path
    category_code: str
    category_desc: str
    filename: str


def parse_category(folder_name: str) -> tuple[str, str]:
    match = re.match(r"^(.+?)（(.+)）$", folder_name)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return folder_name.strip(), ""


def probe_duration_seconds(path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return float(result.stdout.strip())


def collect_items(input_dir: Path) -> list[AudioItem]:
    items: list[AudioItem] = []
    for category_dir in sorted(input_dir.iterdir()):
        if not category_dir.is_dir():
            continue
        code, desc = parse_category(category_dir.name)
        for path in sorted(category_dir.glob("*.wav")):
            items.append(
                AudioItem(
                    path=path,
                    category_code=code,
                    category_desc=desc,
                    filename=path.name,
                )
            )
    return items


def write_markdown(
    manifest_path: Path,
    rows: list[dict[str, object]],
    output_wav: Path,
    seed: int,
    gap_ms: int,
) -> None:
    lines = [
        "# 音频分类打乱拼接标签文档",
        "",
        f"- 生成时间: {datetime.now(timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M:%S %z')}",
        f"- 输出音频: `{output_wav.name}`",
        f"- 片段总数: {len(rows)}",
        f"- 随机种子: `{seed}`",
        f"- 业务间静默: `{gap_ms} ms`",
        "",
        "## 片段顺序",
        "",
        "| 序号 | 开始(s) | 结束(s) | 时长(s) | 分类代码 | 分类说明 | 原文件名 |",
        "| --- | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| {index} | {start:.3f} | {end:.3f} | {duration:.3f} | {category_code} | {category_desc} | {filename} |".format(
                **row
            )
        )
    lines.extend(
        [
            "",
            "## 分类统计",
            "",
        ]
    )
    counts: dict[str, int] = {}
    for row in rows:
        counts[str(row["category_code"])] = counts.get(str(row["category_code"]), 0) + 1
    for code in sorted(counts):
        lines.append(f"- `{code}`: {counts[code]} 条")
    manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Shuffle classified wav files and concatenate them.")
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("test_data_0614/音频分类"),
        help="Directory containing category subfolders with wav files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("test_data_0614/音频分类_打乱拼接"),
        help="Directory for concatenated audio and label documents.",
    )
    parser.add_argument("--seed", type=int, default=20260616, help="Random seed for reproducible shuffle.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum number of files; 0 means all files.")
    parser.add_argument("--gap-ms", type=int, default=0, help="Silence inserted between business events.")
    args = parser.parse_args()

    input_dir = args.input_dir.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    items = collect_items(input_dir)
    if not items:
        raise SystemExit(f"No wav files found under {input_dir}")

    rng = random.Random(args.seed)
    shuffled = items[:]
    rng.shuffle(shuffled)
    if args.limit > 0:
        shuffled = shuffled[: args.limit]

    output_wav = output_dir / "shuffled_concat.wav"
    csv_path = output_dir / "shuffled_concat_labels.csv"
    md_path = output_dir / "shuffled_concat_labels.md"
    json_path = output_dir / "shuffled_concat_manifest.json"

    rows: list[dict[str, object]] = []
    cursor = 0.0
    gap_seconds = max(0, args.gap_ms) / 1000.0
    for index, item in enumerate(shuffled, start=1):
        if index > 1:
            cursor += gap_seconds
        duration = probe_duration_seconds(item.path)
        rows.append(
            {
                "index": index,
                "start_sec": round(cursor, 3),
                "end_sec": round(cursor + duration, 3),
                "duration_sec": round(duration, 3),
                "category_code": item.category_code,
                "category_desc": item.category_desc,
                "filename": item.filename,
                "source_path": str(item.path.relative_to(input_dir.parent)),
            }
        )
        cursor += duration

    with tempfile.TemporaryDirectory() as tmp_dir:
        temp_root = Path(tmp_dir)
        concat_list = temp_root / "concat.txt"
        silence_path = temp_root / "event_gap.wav"
        if gap_seconds > 0:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-f", "lavfi",
                    "-i", "anullsrc=channel_layout=mono:sample_rate=8000",
                    "-t", f"{gap_seconds:.3f}", "-c:a", "pcm_alaw", str(silence_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        with concat_list.open("w", encoding="utf-8") as handle:
            for index, item in enumerate(shuffled):
                if index > 0 and gap_seconds > 0:
                    handle.write(f"file '{silence_path}'\n")
                escaped = str(item.path).replace("'", "'\\''")
                handle.write(f"file '{escaped}'\n")

        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
                "-c", "copy", str(output_wav),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "index",
                "start_sec",
                "end_sec",
                "duration_sec",
                "category_code",
                "category_desc",
                "filename",
                "source_path",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    markdown_rows = [
        {
            "index": row["index"],
            "start": row["start_sec"],
            "end": row["end_sec"],
            "duration": row["duration_sec"],
            "category_code": row["category_code"],
            "category_desc": row["category_desc"],
            "filename": row["filename"],
        }
        for row in rows
    ]
    write_markdown(md_path, markdown_rows, output_wav, args.seed, max(0, args.gap_ms))

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_dir": str(input_dir),
        "output_wav": str(output_wav),
        "seed": args.seed,
        "gap_ms": max(0, args.gap_ms),
        "segment_count": len(rows),
        "total_duration_sec": round(cursor, 3),
        "segments": rows,
    }
    json_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Input dir: {input_dir}")
    print(f"Segments: {len(rows)}")
    print(f"Total duration: {cursor:.3f}s")
    print(f"Output wav: {output_wav}")
    print(f"Labels csv: {csv_path}")
    print(f"Labels md:  {md_path}")
    print(f"Manifest:   {json_path}")


if __name__ == "__main__":
    main()
