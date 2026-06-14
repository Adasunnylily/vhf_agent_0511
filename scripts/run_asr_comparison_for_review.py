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
    FunASRStreamingAdapter,
    QwenASRAdapter,
    sanitize_asr_text,
)
from app.services.entity_resolver import EntityResolver  # noqa: E402
from app.services.preprocess import AudioPreprocessor  # noqa: E402
from app.services.risk_engine import KeywordRiskEngine  # noqa: E402
from app.services.storage import LocalStorage  # noqa: E402
from app.services.vhf_dialogue import postprocess_vhf_dialogue  # noqa: E402
from app.services.asr_prompts import (  # noqa: E402
    build_qwen_eval_prompt,
    build_volc_request_options,
    default_hotwords_path,
    resolve_dashscope_vocabulary_id,
    resolve_paraformer_model,
)
from app.services.volc_stream_asr import transcribe_volc_stream_file  # noqa: E402
from app.services.streaming_file_asr import run_streaming_file_asr  # noqa: E402


AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".aac", ".ogg", ".webm"}
UPLOAD_RECORDING_MODELS = [
    "volc-bigasr-auc-turbo",
    "paraformer-v2",
    "qwen-asr-flash",
]
STREAMING_MODELS = [
    "volc-sauc-duration",
    "paraformer-v2",
    "qwen-asr-flash",
    "local-funasr",
]
STREAMING_OPTIONAL_MODELS = [
    "paraformer-realtime-v2",
    "sensevoice-realtime-v1",
    "paraformer-realtime-8k-v2",
    "local-funasr",
    "s2s-omni",
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
VOLC_RECOGNIZE_FLASH_ENDPOINT = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash"
VOLC_SUBMIT_ENDPOINT = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
VOLC_QUERY_ENDPOINT = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"

MODEL_ENDPOINTS = {
    "volc-bigasr-auc-turbo": VOLC_RECOGNIZE_FLASH_ENDPOINT,
    "volc-sauc-duration": "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel",
    "s2s-omni": "streaming/s2s-omni",
    "qwen-asr-flash": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "qwen-asr-pro": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "local-funasr": "local",
    "paraformer-v2": "dashscope websocket stream",
    "paraformer-realtime-v2": "dashscope websocket stream",
    "paraformer-realtime-8k-v2": "dashscope websocket stream",
    "sensevoice-realtime-v1": "dashscope websocket stream",
}
MODEL_RESOURCES = {
    "volc-bigasr-auc-turbo": "volc.bigasr.auc_turbo",
    "volc-sauc-duration": "volc.bigasr.sauc.duration",
}
PARAFORMER_DIARIZATION_MODELS = {
    "paraformer-v2",
    "paraformer-realtime-v2",
    "paraformer-realtime-8k-v2",
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


def load_manifest_entries(manifest_path: Path, limit: int) -> List[Dict[str, str]]:
    entries: List[Dict[str, str]] = []
    with manifest_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            audio_path = Path((row.get("audio_path") or "").strip())
            sample_id = (row.get("sample_id") or audio_path.stem).strip()
            if not sample_id or not audio_path.exists():
                continue
            entries.append(
                {
                    "sample_id": sample_id,
                    "audio_path": str(audio_path.resolve()),
                    "transcript_gt": (row.get("transcript_gt") or "").strip(),
                    "primary_label_gt": (row.get("primary_label_gt") or "").strip(),
                }
            )
    if limit == 0:
        return []
    return entries[:limit] if limit > 0 else entries


def normalize_model_name(model_name: str) -> str:
    key = model_name.strip()
    return MODEL_ALIASES.get(key, key)


def default_models_for_task(task: str) -> List[str]:
    if task == "upload":
        return UPLOAD_RECORDING_MODELS
    if task == "streaming":
        models = list(STREAMING_MODELS)
        optional = os.getenv("VHF_STREAMING_EXTRA_MODELS", "").strip()
        if optional:
            models.extend(normalize_model_name(item) for item in optional.split(",") if item.strip())
        if os.getenv("VHF_STREAMING_INCLUDE_LOCAL", "0").strip().lower() in {"1", "true", "yes"}:
            models.append("local-funasr")
        if os.getenv("VHF_STREAMING_INCLUDE_S2S", "0").strip().lower() in {"1", "true", "yes"}:
            models.append("s2s-omni")
        return list(dict.fromkeys(models))
    return list(dict.fromkeys([*UPLOAD_RECORDING_MODELS, *STREAMING_MODELS, *STREAMING_OPTIONAL_MODELS]))


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


def make_paraformer_adapter(model_name: str) -> DashScopeParaformerASRAdapter:
    hotwords_path = settings.asr_hotwords_path if settings.asr_hotwords_path.exists() else default_hotwords_path()
    target_model = resolve_paraformer_model(model_name)
    vocabulary_id = settings.asr_vocabulary_id or resolve_dashscope_vocabulary_id(target_model=target_model)
    return DashScopeParaformerASRAdapter(
        model=target_model,
        api_key_env=settings.dashscope_asr_api_key_env,
        diarization_enabled=settings.asr_diarization_enabled,
        speaker_count=settings.asr_speaker_count,
        phrase_id=settings.asr_phrase_id,
        vocabulary_id=vocabulary_id,
        hotwords_path=hotwords_path if hotwords_path.exists() else None,
    )


def make_qwen_adapter(model: str) -> QwenASRAdapter:
    hotwords_path = settings.asr_hotwords_path if settings.asr_hotwords_path.exists() else default_hotwords_path()
    return QwenASRAdapter(
        model=model,
        api_key_env=settings.qwen_asr_api_key_env,
        base_url=settings.qwen_asr_base_url,
        timeout_s=settings.qwen_asr_timeout_s,
        prompt=build_qwen_eval_prompt(hotwords_path=hotwords_path if hotwords_path.exists() else None),
        append_hotwords=False,
        hotwords_path=None,
    )


def make_streaming_adapter(model_name: str) -> Any:
    if model_name in {
        "paraformer-v2",
        "paraformer-realtime-v2",
        "paraformer-realtime-8k-v2",
        "sensevoice-realtime-v1",
    }:
        return make_paraformer_adapter(model_name)
    if model_name == "qwen-asr-flash":
        return make_qwen_adapter("qwen3-asr-flash")
    if model_name == "qwen-asr-pro":
        return make_qwen_adapter("qwen3-asr-pro")
    if model_name == "local-funasr":
        chunk_size = [int(part.strip()) for part in settings.streaming_chunk_size.split(",") if part.strip()]
        return FunASRStreamingAdapter(
            model=os.getenv("VHF_LOCAL_FUNASR_STREAM_MODEL", "paraformer-zh-streaming"),
            device=os.getenv("VHF_LOCAL_FUNASR_DEVICE", settings.asr_device),
            hub=settings.asr_hub,
            model_revision=settings.asr_model_revision,
            chunk_size=chunk_size or [0, 10, 5],
            encoder_chunk_look_back=settings.streaming_encoder_chunk_look_back,
            decoder_chunk_look_back=settings.streaming_decoder_chunk_look_back,
        )
    if model_name == "volc-sauc-duration":
        return "volc-stream-asr"
    if model_name == "s2s-omni":
        return "streaming-ws-candidate"
    raise ValueError(f"未知流式模型: {model_name}")


def make_adapter(model_name: str) -> Any:
    if model_name in {
        "paraformer-v2",
        "paraformer-realtime-v2",
        "paraformer-realtime-8k-v2",
        "sensevoice-realtime-v1",
    }:
        return make_paraformer_adapter(model_name)
    if model_name == "qwen-asr-flash":
        return make_qwen_adapter("qwen3-asr-flash")
    if model_name == "qwen-asr-pro":
        return make_qwen_adapter("qwen3-asr-pro")
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
    if model_name == "volc-sauc-duration":
        return "volc-stream-asr"
    if model_name == "s2s-omni":
        return "streaming-ws-candidate"
    raise ValueError(f"未知模型: {model_name}")


def build_volc_headers(resource_id: str) -> tuple[Dict[str, str], str]:
    app_key = os.getenv("VOLCENGINE_ASR_APP_KEY", "")
    access_key = os.getenv("VOLCENGINE_ASR_ACCESS_KEY", "")
    api_key = os.getenv("VOLCENGINE_ASR_API_KEY", "")
    request_id = str(uuid.uuid4())
    if app_key and access_key:
        headers = {
            "X-Api-App-Key": app_key,
            "X-Api-Access-Key": access_key,
            "X-Api-Resource-Id": resource_id,
            "X-Api-Request-Id": request_id,
            "X-Api-Sequence": "-1",
            "Content-Type": "application/json",
        }
        return headers, app_key
    if api_key:
        headers = {
            "X-Api-Key": api_key,
            "X-Api-Resource-Id": resource_id,
            "X-Api-Request-Id": request_id,
            "X-Api-Sequence": "-1",
            "Content-Type": "application/json",
        }
        uid = os.getenv("VOLCENGINE_ASR_UID", "vhf_agent_0511")
        return headers, uid
    raise RuntimeError("缺少 VOLCENGINE_ASR_APP_KEY/VOLCENGINE_ASR_ACCESS_KEY 或 VOLCENGINE_ASR_API_KEY")


def build_volc_payload(audio_path: Path, uid: str) -> Dict[str, Any]:
    return {
        "user": {"uid": uid},
        "audio": {"data": base64.b64encode(audio_path.read_bytes()).decode("utf-8")},
        "request": build_volc_request_options(streaming=False),
    }


def volc_status_code(response: Any) -> str:
    return str(response.headers.get("X-Api-Status-Code", "")).strip()


def poll_volc_query_result(
    requests: Any,
    headers: Dict[str, str],
    *,
    log_id: str = "",
    timeout_s: int = 300,
    interval_s: float = 2.0,
) -> Dict[str, Any]:
    query_endpoint = os.getenv("VOLCENGINE_FILE_ASR_QUERY_ENDPOINT", VOLC_QUERY_ENDPOINT)
    query_headers = dict(headers)
    if log_id:
        query_headers["X-Tt-Logid"] = log_id
    started = time.perf_counter()
    last_status = ""
    last_message = ""
    while time.perf_counter() - started < timeout_s:
        response = requests.post(query_endpoint, headers=query_headers, json={}, timeout=60)
        response.raise_for_status()
        last_status = volc_status_code(response)
        last_message = str(response.headers.get("X-Api-Message", ""))
        data = response.json() if response.content else {}
        text = extract_doubao_text(data if isinstance(data, dict) else {})
        if text:
            return data if isinstance(data, dict) else {}
        if last_status == "20000000":
            return data if isinstance(data, dict) else {}
        if last_status and last_status not in {"20000001", "20000002"}:
            raise RuntimeError(
                f"火山ASR查询失败 status={last_status} message={last_message} body={str(data)[:300]}"
            )
        time.sleep(interval_s)
    raise RuntimeError(
        f"火山ASR查询超时({timeout_s}s) status={last_status} message={last_message}"
    )


def run_volc_file_asr(audio_path: Path, model_name: str) -> ASRResult:
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("缺少 requests，请先安装: pip install requests") from exc

    endpoint = model_endpoint(model_name)
    resource_id = model_resource_id(model_name)
    headers, uid = build_volc_headers(resource_id)
    payload = build_volc_payload(audio_path, uid)
    timeout_s = int(os.getenv("VOLCENGINE_ASR_TIMEOUT_S", "300"))

    if endpoint.rstrip("/").endswith("/submit"):
        response = requests.post(endpoint, headers=headers, json=payload, timeout=timeout_s)
        response.raise_for_status()
        submit_status = volc_status_code(response)
        if submit_status and submit_status not in {"20000000", "20000001", "20000002"}:
            raise RuntimeError(
                f"火山ASR提交失败 status={submit_status} "
                f"message={response.headers.get('X-Api-Message', '')}"
            )
        log_id = response.headers.get("X-Tt-Logid", "")
        data = poll_volc_query_result(requests, headers, log_id=log_id, timeout_s=timeout_s)
    else:
        response = requests.post(endpoint, headers=headers, json=payload, timeout=timeout_s)
        response.raise_for_status()
        data = response.json() if response.content else {}
        if not isinstance(data, dict):
            data = {}

    text = extract_doubao_text(data)
    if not text:
        status_code = volc_status_code(response)
        message = response.headers.get("X-Api-Message", "")
        raise RuntimeError(f"火山ASR未返回文本 status={status_code} message={message} body={str(data)[:300]}")
    return ASRResult(text=sanitize_asr_text(text), confidence=0.0, engine=f"doubao_seed_asr:{resource_id}")


def run_volc_stream_asr(audio_path: Path, model_name: str) -> ASRResult:
    endpoint = model_endpoint(model_name)
    resource_id = model_resource_id(model_name)
    segment_duration_ms = int(os.getenv("VOLCENGINE_STREAM_SEGMENT_MS", "200"))
    text = transcribe_volc_stream_file(
        audio_path,
        url=endpoint,
        resource_id=resource_id,
        segment_duration_ms=segment_duration_ms,
    )
    return ASRResult(
        text=sanitize_asr_text(text),
        confidence=0.0,
        engine=f"volc_stream_asr:{resource_id}",
    )


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


def should_use_paraformer_diarization(model_name: str, result: ASRResult) -> bool:
    return model_name in PARAFORMER_DIARIZATION_MODELS and bool(result.sentences)


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
    manifest_meta: Optional[Dict[str, str]] = None,
) -> Dict[str, object]:
    resolution = resolver.resolve(result.text)
    use_diarization = should_use_paraformer_diarization(model_name, result)
    dialogue = postprocess_vhf_dialogue(
        resolution.resolved_text,
        asr_sentences=result.sentences if use_diarization else None,
        sentence_resolver=(lambda text: resolver.resolve(text).resolved_text) if use_diarization else None,
        map_speaker_roles=use_diarization,
    )
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
        asr_emotion_tags=list(result.emotion_tags or []),
        asr_event_tags=list(result.event_tags or []),
    )
    events = risk_engine.evaluate(segment)
    first_event = events[0] if events else None
    risk_level = first_event.risk_level if first_event else "INFO"
    action_type = first_event.action_type if first_event else "manual_review"
    meta = manifest_meta or {}
    return {
        "audio_id": audio_id,
        "audio_path": str(audio_path),
        "标注_sample_id": meta.get("sample_id", ""),
        "标注_业务类型": meta.get("primary_label_gt", ""),
        "标注_听写": meta.get("transcript_gt", ""),
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
        "流式模式": result.stream_mode or "",
        "TTFT_ms": "" if result.ttft_ms is None else f"{result.ttft_ms:.1f}",
        "最终延迟_ms": "" if result.final_latency_ms is None else f"{result.final_latency_ms:.1f}",
        "音频时长_ms": "" if result.audio_duration_ms is None else f"{result.audio_duration_ms:.0f}",
        "分片数": result.chunk_count or "",
        "风险等级": risk_level,
        "处置类型": action_type,
        "是否可用": "",
        "错误类型": "",
        "备注": _streaming_remark(result, evaluation_task, model_name),
    }


