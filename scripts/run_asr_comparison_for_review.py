#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


load_env(REPO_ROOT / ".env")
if os.getenv("VHF_DATA_DIR", "").startswith("/root/") and not Path("/root").exists():
    os.environ["VHF_DATA_DIR"] = str(REPO_ROOT / "data")

from app.config import settings  # noqa: E402
from app.domain.models import AudioSegment  # noqa: E402
from app.services.asr import (  # noqa: E402
    ASRResult,
    DashScopeParaformerASRAdapter,
    FunASRAdapter,
    QwenASRAdapter,
    sanitize_asr_text,
)
from app.services.entity_resolver import EntityResolver  # noqa: E402
from app.services.preprocess import AudioPreprocessor  # noqa: E402
from app.services.risk_engine import KeywordRiskEngine  # noqa: E402
from app.services.storage import LocalStorage  # noqa: E402
from app.services.vhf_dialogue import postprocess_vhf_dialogue  # noqa: E402


AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".aac", ".ogg", ".webm"}
UPLOAD_RECORDING_MODELS = [
    "volc-bigasr-auc-turbo",
    "qwen-asr-flash",
]
STREAMING_MODELS = [
    "volc-sauc-duration",
    "s2s-omni",
    "qwen-asr-flash",
    "local-funasr",
    "paraformer-realtime-v2",
    "sensevoice-realtime-v1",
    "paraformer-realtime-8k-v2",
]
DEFAULT_MODELS = UPLOAD_RECORDING_MODELS
MODEL_ALIASES = {
    "volc.bigasr.auc_turbo": "volc-bigasr-auc-turbo",
    "volc.seedasr.auc": "volc-bigasr-auc-turbo",
    "doubao-seed-asr": "volc-bigasr-auc-turbo",
    "doubao_seed_asr_flash": "volc-bigasr-auc-turbo",
    "volc.seedasr.sauc.duration": "volc-sauc-duration",
    "fun-asr": "local-funasr",
    "funasr": "local-funasr",
}
MODEL_ENDPOINTS = {
    "volc-bigasr-auc-turbo": "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit",
    "volc-sauc-duration": "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel",
    "s2s-omni": "streaming/s2s-omni",
    "qwen-asr-flash": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "qwen-asr-pro": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "local-funasr": "local",
    "paraformer-v2": "dashscope Recognition",
    "paraformer-realtime-v2": "dashscope realtime/file replay",
    "paraformer-realtime-8k-v2": "dashscope realtime/file replay",
    "sensevoice-realtime-v1": "dashscope realtime/file replay",
}
MODEL_RESOURCES = {
    "volc-bigasr-auc-turbo": "volc.seedasr.auc",
    "volc-sauc-duration": "volc.seedasr.sauc.duration",
}


def iter_audio_files(audio_dir: Path, limit: int) -> List[Path]:
    files = sorted(
        path
        for path in audio_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
    )
    if limit == 0:
        return []
    return files[:limit] if limit > 0 else files


def normalize_model_name(model_name: str) -> str:
    key = model_name.strip()
    return MODEL_ALIASES.get(key, key)


def default_models_for_task(task: str) -> List[str]:
    if task == "upload":
        return UPLOAD_RECORDING_MODELS
    if task == "streaming":
        return STREAMING_MODELS
    return list(dict.fromkeys([*UPLOAD_RECORDING_MODELS, *STREAMING_MODELS]))


def parse_models(raw: str, task: str) -> List[str]:
    if not raw.strip():
        return default_models_for_task(task)
    models = [item.strip() for item in raw.split(",") if item.strip()]
    return [normalize_model_name(model) for model in models] or default_models_for_task(task)


def model_task(model_name: str, requested_task: str) -> str:
    if requested_task in {"upload", "streaming"}:
        return requested_task
    if model_name in STREAMING_MODELS and model_name not in UPLOAD_RECORDING_MODELS:
        return "streaming"
    return "upload"


def model_endpoint(model_name: str) -> str:
    if model_name == "volc-bigasr-auc-turbo":
        return os.getenv("VOLCENGINE_FILE_ASR_ENDPOINT", MODEL_ENDPOINTS[model_name])
    return MODEL_ENDPOINTS.get(model_name, "")


