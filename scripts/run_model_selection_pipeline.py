from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


@dataclass
class ModelScore:
    model_name: str
    provider: str
    score: float
    samples: int
    language_guard_hits: int
    empty_text_hits: int
    short_text_hits: int


def load_yaml(path: Path) -> Dict[str, Any]:
    if yaml is None:
        raise RuntimeError("请先安装 pyyaml: pip install pyyaml")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: List[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run_asr_selection(config: Dict[str, Any], output_dir: Path) -> Path:
    models = ",".join(config["asr_candidates"])
    command = [
        sys.executable,
        "scripts/run_asr_model_selection.py",
        "--vad-manifest",
        str(config["manifest_csv"]),
        "--config",
        str(config["asr_candidates_config"]),
        "--models",
        models,
        "--output-dir",
        str(output_dir / "asr_selection"),
        "--limit",
        str(config.get("sample_limit", 50)),
    ]
    subprocess.run(command, check=True)
    return output_dir / "asr_selection" / "asr_selection_long.csv"


def score_asr_rows(rows: List[Dict[str, str]], weight: Dict[str, float]) -> List[ModelScore]:
    groups: Dict[Tuple[str, str], List[Dict[str, str]]] = {}
    for row in rows:
        key = (row.get("asr_model_name", ""), row.get("asr_provider", ""))
        groups.setdefault(key, []).append(row)

    scores: List[ModelScore] = []
    for (model_name, provider), items in groups.items():
        language_guard_hits = sum(1 for item in items if item.get("language_guard_flag") == "1")
        empty_hits = sum(1 for item in items if not (item.get("asr_text") or "").strip())
        short_hits = sum(1 for item in items if 0 < len((item.get("asr_text") or "").strip()) < 8)

        base = float(len(items))
        penalty = (
            language_guard_hits * float(weight.get("language_guard_penalty", 3.0))
            + empty_hits * float(weight.get("empty_text_penalty", 2.0))
            + short_hits * float(weight.get("short_text_penalty", 1.0))
        )
        score = max(0.0, base - penalty)
        scores.append(
            ModelScore(
                model_name=model_name,
                provider=provider,
                score=score,
                samples=len(items),
                language_guard_hits=language_guard_hits,
                empty_text_hits=empty_hits,
                short_text_hits=short_hits,
            )
        )
    scores.sort(key=lambda item: item.score, reverse=True)
    return scores


def compare_two_pipelines(config: Dict[str, Any]) -> Dict[str, Any]:
    compare_conf = config.get("pipeline_compare", {})
    if not compare_conf.get("enabled", False):
        return {"enabled": False}

    asr_llm_path = Path(compare_conf.get("asr_llm_csv", ""))
    mllm_path = Path(compare_conf.get("mllm_direct_csv", ""))
    if not (asr_llm_path.exists() and mllm_path.exists()):
        return {
            "enabled": True,
            "ready": False,
            "message": "未找到 asr_llm_csv 或 mllm_direct_csv，先导出两条链路结果后再比较。",
        }

    asr_rows = read_csv(asr_llm_path)
    mllm_rows = read_csv(mllm_path)
    mllm_map = {row.get("segment_id"): row for row in mllm_rows}
    key_fields = compare_conf.get("key_fields", ["primary_label", "risk_level"])

    compared = 0
    same = {field: 0 for field in key_fields}
    for row in asr_rows:
        seg = row.get("segment_id")
        if not seg or seg not in mllm_map:
            continue
        compared += 1
        target = mllm_map[seg]
        for field in key_fields:
            if (row.get(field) or "").strip() == (target.get(field) or "").strip():
                same[field] += 1

    agreement = {
        field: round((same[field] / compared) * 100, 2) if compared else 0.0
        for field in key_fields
    }
    return {
        "enabled": True,
        "ready": True,
        "compared_segments": compared,
        "agreement_percent": agreement,
        "asr_llm_rows": len(asr_rows),
        "mllm_rows": len(mllm_rows),
    }


def build_report(scores: List[ModelScore], pipeline_compare: Dict[str, Any], output_dir: Path) -> Path:
    report_path = output_dir / "model_selection_report.json"
    payload = {
        "top_asr_models": [
            {
                "rank": index + 1,
                "model_name": item.model_name,
                "provider": item.provider,
                "score": round(item.score, 3),
                "samples": item.samples,
                "language_guard_hits": item.language_guard_hits,
                "empty_text_hits": item.empty_text_hits,
                "short_text_hits": item.short_text_hits,
            }
            for index, item in enumerate(scores)
        ],
        "pipeline_compare": pipeline_compare,
    }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ASR API 选型 + asr+llm 与 mllm 直连链路比较")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/model_selection.yaml"),
        help="YAML 配置路径",
    )
    parser.add_argument(
        "--skip-asr-selection",
        action="store_true",
        help="跳过 ASR 候选调用，直接读取已有 asr_selection_long.csv",
    )
    parser.add_argument(
        "--existing-asr-long-csv",
        type=Path,
        default=Path(""),
        help="已有 asr_selection_long.csv 路径",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_yaml(args.config)
    output_dir = Path(config["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.skip_asr_selection:
        if not args.existing_asr_long_csv.exists():
            raise FileNotFoundError("skip 模式下请提供有效的 --existing-asr-long-csv")
        asr_long_csv = args.existing_asr_long_csv
    else:
        asr_long_csv = run_asr_selection(config, output_dir)

    asr_rows = read_csv(asr_long_csv)
    scores = score_asr_rows(asr_rows, config.get("evaluation", {}).get("weight", {}))
    score_rows = [
        {
            "rank": index + 1,
            "model_name": item.model_name,
            "provider": item.provider,
            "score": round(item.score, 3),
            "samples": item.samples,
            "language_guard_hits": item.language_guard_hits,
            "empty_text_hits": item.empty_text_hits,
            "short_text_hits": item.short_text_hits,
        }
        for index, item in enumerate(scores)
    ]
    write_csv(output_dir / "asr_model_ranking.csv", score_rows)

    pipeline_compare = compare_two_pipelines(config)
    report_path = build_report(scores, pipeline_compare, output_dir)

    top = scores[0] if scores else None
    if top:
        print(
            f"[DONE] Top ASR: {top.model_name} ({top.provider}) score={top.score:.3f} samples={top.samples}",
            flush=True,
        )
    print(f"[DONE] ranking: {output_dir / 'asr_model_ranking.csv'}", flush=True)
    print(f"[DONE] report: {report_path}", flush=True)


if __name__ == "__main__":
    main()