def _streaming_remark(result: ASRResult, evaluation_task: str, model_name: str) -> str:
    if evaluation_task != "streaming":
        return ""
    if result.stream_mode == "qwen_vad_segment_sim":
        return "Qwen 暂无双向流式 API，当前为 VAD 切段准流式；Paraformer/火山/FunASR 为真分片流式。"
    if result.stream_mode:
        return f"真分片流式: {result.stream_mode}"
    if model_name == "s2s-omni":
        return ""
    return "流式候选的准确率可用该结果初筛；真实流式还需单独测TTFT/最终时延。"


def error_row(
    audio_id: str,
    audio_path: Path,
    model_name: str,
    evaluation_task: str,
    error: Exception,
    elapsed_s: float,
    manifest_meta: Optional[Dict[str, str]] = None,
) -> Dict[str, object]:
    meta = manifest_meta or {}
    return {
        "audio_id": audio_id,
        "audio_path": str(audio_path),
        "标注_sample_id": meta.get("sample_id", ""),
        "标注_业务类型": meta.get("primary_label_gt", ""),
        "标注_听写": meta.get("transcript_gt", ""),
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
        "流式模式": "",
        "TTFT_ms": "",
        "最终延迟_ms": "",
        "音频时长_ms": "",
        "分片数": "",
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
        "标注_sample_id",
        "标注_业务类型",
        "标注_听写",
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
        "流式模式",
        "TTFT_ms",
        "最终延迟_ms",
        "音频时长_ms",
        "分片数",
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


def get_adapter(model_name: str, evaluation_task: str) -> Any:
    if evaluation_task == "streaming":
        return make_streaming_adapter(model_name)
    return make_adapter(model_name)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ASR models and create a review CSV with business/entity fields.")
    parser.add_argument("--audio-dir", type=Path, default=None)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="CSV manifest with sample_id/audio_path (from build_segment_manifest_from_xlsx.py).",
    )
    parser.add_argument("--out", default="data/eval/asr_comparison_results_for_review.csv", type=Path)
    parser.add_argument("--limit", default=20, type=int, help="0 means dry-run/no audio; -1 means all files.")
    parser.add_argument("--task", choices=["upload", "streaming", "all"], default="upload")
    parser.add_argument("--models", default="", help="Comma-separated models. Empty means defaults for --task.")
    parser.add_argument("--continue-on-error", action="store_true", default=True)
    args = parser.parse_args()
    if args.manifest is None and args.audio_dir is None:
        parser.error("请指定 --manifest 或 --audio-dir 之一。")

    manifest_entries: List[Dict[str, str]] = []
    if args.manifest is not None:
        manifest_entries = load_manifest_entries(args.manifest.expanduser().resolve(), args.limit)
        audio_files = [Path(item["audio_path"]) for item in manifest_entries]
    else:
        audio_files = iter_audio_files(args.audio_dir.expanduser().resolve(), args.limit)
    models = parse_models(args.models, args.task)
    storage = LocalStorage(settings)
    preprocessor = AudioPreprocessor(storage)
    resolver = EntityResolver(settings.entity_lexicon_path, enabled=settings.entity_resolver_enabled)
    risk_engine = KeywordRiskEngine()
    print("正在预加载 ASR 客户端...", flush=True)
    preload_models = sorted(set(models))
    for model_name in preload_models:
        upload_adapter = make_adapter(model_name)
        if model_name == "local-funasr":
            print(f"  {model_name} lazy-load", flush=True)
            continue
        if hasattr(upload_adapter, "_ensure_client"):
            try:
                upload_adapter._ensure_client()
                print(f"  {model_name} ready", flush=True)
            except Exception as exc:
                print(f"  {model_name} init skipped: {exc}", flush=True)
    rows: List[Dict[str, object]] = []

    for audio_index, audio_path in enumerate(audio_files, start=1):
        manifest_meta = manifest_entries[audio_index - 1] if manifest_entries else None
        audio_id = (manifest_meta or {}).get("sample_id") or audio_path.stem
        normalized_path: Optional[Path] = None
        for model_name in models:
            started = time.perf_counter()
            try:
                if normalized_path is None:
                    normalized_path = Path(preprocessor.prepare(audio_path, enable_denoise=False).processed_path)
                evaluation_task = model_task(model_name, args.task)
                adapter = get_adapter(model_name, evaluation_task)
                if evaluation_task == "streaming":
                    result = run_streaming_file_asr(
                        model_name,
                        normalized_path,
                        adapter=adapter,
                        volc_url=model_endpoint(model_name),
                        volc_resource_id=model_resource_id(model_name),
                    )
                elif adapter == "volc-file-asr":
                    result = run_volc_file_asr(normalized_path, model_name)
                elif adapter == "volc-stream-asr":
                    result = run_volc_stream_asr(normalized_path, model_name)
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
                        manifest_meta=manifest_meta,
                    )
                )
                print(f"[{audio_index}/{len(audio_files)}] {model_name} {audio_path.name} OK {elapsed:.2f}s", flush=True)
            except Exception as exc:
                elapsed = time.perf_counter() - started
                rows.append(
                    error_row(
                        audio_id,
                        audio_path,
                        model_name,
                        model_task(model_name, args.task),
                        exc,
                        elapsed,
                        manifest_meta=manifest_meta,
                    )
                )
                print(f"[{audio_index}/{len(audio_files)}] {model_name} {audio_path.name} ERROR {exc}", flush=True)
                if not args.continue_on_error:
                    raise
            write_csv(args.out, rows)

    print(f"wrote {len(rows)} rows -> {args.out}")


if __name__ == "__main__":
    main()