def model_resource_id(model_name: str) -> str:
    if model_name == "volc-bigasr-auc-turbo":
        return os.getenv("VOLCENGINE_FILE_ASR_RESOURCE_ID", MODEL_RESOURCES[model_name])
    if model_name == "volc-sauc-duration":
        return os.getenv("VOLCENGINE_STREAM_ASR_RESOURCE_ID", MODEL_RESOURCES[model_name])
    return MODEL_RESOURCES.get(model_name, "")


def make_adapter(model_name: str) -> Any:
    if model_name in {
        "paraformer-v2",
        "paraformer-realtime-v2",
        "paraformer-realtime-8k-v2",
        "sensevoice-realtime-v1",
    }:
        hotwords_path = Path("data/hotwords/nbzh_hotwords.txt")
        return DashScopeParaformerASRAdapter(
            model=model_name,
            api_key_env=settings.dashscope_asr_api_key_env,
            diarization_enabled=True,
            speaker_count=2,
            phrase_id=settings.asr_phrase_id,
            vocabulary_id=settings.asr_vocabulary_id,
            hotwords_path=hotwords_path if hotwords_path.exists() else None,
        )
    if model_name == "qwen-asr-flash":
        return QwenASRAdapter(
            model="qwen3-asr-flash",
            api_key_env=settings.qwen_asr_api_key_env,
            base_url=settings.qwen_asr_base_url,
            timeout_s=settings.qwen_asr_timeout_s,
            prompt=settings.qwen_asr_prompt,
        )
    if model_name == "qwen-asr-pro":
        return QwenASRAdapter(
            model="qwen3-asr-pro",
            api_key_env=settings.qwen_asr_api_key_env,
            base_url=settings.qwen_asr_base_url,
            timeout_s=settings.qwen_asr_timeout_s,
            prompt=settings.qwen_asr_prompt,
        )
    if model_name == "local-funasr":
        return FunASRAdapter(
            model=os.getenv("VHF_LOCAL_FUNASR_MODEL", "iic/SenseVoiceSmall"),
            vad_model=settings.asr_vad_model,
            punc_model=settings.asr_punc_model,
            device=os.getenv("VHF_LOCAL_FUNASR_DEVICE", settings.asr_device),
            hub=settings.asr_hub,
            batch_size_s=settings.asr_batch_size_s,
            language=settings.asr_language,
            use_itn=settings.asr_use_itn,
            vad_max_single_segment_time=settings.asr_vad_max_single_segment_time,
        )
    if model_name == "volc-bigasr-auc-turbo":
        return "volc-file-asr"
    if model_name in {"volc-sauc-duration", "s2s-omni"}:
        return "streaming-ws-candidate"
    raise ValueError(f"未知模型: {model_name}")


def run_volc_file_asr(audio_path: Path, model_name: str) -> ASRResult:
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("缺少 requests，请先安装: pip install requests") from exc

    endpoint = model_endpoint(model_name)
    resource_id = model_resource_id(model_name)
    app_key = os.getenv("VOLCENGINE_ASR_APP_KEY", "")
    access_key = os.getenv("VOLCENGINE_ASR_ACCESS_KEY", "")
    api_key = os.getenv("VOLCENGINE_ASR_API_KEY", "")
    if app_key and access_key:
        headers = {
            "X-Api-App-Key": app_key,
            "X-Api-Access-Key": access_key,
            "X-Api-Resource-Id": resource_id,
            "X-Api-Request-Id": str(uuid.uuid4()),
            "X-Api-Sequence": "-1",
            "Content-Type": "application/json",
        }
        uid = app_key
    elif api_key:
        headers = {
            "X-Api-Key": api_key,
            "X-Api-Resource-Id": resource_id,
            "X-Api-Request-Id": str(uuid.uuid4()),
            "X-Api-Sequence": "-1",
            "Content-Type": "application/json",
        }
        uid = os.getenv("VOLCENGINE_ASR_UID", "vhf_agent_0511")
    else:
        raise RuntimeError("缺少 VOLCENGINE_ASR_APP_KEY/VOLCENGINE_ASR_ACCESS_KEY 或 VOLCENGINE_ASR_API_KEY")

    payload = {
        "user": {"uid": uid},
        "audio": {"data": base64.b64encode(audio_path.read_bytes()).decode("utf-8")},
        "request": {"model_name": os.getenv("VOLCENGINE_ASR_MODEL_NAME", "bigmodel")},
    }
    response = requests.post(endpoint, headers=headers, json=payload, timeout=300)
    response.raise_for_status()
    data = response.json()
    text = extract_doubao_text(data)
    if not text:
        status_code = response.headers.get("X-Api-Status-Code", "")
        message = response.headers.get("X-Api-Message", "")
        task_id = extract_volc_task_id(data)
        if task_id:
            raise RuntimeError(
                "火山录音文件已提交但未直接返回文本；"
                f"task_id={task_id}。如控制台为异步submit接口，需要补充查询接口或改用同步recognize接口。"
            )
        raise RuntimeError(f"火山ASR未返回文本 status={status_code} message={message} body={str(data)[:300]}")
    return ASRResult(text=sanitize_asr_text(text), confidence=0.0, engine=f"doubao_seed_asr:{resource_id}")


