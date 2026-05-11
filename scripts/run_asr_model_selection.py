from __future__ import annotations

import argparse
import base64
import csv
import json
import mimetypes
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.services.asr import ASRResult, FunASRAdapter, detect_unexpected_language_marks, sanitize_asr_text  # noqa: E402


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
        item["provider"] = str(item.get("provider", "funasr")).strip()
        if not item.get("name"):
            raise ValueError("ASR模型配置缺少 name。")
    return specs


def make_result_row(
    row: Dict[str, str],
    spec: Dict[str, Any],
    result: ASRResult,
    provider: str,
    error: str = "",
) -> Dict[str, object]:
    language_marks = detect_unexpected_language_marks(result.text)
    return {
        "segment_id": row["segment_id"],
        "clip_path": row["clip_path"],
        "asr_model_name": str(spec["name"]),
        "asr_provider": provider,
        "asr_model": result.engine,
        "asr_text": result.text,
        "asr_confidence": result.confidence,
        "asr_error": error,
        "language_guard_flag": "1" if language_marks else "0",
        "language_guard_notes": "|".join(language_marks),
    }


def make_error_rows(rows: List[Dict[str, str]], spec: Dict[str, Any], error: Exception) -> List[Dict[str, object]]:
    provider = str(spec.get("provider", ""))
    return [
        make_result_row(
            row=row,
            spec=spec,
            provider=provider,
            result=ASRResult(text="", confidence=0.0, engine=str(spec.get("model", ""))),
            error=f"{type(error).__name__}: {error}",
        )
        for row in rows
    ]


def audio_to_data_url(path: Path, mime_type: str = "") -> str:
    detected_mime = mime_type or mimetypes.guess_type(path.name)[0] or "audio/wav"
    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{detected_mime};base64,{encoded}"


def run_funasr_model(
    spec: Dict[str, Any],
    rows: List[Dict[str, str]],
    device: str,
    hub: str,
    batch_size_s: int,
    fail_fast: bool,
) -> List[Dict[str, object]]:
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
        try:
            result = adapter.transcribe(Path(row["clip_path"]))
            outputs.append(make_result_row(row, spec, result, provider="funasr"))
            print(f"{model_name} {index}/{len(rows)} {row['segment_id']} {result.text[:50]}", flush=True)
        except Exception as exc:
            if fail_fast:
                raise
            outputs.append(make_error_rows([row], spec, exc)[0])
            print(f"{model_name} {index}/{len(rows)} {row['segment_id']} ERROR {exc}", flush=True)
    return outputs


def run_qwen_asr_model(
    spec: Dict[str, Any],
    rows: List[Dict[str, str]],
    fail_fast: bool,
) -> List[Dict[str, object]]:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("缺少 openai SDK，请先安装：pip install openai") from exc

    api_key_env = str(spec.get("api_key_env", "DASHSCOPE_API_KEY"))
    api_key = os.getenv(api_key_env)
    if not api_key:
        raise RuntimeError(f"缺少环境变量 {api_key_env}。")

    base_url = str(spec.get("base_url") or os.getenv("DASHSCOPE_BASE_URL") or "https://dashscope.aliyuncs.com/compatible-mode/v1")
    client = OpenAI(api_key=api_key, base_url=base_url)
    model_name = str(spec["name"])
    prompt = str(spec.get("prompt", ""))
    max_file_mb = float(spec.get("max_file_mb", 10))
    outputs: List[Dict[str, object]] = []
    for index, row in enumerate(rows, start=1):
        try:
            clip_path = Path(row["clip_path"])
            file_mb = clip_path.stat().st_size / (1024 * 1024)
            if max_file_mb > 0 and file_mb > max_file_mb:
                raise RuntimeError(f"Qwen3-ASR-Flash OpenAI兼容模式建议音频小于 {max_file_mb:g}MB，当前 {file_mb:.2f}MB。")

            messages: List[Dict[str, object]] = []
            if prompt:
                messages.append({"role": "system", "content": [{"type": "text", "text": prompt}]})
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": audio_to_data_url(clip_path, str(spec.get("mime_type", ""))),
                            },
                        }
                    ],
                }
            )
            completion = client.chat.completions.create(
                model=str(spec["model"]),
                messages=messages,  # type: ignore[arg-type]
                stream=False,
                extra_body={
                    "asr_options": {
                        "language": str(spec.get("language", "zh")),
                        "enable_itn": bool(spec.get("enable_itn", True)),
                    }
                },
            )
            text = completion.choices[0].message.content or ""
            result = ASRResult(
                text=sanitize_asr_text(str(text)),
                confidence=0.0,
                engine=f"qwen_asr:{spec['model']}",
            )
            outputs.append(make_result_row(row, spec, result, provider="qwen_asr"))
            print(f"{model_name} {index}/{len(rows)} {row['segment_id']} {result.text[:50]}", flush=True)
        except Exception as exc:
            if fail_fast:
                raise
            outputs.append(make_error_rows([row], spec, exc)[0])
            print(f"{model_name} {index}/{len(rows)} {row['segment_id']} ERROR {exc}", flush=True)
    return outputs


