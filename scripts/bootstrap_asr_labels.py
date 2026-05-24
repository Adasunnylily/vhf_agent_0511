from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.asr import QwenASRAdapter, sanitize_asr_text


def list_audio_files(audio_dir: Path) -> List[Path]:
    patterns = ("*.wav", "*.mp3", "*.m4a", "*.flac", "*.aac", "*.webm", "*.ogg")
    files: List[Path] = []
    for p in patterns:
        files.extend(audio_dir.rglob(p))
    files = sorted(set(files))
    return files


def rule_label(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["mayday", "求救", "起火", "失火", "着火", "冒烟", "碰撞", "搁浅", "失控"]):
        return "emergency_risk"
    if any(k in t for k in ["离泊", "出港", "开航", "申请", "请求"]):
        return "departure_request"
    if any(k in t for k in ["靠泊", "靠港", "抛锚", "锚泊", "已靠妥", "报告线", "码头"]):
        return "routine_report"
    if len(text.strip()) < 3:
        return "invalid_or_noise"
    return "other_business"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run strong ASR API first, export CSV for human correction.")
    parser.add_argument("--audio-dir", required=True, type=Path, help="目录下递归扫描音频")
    parser.add_argument("--out", required=True, type=Path, help="输出csv")
    parser.add_argument("--limit", type=int, default=0, help="仅处理前N条，0表示全部")
    parser.add_argument("--model", default="qwen3-asr-flash")
    parser.add_argument("--api-key-env", default="DASHSCOPE_API_KEY")
    parser.add_argument("--base-url", default="https://dashscope.aliyuncs.com/compatible-mode/v1")
    args = parser.parse_args()

    files = list_audio_files(args.audio_dir)
    if args.limit > 0:
        files = files[: args.limit]
    if not files:
        raise RuntimeError("未找到音频文件。")

    adapter = QwenASRAdapter(
        model=args.model,
        api_key_env=args.api_key_env,
        base_url=args.base_url,
        timeout_s=180,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "sample_id",
                "audio_path",
                "asr_text_auto",
                "primary_label_auto",
                "primary_label_gt",
                "transcript_gt",
                "ship_entities_gt",
                "location_entities_gt",
                "review_status",
                "review_notes",
            ],
        )
        writer.writeheader()
        for i, audio in enumerate(files, start=1):
            result = adapter.transcribe(audio)
            text = sanitize_asr_text(result.text or "")
            sample_id = audio.stem
            writer.writerow(
                {
                    "sample_id": sample_id,
                    "audio_path": str(audio),
                    "asr_text_auto": text,
                    "primary_label_auto": rule_label(text),
                    "primary_label_gt": "",
                    "transcript_gt": "",
                    "ship_entities_gt": "",
                    "location_entities_gt": "",
                    "review_status": "todo",
                    "review_notes": "",
                }
            )
            print(f"[{i}/{len(files)}] {sample_id}")

    print(f"[ok] wrote: {args.out}")


if __name__ == "__main__":
    main()
