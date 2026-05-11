from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.services.asr import FunASRAdapter  # noqa: E402


def read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: List[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def load_model_specs(config: Path, model_names: Optional[List[str]]) -> List[Dict[str, Any]]:
    data = json.loads(config.read_text(encoding="utf-8"))
    specs = data.get("models", [])
    if model_names:
        keep = set(model_names)
        specs = [item for item in specs if item.get("name") in keep]
    if not specs:
        raise ValueError("没有匹配到ASR模型，请检查 --models 或配置文件。")
    for item in specs:
        if item.get("provider", "funasr") != "funasr":
            raise ValueError(f"当前脚本只直接支持 FunASR 本地模型: {item.get('name')}")
    return specs


def run_model(spec: Dict[str, Any], rows: List[Dict[str, str]], device: str, hub: str, batch_size_s: int) -> List[Dict[str, object]]:
    adapter = FunASRAdapter(
        model=str(spec["model"]),
        vad_model=str(spec.get("vad_model", "")),
        punc_model=str(spec.get("punc_model", "")),
        device=device,
        hub=hub,
        language=str(spec.get("language", "auto")),
        batch_size_s=batch_size_s,
    )
    model_name = str(spec["name"])
    outputs: List[Dict[str, object]] = []
    for index, row in enumerate(rows, start=1):
        result = adapter.transcribe(Path(row["clip_path"]))
        outputs.append(
            {
                "segment_id": row["segment_id"],
                "clip_path": row["clip_path"],
                "asr_model_name": model_name,
                "asr_model": result.engine,
                "asr_text": result.text,
                "asr_confidence": result.confidence,
            }
        )
        print(f"{model_name} {index}/{len(rows)} {row['segment_id']} {result.text[:50]}", flush=True)
    return outputs


def build_wide_rows(base_rows: List[Dict[str, str]], long_rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    grouped: Dict[str, Dict[str, object]] = {
        row["segment_id"]: {
            "segment_id": row["segment_id"],
            "clip_path": row["clip_path"],
            "start_ms": row.get("start_ms", ""),
            "end_ms": row.get("end_ms", ""),
            "duration_ms": row.get("duration_ms", ""),
            "source_audio_path": row.get("source_audio_path", ""),
        }
        for row in base_rows
    }
    for item in long_rows:
        segment_id = str(item["segment_id"])
        model_name = str(item["asr_model_name"])
        grouped.setdefault(segment_id, {"segment_id": segment_id, "clip_path": item.get("clip_path", "")})
        grouped[segment_id][f"asr_text__{model_name}"] = item.get("asr_text", "")
        grouped[segment_id][f"asr_confidence__{model_name}"] = item.get("asr_confidence", "")
    return list(grouped.values())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run multiple ASR models on VAD clips for human model selection.")
    parser.add_argument("--vad-manifest", required=True, type=Path)
    parser.add_argument("--config", type=Path, default=Path("configs/asr_models_0511.json"))
    parser.add_argument("--models", default="", help="Comma-separated model names. Empty means all models in config.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--hub", default="ms")
    parser.add_argument("--batch-size-s", type=int, default=30)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model_names = [item.strip() for item in args.models.split(",") if item.strip()] or None
    specs = load_model_specs(args.config, model_names)
    rows = read_csv(args.vad_manifest)
    if args.limit > 0:
        rows = rows[: args.limit]
    if not rows:
        raise ValueError("vad manifest 没有可转写样本。")

    long_rows: List[Dict[str, object]] = []
    for spec in specs:
        long_rows.extend(run_model(spec, rows, args.device, args.hub, args.batch_size_s))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    long_path = args.output_dir / "asr_selection_long.csv"
    wide_path = args.output_dir / "asr_selection_wide.csv"
    write_csv(long_path, long_rows)
    write_csv(wide_path, build_wide_rows(rows, long_rows))
    print(f"wrote long results -> {long_path}")
    print(f"wrote wide results -> {wide_path}")


if __name__ == "__main__":
    main()