def run_openai_audio_model(
    spec: Dict[str, Any],
    rows: List[Dict[str, str]],
    fail_fast: bool,
) -> List[Dict[str, object]]:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("缺少 openai SDK，请先安装：pip install openai") from exc

    api_key_env = str(spec.get("api_key_env", "OPENAI_API_KEY"))
    api_key = os.getenv(api_key_env)
    if not api_key:
        raise RuntimeError(f"缺少环境变量 {api_key_env}。")

    client = OpenAI(api_key=api_key)
    model_name = str(spec["name"])
    outputs: List[Dict[str, object]] = []
    for index, row in enumerate(rows, start=1):
        try:
            params: Dict[str, Any] = {"model": str(spec["model"])}
            for key in ["language", "prompt", "response_format", "temperature", "chunking_strategy"]:
                if spec.get(key) not in (None, ""):
                    params[key] = spec[key]
            with Path(row["clip_path"]).open("rb") as audio_file:
                response = client.audio.transcriptions.create(file=audio_file, **params)
            text = getattr(response, "text", "") or ""
            if not text and isinstance(response, dict):
                text = str(response.get("text", ""))
            result = ASRResult(
                text=sanitize_asr_text(str(text)),
                confidence=0.0,
                engine=f"openai_audio:{spec['model']}",
            )
            outputs.append(make_result_row(row, spec, result, provider="openai_audio"))
            print(f"{model_name} {index}/{len(rows)} {row['segment_id']} {result.text[:50]}", flush=True)
        except Exception as exc:
            if fail_fast:
                raise
            outputs.append(make_error_rows([row], spec, exc)[0])
            print(f"{model_name} {index}/{len(rows)} {row['segment_id']} ERROR {exc}", flush=True)
    return outputs


def run_gemini_audio_model(
    spec: Dict[str, Any],
    rows: List[Dict[str, str]],
    fail_fast: bool,
) -> List[Dict[str, object]]:
    try:
        from google import genai
    except ImportError as exc:
        raise RuntimeError("缺少 google-genai SDK，请先安装：pip install google-genai") from exc

    api_key_env = str(spec.get("api_key_env", "GEMINI_API_KEY"))
    api_key = os.getenv(api_key_env) or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError(f"缺少环境变量 {api_key_env} 或 GOOGLE_API_KEY。")

    client = genai.Client(api_key=api_key)
    prompt = str(
        spec.get(
            "prompt",
            "请将这段VHF海事通信音频准确转写为中文文本。只输出转写文本，不要解释。",
        )
    )
    model_name = str(spec["name"])
    outputs: List[Dict[str, object]] = []
    for index, row in enumerate(rows, start=1):
        try:
            uploaded = client.files.upload(file=str(row["clip_path"]))
            response = client.models.generate_content(
                model=str(spec["model"]),
                contents=[prompt, uploaded],
            )
            text = getattr(response, "text", "") or ""
            result = ASRResult(
                text=sanitize_asr_text(str(text)),
                confidence=0.0,
                engine=f"gemini_audio:{spec['model']}",
            )
            outputs.append(make_result_row(row, spec, result, provider="gemini_audio"))
            print(f"{model_name} {index}/{len(rows)} {row['segment_id']} {result.text[:50]}", flush=True)
        except Exception as exc:
            if fail_fast:
                raise
            outputs.append(make_error_rows([row], spec, exc)[0])
            print(f"{model_name} {index}/{len(rows)} {row['segment_id']} ERROR {exc}", flush=True)
    return outputs


def run_doubao_seed_asr_model(
    spec: Dict[str, Any],
    rows: List[Dict[str, str]],
    fail_fast: bool,
) -> List[Dict[str, object]]:
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("缺少 requests，请先安装：pip install requests") from exc

    api_key_env = str(spec.get("api_key_env", "VOLCENGINE_ASR_API_KEY"))
    api_key = os.getenv(api_key_env)
    if not api_key:
        raise RuntimeError(f"缺少环境变量 {api_key_env}。")

    endpoint = str(spec.get("endpoint", "https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash"))
    resource_id = str(spec.get("resource_id", "volc.bigasr.auc_turbo"))
    uid = str(spec.get("uid") or os.getenv("VOLCENGINE_ASR_UID") or "vhf_agent_0511")
    timeout_sec = int(spec.get("timeout_sec", 300))
    model_name = str(spec["name"])
    outputs: List[Dict[str, object]] = []
    for index, row in enumerate(rows, start=1):
        try:
            clip_path = Path(row["clip_path"])
            request_id = str(uuid.uuid4())
            headers = {
                "X-Api-Key": api_key,
                "X-Api-Resource-Id": resource_id,
                "X-Api-Request-Id": request_id,
                "X-Api-Sequence": "-1",
                "Content-Type": "application/json",
            }
            payload = {
                "user": {"uid": uid},
                "audio": {"data": base64.b64encode(clip_path.read_bytes()).decode("utf-8")},
                "request": {"model_name": str(spec.get("model_name", "bigmodel"))},
            }
            response = requests.post(endpoint, headers=headers, json=payload, timeout=timeout_sec)
            response.raise_for_status()
            data = response.json()
            text = str(data.get("result", {}).get("text", ""))
            if not text:
                raise RuntimeError(f"豆包ASR返回中没有 result.text: {str(data)[:500]}")
            result = ASRResult(
                text=sanitize_asr_text(text),
                confidence=0.0,
                engine=f"doubao_seed_asr:{resource_id}",
            )
            outputs.append(make_result_row(row, spec, result, provider="doubao_seed_asr"))
            print(f"{model_name} {index}/{len(rows)} {row['segment_id']} {result.text[:50]}", flush=True)
        except Exception as exc:
            if fail_fast:
                raise
            outputs.append(make_error_rows([row], spec, exc)[0])
            print(f"{model_name} {index}/{len(rows)} {row['segment_id']} ERROR {exc}", flush=True)
    return outputs


