#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Iterable, List


AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".aac", ".ogg", ".webm"}
DEFAULT_MODELS = [
    "paraformer-v2",
    "qwen-asr-flash",
    "qwen-asr-pro",
    "doubao-seed-asr",
    "local-funasr",
]


def iter_audio_files(audio_dir: Path, limit: int) -> Iterable[Path]:
    files = sorted(
        path
        for path in audio_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
    )
    return files[:limit] if limit > 0 else files


def parse_models(raw: str) -> List[str]:
    models = [item.strip() for item in raw.split(",") if item.strip()]
    return models or DEFAULT_MODELS


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a manual ASR model comparison annotation sheet.")
    parser.add_argument("--audio-dir", required=True, type=Path, help="Audio directory to sample from")
    parser.add_argument("--out", default="data/eval/asr_comparison_for_review.csv", type=Path)
    parser.add_argument("--limit", default=20, type=int, help="Number of audio files to include; <=0 means all")
    parser.add_argument(
        "--models",
        default=",".join(DEFAULT_MODELS),
        help="Comma-separated model names",
    )
    args = parser.parse_args()

    audio_dir = args.audio_dir.expanduser().resolve()
    models = parse_models(args.models)
    rows = []
    for audio_path in iter_audio_files(audio_dir, args.limit):
        audio_id = audio_path.stem
        for model in models:
            rows.append(
                {
                    "audio_id": audio_id,
                    "audio_path": str(audio_path),
                    "模型": model,
                    "语音": "",
                    "业务类型": "",
                    "船名": "",
                    "地名": "",
                    "相应时间": "",
                    "是否可用": "",
                    "错误类型": "",
                    "备注": "",
                }
            )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "audio_id",
                "audio_path",
                "模型",
                "语音",
                "业务类型",
                "船名",
                "地名",
                "相应时间",
                "是否可用",
                "错误类型",
                "备注",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"wrote {len(rows)} rows for {len(rows) // max(1, len(models))} audio files -> {args.out}")


if __name__ == "__main__":
    main()