def extract_doubao_text(data: Dict[str, Any]) -> str:
    result = data.get("result")
    if isinstance(result, dict):
        if result.get("text"):
            return str(result["text"])
        utterances = result.get("utterances")
        if isinstance(utterances, list):
            return "".join(str(item.get("text") or "") for item in utterances if isinstance(item, dict))
    if data.get("text"):
        return str(data["text"])
    return ""


def extract_volc_task_id(data: Dict[str, Any]) -> str:
    for key in ("task_id", "id"):
        if data.get(key):
            return str(data[key])
    result = data.get("result")
    if isinstance(result, dict):
        for key in ("task_id", "id"):
            if result.get(key):
                return str(result[key])
    return ""


def streaming_candidate_error(model_name: str) -> RuntimeError:
    endpoint = model_endpoint(model_name)
    if model_name == "volc-sauc-duration":
        return RuntimeError(
            "TRUE_STREAMING_WS_NOT_IMPLEMENTED: "
            f"{model_name} 需要 WebSocket 实时音频帧评测，接口 {endpoint}。"
            "当前脚本只负责生成可标注对比表；请用后续 ws runner 测 TTFT/最终时延。"
        )
    return RuntimeError(
        "TRUE_STREAMING_NOT_IMPLEMENTED: "
        f"{model_name} 需要单独的实时双向会话评测；当前离线CSV脚本不模拟该协议。"
    )


def classify_business(text: str, risk_level: str, action_type: str) -> str:
    if risk_level in {"L1", "L2", "L3"}:
        return "emergency_risk"
    if action_type == "auto_reply":
        return "routine_report"
    if re.search(r"(申请|离泊|起锚|锚离底|备车|开航|解缆|穿越)", text):
        return "departure_request"
    if text.strip():
        return "other_business"
    return "invalid_or_noise"


def extract_entities(candidates: List[Dict[str, Any]], entity_type: str) -> str:
    values = [
        str(item.get("canonical") or "")
        for item in candidates
        if item.get("entity_type") == entity_type and item.get("canonical")
    ]
    return "；".join(dict.fromkeys(values))


def analyze_text(
    *,
    audio_id: str,
    model_name: str,
    evaluation_task: str,
    audio_path: Path,
    result: ASRResult,
    resolver: EntityResolver,
    risk_engine: KeywordRiskEngine,
    elapsed_s: float,
) -> Dict[str, object]:
    resolution = resolver.resolve(result.text)
    dialogue = postprocess_vhf_dialogue(resolution.resolved_text)
    candidates = [item.to_dict() for item in resolution.candidates]
    segment = AudioSegment(
        id=f"{audio_id}_{model_name}",
        channel_id="asr_compare",
        file_path=str(audio_path),
        clip_path=str(audio_path),
        start_ms=0,
        end_ms=0,
        duration_ms=0,
        text=result.text,
        confidence=result.confidence,
        keywords=[],
        engine=result.engine,
        resolved_text=dialogue.resolved_text,
        entities=candidates,
        asr_sentences=result.sentences,
    )
    events = risk_engine.evaluate(segment)
    first_event = events[0] if events else None
    risk_level = first_event.risk_level if first_event else "INFO"
    action_type = first_event.action_type if first_event else "manual_review"
    return {
        "audio_id": audio_id,
        "audio_path": str(audio_path),
        "评测类型": "上传录音" if evaluation_task == "upload" else "流式识别",
        "模型": model_name,
        "接口地址": model_endpoint(model_name),
        "资源ID": model_resource_id(model_name),
        "语音": result.text,
        "修正后文本": dialogue.resolved_text,
        "对话轮次": dialogue.dialogue_review_text,
        "业务类型": classify_business(dialogue.resolved_text, risk_level, action_type),
        "船名": extract_entities(candidates, "ship"),
        "地名": extract_entities(candidates, "location"),
        "相应时间": f"{elapsed_s:.3f}",
        "风险等级": risk_level,
        "处置类型": action_type,
        "是否可用": "",
        "错误类型": "",
        "备注": "流式候选的准确率可用该结果初筛；真实流式还需单独测TTFT/最终时延。"
        if evaluation_task == "streaming" and model_name not in {"volc-sauc-duration", "s2s-omni"}
        else "",
    }


