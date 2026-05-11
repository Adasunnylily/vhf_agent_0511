from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


@dataclass(frozen=True)
class EvalItem:
    audio_path: Path
    transcript: str
    item_id: str


@dataclass(frozen=True)
class ModelSpec:
    name: str
    model: str
    vad_model: str = ""
    punc_model: str = ""
    language: str = "auto"
    provider: str = "funasr"


def normalize_text(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[\s,，.。:：;；!?！？、\"'“”‘’（）()\[\]【】{}<>《》\-_/\\|~`^]+", "", text)
    text = re.sub(r"频道", "ch", text)
    text = re.sub(r"幺", "一", text)
    text = re.sub(r"两", "二", text)
    return text


def edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (0 if ca == cb else 1),
                )
            )
        previous = current
    return previous[-1]


def cer(reference: str, hypothesis: str) -> float:
    ref = normalize_text(reference)
    hyp = normalize_text(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    return edit_distance(ref, hyp) / len(ref)


def read_manifest(path: Path, audio_dir: Optional[Path]) -> List[EvalItem]:
    if path.suffix.lower() == ".jsonl":
        return list(read_jsonl_manifest(path, audio_dir))
    return list(read_csv_manifest(path, audio_dir))


def read_jsonl_manifest(path: Path, audio_dir: Optional[Path]) -> Iterable[EvalItem]:
    with path.open("r", encoding="utf-8") as file:
        for index, line in enumerate(file, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            yield item_from_mapping(row, index, audio_dir)


def read_csv_manifest(path: Path, audio_dir: Optional[Path]) -> Iterable[EvalItem]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        for index, row in enumerate(csv.DictReader(file), start=1):
            yield item_from_mapping(row, index, audio_dir)


def item_from_mapping(row: Dict[str, Any], index: int, audio_dir: Optional[Path]) -> EvalItem:
    audio_value = row.get("audio_path") or row.get("path") or row.get("file") or row.get("audio")
    if not audio_value:
        raise ValueError(f"manifest 第 {index} 行缺少 audio_path/path/file/audio 字段")

    transcript = str(row.get("transcript") or row.get("text") or row.get("ground_truth") or "").strip()
    audio_path = Path(str(audio_value)).expanduser()
    if not audio_path.is_absolute() and audio_dir is not None:
        audio_path = audio_dir / audio_path

    return EvalItem(
        audio_path=audio_path,
        transcript=transcript,
        item_id=str(row.get("id") or row.get("utt_id") or audio_path.stem or index),
    )


def load_model_specs(config_path: Path, selected_names: Optional[List[str]]) -> List[ModelSpec]:
    data = json.loads(config_path.read_text(encoding="utf-8"))
    specs = [
        ModelSpec(
            name=str(item["name"]),
            provider=str(item.get("provider", "funasr")),
            model=str(item["model"]),
            vad_model=str(item.get("vad_model", "")),
            punc_model=str(item.get("punc_model", "")),
            language=str(item.get("language", "auto")),
        )
        for item in data.get("models", [])
    ]
    if selected_names:
        selected = set(selected_names)
        specs = [spec for spec in specs if spec.name in selected]
    if not specs:
        raise ValueError("没有可评测的模型，请检查 --models 或配置文件")
    return specs


class FunASRRunner:
    def __init__(self, spec: ModelSpec, device: str, hub: str, batch_size_s: int, use_itn: bool) -> None:
        try:
            from funasr import AutoModel
        except ImportError as exc:
            raise RuntimeError("未安装 funasr，请先在 AutoDL 执行 requirements-server.txt 安装。") from exc

        kwargs: Dict[str, Any] = {
            "model": spec.model,
            "device": device,
            "hub": hub,
            "disable_update": True,
        }
        if spec.vad_model:
            kwargs["vad_model"] = spec.vad_model
            kwargs["vad_kwargs"] = {"max_single_segment_time": 30000}
        if spec.punc_model:
            kwargs["punc_model"] = spec.punc_model

        self.spec = spec
        self.batch_size_s = batch_size_s
        self.use_itn = use_itn
        self.model = AutoModel(**kwargs)

    def transcribe(self, audio_path: Path) -> str:
        result = self.model.generate(
            input=str(audio_path),
            batch_size_s=self.batch_size_s,
            language=self.spec.language,
            use_itn=self.use_itn,
        )
        if isinstance(result, list) and result and isinstance(result[0], dict):
            return str(result[0].get("text", "")).strip()
        if isinstance(result, dict):
            return str(result.get("text", "")).strip()
        return ""


def evaluate_model(
    spec: ModelSpec,
    items: List[EvalItem],
    output_dir: Path,
    device: str,
    hub: str,
    batch_size_s: int,
    use_itn: bool,
) -> Dict[str, Any]:
    if spec.provider != "funasr":
        raise ValueError(f"暂不支持 provider={spec.provider}")

    runner = FunASRRunner(spec, device=device, hub=hub, batch_size_s=batch_size_s, use_itn=use_itn)
    rows: List[Dict[str, Any]] = []
    errors: List[float] = []
    started = time.time()

    for index, item in enumerate(items, start=1):
        if not item.audio_path.exists():
            raise FileNotFoundError(f"音频不存在: {item.audio_path}")
        prediction = runner.transcribe(item.audio_path)
        item_cer = cer(item.transcript, prediction) if item.transcript else None
        if item_cer is not None:
            errors.append(item_cer)
        rows.append(
            {
                "index": index,
                "id": item.item_id,
                "audio_path": str(item.audio_path),
                "reference": item.transcript,
                "prediction": prediction,
                "cer": "" if item_cer is None else f"{item_cer:.6f}",
                "accuracy": "" if item_cer is None else f"{max(0.0, 1.0 - item_cer):.6f}",
            }
        )
        print(f"[{spec.name}] {index}/{len(items)} cer={'' if item_cer is None else round(item_cer, 4)} {item.audio_path.name}", flush=True)

    output_dir.mkdir(parents=True, exist_ok=True)
    detail_path = output_dir / f"{spec.name}_details.csv"
    with detail_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["index", "id", "audio_path", "reference", "prediction", "cer", "accuracy"],
        )
        writer.writeheader()
        writer.writerows(rows)

    avg_cer = statistics.mean(errors) if errors else None
    p50_cer = statistics.median(errors) if errors else None
    passed_count = sum(1 for value in errors if (1.0 - value) >= 0.8)
    return {
        "name": spec.name,
        "model": spec.model,
        "items": len(items),
        "scored_items": len(errors),
        "avg_cer": avg_cer,
        "avg_accuracy": None if avg_cer is None else max(0.0, 1.0 - avg_cer),
        "p50_cer": p50_cer,
        "pass_rate_at_80": None if not errors else passed_count / len(errors),
        "detail_csv": str(detail_path),
        "elapsed_sec": round(time.time() - started, 3),
    }


def write_summary(output_dir: Path, summaries: List[Dict[str, Any]]) -> None:
    ranked = sorted(
        summaries,
        key=lambda item: -1.0 if item["avg_accuracy"] is None else float(item["avg_accuracy"]),
        reverse=True,
    )
    summary_path = output_dir / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "target_accuracy": 0.8,
                "ranked": ranked,
                "qualified_models": [
                    item for item in ranked if item["avg_accuracy"] is not None and item["avg_accuracy"] >= 0.8
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    csv_path = output_dir / "summary.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "name",
                "model",
                "items",
                "scored_items",
                "avg_cer",
                "avg_accuracy",
                "p50_cer",
                "pass_rate_at_80",
                "detail_csv",
                "elapsed_sec",
            ],
        )
        writer.writeheader()
        writer.writerows(ranked)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate ASR models on pre-split VHF speech clips.")
    parser.add_argument("--manifest", required=True, type=Path, help="CSV/JSONL, fields: audio_path, transcript")
    parser.add_argument("--audio-dir", type=Path, default=None, help="Base dir for relative audio paths")
    parser.add_argument("--config", type=Path, default=Path("configs/asr_models_0511.json"))
    parser.add_argument("--models", default="", help="Comma-separated model names from config")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/asr_eval_0511"))
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--hub", default="ms")
    parser.add_argument("--batch-size-s", type=int, default=30)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--no-itn", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    selected = [item.strip() for item in args.models.split(",") if item.strip()] or None
    items = read_manifest(args.manifest, args.audio_dir)
    if args.limit > 0:
        items = items[: args.limit]
    if not items:
        raise ValueError("manifest 中没有可评测样本")

    specs = load_model_specs(args.config, selected)
    summaries = [
        evaluate_model(
            spec,
            items,
            output_dir=args.output_dir,
            device=args.device,
            hub=args.hub,
            batch_size_s=args.batch_size_s,
            use_itn=not args.no_itn,
        )
        for spec in specs
    ]
    write_summary(args.output_dir, summaries)
    print(json.dumps({"output_dir": str(args.output_dir), "summaries": summaries}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
