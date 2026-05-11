from __future__ import annotations

import argparse
import csv
from pathlib import Path


AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".aac", ".pcm", ".ogg"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an unlabeled ASR manifest from pre-split audio clips.")
    parser.add_argument("--audio-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    audio_dir = args.audio_dir.expanduser().resolve()
    files = sorted(
        path
        for path in audio_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["id", "audio_path", "transcript"])
        writer.writeheader()
        for index, path in enumerate(files, start=1):
            writer.writerow(
                {
                    "id": path.stem or f"clip_{index:06d}",
                    "audio_path": str(path),
                    "transcript": "",
                }
            )
    print(f"wrote {len(files)} rows to {args.output}")


if __name__ == "__main__":
    main()