def error_row(
    audio_id: str,
    audio_path: Path,
    model_name: str,
    evaluation_task: str,
    error: Exception,
    elapsed_s: float,
) -> Dict[str, object]:
    return {
        "audio_id": audio_id,
        "audio_path": str(audio_path),
        "评测类型": "上传录音" if evaluation_task == "upload" else "流式识别",
        "模型": model_name,
        "接口地址": model_endpoint(model_name),
        "资源ID": model_resource_id(model_name),
        "语音": "",
        "修正后文本": "",
        "对话轮次": "",
        "业务类型": "",
        "船名": "",
        "地名": "",
        "相应时间": f"{elapsed_s:.3f}",
        "风险等级": "",
        "处置类型": "",
        "是否可用": "0",
        "错误类型": f"MODEL_ERROR: {type(error).__name__}: {error}",
        "备注": "",
    }


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "audio_id",
        "audio_path",
        "评测类型",
        "模型",
        "接口地址",
        "资源ID",
        "语音",
        "修正后文本",
        "对话轮次",
        "业务类型",
        "船名",
        "地名",
        "相应时间",
        "风险等级",
        "处置类型",
        "是否可用",
        "错误类型",
        "备注",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ASR models and create a review CSV with business/entity fields.")
    parser.add_argument("--audio-dir", required=True, type=Path)
    parser.add_argument("--out", default="data/eval/asr_comparison_results_for_review.csv", type=Path)
    parser.add_argument("--limit", default=20, type=int, help="0 means dry-run/no audio; -1 means all files.")
    parser.add_argument("--task", choices=["upload", "streaming", "all"], default="upload")
    parser.add_argument("--models", default="", help="Comma-separated models. Empty means defaults for --task.")
    parser.add_argument("--continue-on-error", action="store_true", default=True)
    args = parser.parse_args()

    audio_files = iter_audio_files(args.audio_dir.expanduser().resolve(), args.limit)
    models = parse_models(args.models, args.task)
    storage = LocalStorage(settings)
    preprocessor = AudioPreprocessor(storage)
    resolver = EntityResolver(settings.entity_lexicon_path, enabled=settings.entity_resolver_enabled)
    risk_engine = KeywordRiskEngine()
    adapters = {model: make_adapter(model) for model in models}
    rows: List[Dict[str, object]] = []

    for audio_index, audio_path in enumerate(audio_files, start=1):
        audio_id = audio_path.stem
        normalized_path: Optional[Path] = None
        for model_name in models:
            started = time.perf_counter()
            try:
                if normalized_path is None:
                    normalized_path = Path(preprocessor.prepare(audio_path, enable_denoise=False).processed_path)
                adapter = adapters[model_name]
                evaluation_task = model_task(model_name, args.task)
                if adapter == "volc-file-asr":
                    result = run_volc_file_asr(normalized_path, model_name)
                elif adapter == "streaming-ws-candidate":
                    raise streaming_candidate_error(model_name)
                else:
                    result = adapter.transcribe(normalized_path)
                elapsed = time.perf_counter() - started
                rows.append(
                    analyze_text(
                        audio_id=audio_id,
                        model_name=model_name,
                        evaluation_task=evaluation_task,
                        audio_path=audio_path,
                        result=result,
                        resolver=resolver,
                        risk_engine=risk_engine,
                        elapsed_s=elapsed,
                    )
                )
                print(f"[{audio_index}/{len(audio_files)}] {model_name} {audio_path.name} OK {elapsed:.2f}s", flush=True)
            except Exception as exc:
                elapsed = time.perf_counter() - started
                rows.append(error_row(audio_id, audio_path, model_name, model_task(model_name, args.task), exc, elapsed))
                print(f"[{audio_index}/{len(audio_files)}] {model_name} {audio_path.name} ERROR {exc}", flush=True)
                if not args.continue_on_error:
                    raise
            write_csv(args.out, rows)

    print(f"wrote {len(rows)} rows -> {args.out}")


if __name__ == "__main__":
    main()