def read_external_results(spec: Dict[str, Any], rows: List[Dict[str, str]]) -> List[Dict[str, object]]:
    result_path_raw = str(spec.get("result_path", "")).strip()
    if not result_path_raw:
        raise ValueError(f"{spec['name']} 是 external_csv provider，但缺少 result_path。")
    result_path = Path(result_path_raw).expanduser()
    if not result_path.exists():
        raise FileNotFoundError(f"外部ASR结果不存在: {result_path}")

    external_rows = read_csv(result_path)
    by_segment: Dict[str, Dict[str, str]] = {}
    by_clip: Dict[str, Dict[str, str]] = {}
    for item in external_rows:
        if item.get("segment_id"):
            by_segment[str(item["segment_id"])] = item
        if item.get("clip_path"):
            by_clip[str(Path(item["clip_path"]).expanduser())] = item

    text_fields = ["asr_text", "text", "prediction", "transcript", "transcription"]
    confidence_fields = ["asr_confidence", "confidence", "score"]
    outputs: List[Dict[str, object]] = []
    for row in rows:
        item = by_segment.get(row["segment_id"]) or by_clip.get(str(Path(row["clip_path"]).expanduser()))
        if not item:
            outputs.append(
                make_result_row(
                    row=row,
                    spec=spec,
                    provider="external_csv",
                    result=ASRResult(text="", confidence=0.0, engine=str(spec.get("model", "external_csv"))),
                    error="external_csv 中未找到对应 segment_id/clip_path",
                )
            )
            continue

        text = next((str(item[field]) for field in text_fields if item.get(field)), "")
        confidence_raw = next((item[field] for field in confidence_fields if item.get(field)), "")
        try:
            confidence = float(confidence_raw) if confidence_raw != "" else 0.0
        except ValueError:
            confidence = 0.0
        model = item.get("asr_model") or item.get("model") or spec.get("model", "external_csv")
        outputs.append(
            make_result_row(
                row=row,
                spec=spec,
                provider="external_csv",
                result=ASRResult(
                    text=sanitize_asr_text(text),
                    confidence=confidence,
                    engine=str(model),
                ),
            )
        )
    return outputs


def run_model(
    spec: Dict[str, Any],
    rows: List[Dict[str, str]],
    device: str,
    hub: str,
    batch_size_s: int,
    fail_fast: bool,
) -> List[Dict[str, object]]:
    provider = str(spec.get("provider", "funasr"))
    if provider == "funasr":
        return run_funasr_model(spec, rows, device, hub, batch_size_s, fail_fast)
    if provider == "qwen_asr":
        return run_qwen_asr_model(spec, rows, fail_fast)
    if provider == "openai_audio":
        return run_openai_audio_model(spec, rows, fail_fast)
    if provider == "gemini_audio":
        return run_gemini_audio_model(spec, rows, fail_fast)
    if provider == "doubao_seed_asr":
        return run_doubao_seed_asr_model(spec, rows, fail_fast)
    if provider == "external_csv":
        return read_external_results(spec, rows)
    raise ValueError(f"不支持的ASR provider: {provider} ({spec.get('name')})")


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
        grouped[segment_id][f"asr_error__{model_name}"] = item.get("asr_error", "")
        grouped[segment_id][f"language_guard__{model_name}"] = item.get("language_guard_notes", "")
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
    parser.add_argument("--fail-fast", action="store_true", help="遇到单个模型/样本错误时立即退出。默认记录错误并继续。")
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
        try:
            long_rows.extend(run_model(spec, rows, args.device, args.hub, args.batch_size_s, args.fail_fast))
        except Exception as exc:
            if args.fail_fast:
                raise
            print(f"{spec['name']} MODEL_ERROR {exc}", flush=True)
            long_rows.extend(make_error_rows(rows, spec, exc))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    long_path = args.output_dir / "asr_selection_long.csv"
    wide_path = args.output_dir / "asr_selection_wide.csv"
    write_csv(long_path, long_rows)
    write_csv(wide_path, build_wide_rows(rows, long_rows))
    print(f"wrote long results -> {long_path}")
    print(f"wrote wide results -> {wide_path}")


if __name__ == "__main__":
    main()
