from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import List


def list_audio_files(audio_dir: Path) -> List[Path]:
    patterns = ("*.wav", "*.mp3", "*.m4a", "*.flac", "*.aac", "*.webm", "*.ogg")
    files: List[Path] = []
    for p in patterns:
        files.extend(audio_dir.rglob(p))
    files = sorted(set(files))
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description="Build annotation template for streaming performance measurement.")
    parser.add_argument("--audio-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    files = list_audio_files(args.audio_dir)
    if args.limit > 0:
        files = files[: args.limit]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "sample_id",
                "audio_path",
                "channel_id",
                "run_mode",
                "model_name",
                "audio_duration_ms",
                "speech_start_gt_ms",
                "speech_end_gt_ms",
                "first_business_cue_gt_ms",
                "first_risk_cue_gt_ms",
                "primary_label_gt",
                "risk_level_gt",
                "key_transcript_gt",
                "start_ts",
                "first_text_ts",
                "final_ts",
                "ttft_ms",
                "final_latency_ms",
                "risk_trigger_ts",
                "risk_delay_ms",
                "first_text_correct",
                "risk_trigger_correct",
                "http_ok",
                "ws_ok",
                "error_type",
                "audio_quality_gt",
                "overlap_gt",
                "urgent_prosody_gt",
                "notes",
            ],
        )
        writer.writeheader()
        for audio in files:
            writer.writerow(
                {
                    "sample_id": audio.stem,
                    "audio_path": str(audio),
                    "channel_id": "vhf_demo_01",
                    "run_mode": "stream_rt",
                    "model_name": "",
                    "audio_duration_ms": "",
                    "speech_start_gt_ms": "",
                    "speech_end_gt_ms": "",
                    "first_business_cue_gt_ms": "",
                    "first_risk_cue_gt_ms": "",
                    "primary_label_gt": "",
                    "risk_level_gt": "",
                    "key_transcript_gt": "",
                    "start_ts": "",
                    "first_text_ts": "",
                    "final_ts": "",
                    "ttft_ms": "",
                    "final_latency_ms": "",
                    "risk_trigger_ts": "",
                    "risk_delay_ms": "",
                    "first_text_correct": "",
                    "risk_trigger_correct": "",
                    "http_ok": "",
                    "ws_ok": "",
                    "error_type": "",
                    "audio_quality_gt": "",
                    "overlap_gt": "",
                    "urgent_prosody_gt": "",
                    "notes": "",
                }
            )
    print(f"[ok] wrote: {args.out} ({len(files)} rows)")


if __name__ == "__main__":
    main()
