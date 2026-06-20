from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import base64
import re
import threading
import time
from typing import Any, Dict, List, Optional
from http import HTTPStatus

from app.services.asr_prompts import ensure_dashscope_api_key_in_env
from app.services.funasr_emotion import extract_funasr_emotion_tags, extract_funasr_event_tags


@dataclass
class ASRResult:
    text: str
    confidence: float
    engine: str
    sentences: List[Dict[str, Any]] = field(default_factory=list)
    emotion_tags: List[str] = field(default_factory=list)
    event_tags: List[str] = field(default_factory=list)
    stream_mode: str = ""
    ttft_ms: Optional[float] = None
    final_latency_ms: Optional[float] = None
    chunk_count: int = 0
    audio_duration_ms: Optional[float] = None


def sanitize_asr_text(text: str) -> str:
    if not text:
        return text

    # Remove common emoji/pictograph ranges.
    text = re.sub(
        r"[\U0001F300-\U0001FAFF\U00002700-\U000027BF\U0001F1E6-\U0001F1FF]+",
        "",
        text,
    )

    # Remove generic bracketed style tags often produced by expressive speech models.
    text = re.sub(r"[\(\[\{（【][^)\]\}）】]{0,12}[\)\]\}）】]", "", text)

    # Collapse spaces between consecutive CJK characters.
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)

    # Remove repeated punctuation and unsuitable decorative symbols.
    text = re.sub(r"[~`^_=<>|\\/]{1,}", " ", text)
    text = re.sub(r"[#*]{2,}", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def detect_unexpected_language_marks(text: str) -> List[str]:
    """Flag scripts that should not appear in zh/en VHF transcripts."""
    marks: List[str] = []
    if re.search(r"[\u3040-\u30ff]", text):
        marks.append("japanese_kana")
    if re.search(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]", text):
        marks.append("korean_hangul")
    return marks


class BaseASRAdapter:
    def transcribe(
        self,
        file_path: Path,
        transcript_override: Optional[str] = None,
        ) -> ASRResult:
        raise NotImplementedError


class BaseStreamingASRAdapter:
    def transcribe_stream(
        self,
        chunks: List[Any],
    ) -> List[ASRResult]:
        raise NotImplementedError


class DemoASRAdapter(BaseASRAdapter):
    def transcribe(
        self,
        file_path: Path,
        transcript_override: Optional[str] = None,
    ) -> ASRResult:
        if transcript_override:
            return ASRResult(
                text=transcript_override.strip(),
                confidence=0.91,
                engine="demo_override",
            )

        sidecar = file_path.with_suffix(".txt")
        if sidecar.exists():
            text = sidecar.read_text(encoding="utf-8").strip()
            return ASRResult(text=text, confidence=0.86, engine="demo_sidecar")

        return ASRResult(
            text="",
            confidence=0.0,
            engine="demo_empty",
        )


class FunASRAdapter(BaseASRAdapter):
    def __init__(
        self,
        model: str,
        vad_model: str,
        punc_model: str,
        device: str = "cuda:0",
        hub: str = "ms",
        batch_size_s: int = 60,
        model_revision: Optional[str] = None,
        language: str = "auto",
        use_itn: bool = True,
        vad_max_single_segment_time: int = 30000,
    ) -> None:
        self.model_name = model
        self.vad_model = vad_model
        self.punc_model = punc_model
        self.device = device
        self.hub = hub
        self.batch_size_s = batch_size_s
        self.model_revision = model_revision or None
        self.language = language
        self.use_itn = use_itn
        self.vad_max_single_segment_time = vad_max_single_segment_time
        self._model = None
        self._postprocess = None
        self._model_lock = threading.Lock()
        self._generate_lock = threading.Lock()

    def transcribe(
        self,
        file_path: Path,
        transcript_override: Optional[str] = None,
    ) -> ASRResult:
        if transcript_override:
            return ASRResult(
                text=transcript_override.strip(),
                confidence=0.99,
                engine="manual_override",
            )

        model = self._ensure_model()
        with self._generate_lock:
            results = model.generate(
                input=str(file_path),
                batch_size_s=self.batch_size_s,
                language=self.language,
                use_itn=self.use_itn,
            )
        text = self._extract_text(results)
        emotion_tags = extract_funasr_emotion_tags(text)
        event_tags = extract_funasr_event_tags(text)
        text = self._post_process_text(text)
        confidence = self._extract_confidence(results)
        return ASRResult(
            text=sanitize_asr_text(text),
            confidence=confidence,
            engine=f"funasr:{self.model_name}",
            emotion_tags=emotion_tags,
            event_tags=event_tags,
        )

    def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model

        with self._model_lock:
            if self._model is not None:
                return self._model

            try:
                from funasr import AutoModel
            except ImportError as exc:
                raise RuntimeError(
                    "FunASR 未安装，请先在服务器执行依赖安装。"
                ) from exc

            try:
                from funasr.utils.postprocess_utils import rich_transcription_postprocess
            except ImportError:
                rich_transcription_postprocess = None

            kwargs: Dict[str, Any] = {
                "model": self.model_name,
                "device": self.device,
                "hub": self.hub,
                "disable_update": True,
            }
            if self.vad_model:
                kwargs["vad_model"] = self.vad_model
                kwargs["vad_kwargs"] = {
                    "max_single_segment_time": self.vad_max_single_segment_time
                }
            if self.punc_model:
                kwargs["punc_model"] = self.punc_model
            if self.model_revision:
                kwargs["model_revision"] = self.model_revision

            self._model = AutoModel(**kwargs)
            self._postprocess = rich_transcription_postprocess
            return self._model

    def _extract_text(self, results: Any) -> str:
        if isinstance(results, list) and results:
            first = results[0]
            if isinstance(first, dict):
                return str(first.get("text", "")).strip()
        if isinstance(results, dict):
            return str(results.get("text", "")).strip()
        return ""

    def _extract_confidence(self, results: Any) -> float:
        candidates: List[Any] = []
        if isinstance(results, list) and results:
            first = results[0]
            if isinstance(first, dict):
                candidates.extend(
                    [
                        first.get("confidence"),
                        first.get("score"),
                    ]
                )
        elif isinstance(results, dict):
            candidates.extend(
                [
                    results.get("confidence"),
                    results.get("score"),
                ]
            )

        for value in candidates:
            if isinstance(value, (int, float)):
                return max(0.0, min(1.0, float(value)))
        return 0.85

    def _post_process_text(self, text: str) -> str:
        if not text:
            return text
        if self._postprocess is None:
            return text
        try:
            return str(self._postprocess(text)).strip()
        except Exception:
            return text


class FunASRStreamingAdapter(BaseStreamingASRAdapter):
    def __init__(
        self,
        model: str = "paraformer-zh-streaming",
        device: str = "cuda:0",
        hub: str = "ms",
        model_revision: Optional[str] = None,
        chunk_size: Optional[List[int]] = None,
        encoder_chunk_look_back: int = 4,
        decoder_chunk_look_back: int = 1,
    ) -> None:
        self.model_name = model
        self.device = device
        self.hub = hub
        self.model_revision = model_revision or None
        self.chunk_size = chunk_size or [0, 10, 5]
        self.encoder_chunk_look_back = encoder_chunk_look_back
        self.decoder_chunk_look_back = decoder_chunk_look_back
        self._model = None
        self._model_lock = threading.Lock()
        self._generate_lock = threading.Lock()

    def transcribe_stream(
        self,
        chunks: List[Any],
    ) -> List[ASRResult]:
        model = self._ensure_model()
        cache: Dict[str, Any] = {}
        outputs: List[ASRResult] = []
        for index, chunk in enumerate(chunks):
            is_final = index == len(chunks) - 1
            with self._generate_lock:
                results = model.generate(
                    input=chunk,
                    cache=cache,
                    is_final=is_final,
                    chunk_size=self.chunk_size,
                    encoder_chunk_look_back=self.encoder_chunk_look_back,
                    decoder_chunk_look_back=self.decoder_chunk_look_back,
                )
            text = self._extract_text(results)
            outputs.append(
                ASRResult(
                    text=sanitize_asr_text(text),
                    confidence=self._extract_confidence(results),
                    engine=f"funasr:{self.model_name}",
                )
            )
        return outputs

    def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model
        with self._model_lock:
            if self._model is not None:
                return self._model
            try:
                from funasr import AutoModel
            except ImportError as exc:
                raise RuntimeError("FunASR 未安装，请先在服务器执行依赖安装。") from exc
            kwargs: Dict[str, Any] = {
                "model": self.model_name,
                "device": self.device,
                "hub": self.hub,
                "disable_update": True,
            }
            if self.model_revision:
                kwargs["model_revision"] = self.model_revision
            self._model = AutoModel(**kwargs)
            return self._model

    def _extract_text(self, results: Any) -> str:
        if isinstance(results, list) and results:
            first = results[0]
            if isinstance(first, dict):
                return str(first.get("text", "")).strip()
        if isinstance(results, dict):
            return str(results.get("text", "")).strip()
        return ""

    def _extract_confidence(self, results: Any) -> float:
        candidates: List[Any] = []
        if isinstance(results, list) and results:
            first = results[0]
            if isinstance(first, dict):
                candidates.extend([first.get("confidence"), first.get("score")])
        elif isinstance(results, dict):
            candidates.extend([results.get("confidence"), results.get("score")])
        for value in candidates:
            if isinstance(value, (int, float)):
                return max(0.0, min(1.0, float(value)))
        return 0.85


class QwenASRAdapter(BaseASRAdapter):
    def __init__(
        self,
        model: str = "qwen3-asr-flash",
        api_key_env: str = "DASHSCOPE_API_KEY",
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        timeout_s: int = 120,
        prompt: str = "",
        append_hotwords: bool = True,
        hotwords_path: Optional[Path] = None,
    ) -> None:
        self.model = model
        self.api_key_env = api_key_env
        self.base_url = base_url
        self.timeout_s = timeout_s
        self.prompt = prompt
        self.append_hotwords = append_hotwords
        self.hotwords_path = hotwords_path
        self._client: Any = None
        self._lock = threading.Lock()

    def transcribe(
        self,
        file_path: Path,
        transcript_override: Optional[str] = None,
    ) -> ASRResult:
        if transcript_override:
            return ASRResult(
                text=transcript_override.strip(),
                confidence=0.99,
                engine="manual_override",
            )
        client = self._ensure_client()
        try:
            data_url = self._audio_to_data_url(file_path)
            messages: List[Dict[str, object]] = []
            prompt = self._build_prompt()
            if prompt:
                messages.append(
                    {"role": "system", "content": [{"type": "text", "text": prompt}]}
                )
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {"data": data_url},
                        }
                    ],
                }
            )
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,  # type: ignore[arg-type]
                stream=False,
                extra_body={
                    "asr_options": {
                        "language": "zh",
                        "enable_itn": True,
                    }
                },
            )
            text = ""
            if getattr(response, "choices", None):
                text = response.choices[0].message.content or ""
            return ASRResult(
                text=sanitize_asr_text(str(text)),
                confidence=0.0,
                engine=f"qwen_asr:{self.model}",
            )
        except Exception as exc:
            raise RuntimeError(f"Qwen ASR 调用失败: {exc}") from exc

    def _build_prompt(self) -> str:
        parts = [self.prompt.strip()]
        hotwords: List[str] = []
        if self.hotwords_path:
            hotwords = load_hotword_lines(self.hotwords_path, limit=50)
        elif self.append_hotwords:
            hotwords = MARITIME_HOTWORDS[:80]
        if hotwords:
            parts.append("热词：" + "、".join(hotwords))
        return "\n".join(part for part in parts if part)

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        with self._lock:
            if self._client is not None:
                return self._client
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise RuntimeError("缺少 openai SDK，请安装: pip install openai") from exc
            api_key = ensure_dashscope_api_key_in_env(env_name=self.api_key_env)
            self._client = OpenAI(
                api_key=api_key,
                base_url=self.base_url,
                timeout=self.timeout_s,
            )
            return self._client

    def _audio_to_data_url(self, file_path: Path) -> str:
        suffix = file_path.suffix.lower()
        mime = {
            ".wav": "audio/wav",
            ".mp3": "audio/mpeg",
            ".m4a": "audio/mp4",
            ".mp4": "audio/mp4",
            ".aac": "audio/aac",
            ".flac": "audio/flac",
            ".webm": "audio/webm",
            ".ogg": "audio/ogg",
            ".pcm": "audio/wav",
        }.get(suffix, "audio/wav")
        encoded = base64.b64encode(file_path.read_bytes()).decode("utf-8")
        return f"data:{mime};base64,{encoded}"


class LocalQwenASRAdapter(BaseASRAdapter):
    """Local Qwen3-ASR adapter backed by the official qwen-asr package."""

    def __init__(
        self,
        model: str = "Qwen/Qwen3-ASR-0.6B",
        device_map: str = "cuda:0",
        dtype: str = "bfloat16",
        language: str = "Chinese",
        max_new_tokens: int = 256,
        max_inference_batch_size: int = 8,
        prompt: str = "",
    ) -> None:
        self.model_name = model
        self.device_map = device_map
        self.dtype = dtype
        self.language = language
        self.max_new_tokens = max_new_tokens
        self.max_inference_batch_size = max_inference_batch_size
        self.prompt = prompt
        self._model: Any = None
        self._model_lock = threading.Lock()
        self._generate_lock = threading.Lock()

    def transcribe(
        self,
        file_path: Path,
        transcript_override: Optional[str] = None,
    ) -> ASRResult:
        if transcript_override:
            return ASRResult(
                text=transcript_override.strip(),
                confidence=0.99,
                engine="manual_override",
            )

        model = self._ensure_model()
        started = time.perf_counter()
        with self._generate_lock:
            results = self._call_transcribe(model, file_path)
        elapsed_ms = (time.perf_counter() - started) * 1000
        text = sanitize_asr_text(self._extract_text(results))
        return ASRResult(
            text=text,
            confidence=0.0,
            engine=f"qwen_local:{self.model_name}",
            final_latency_ms=elapsed_ms,
        )

    def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model

        with self._model_lock:
            if self._model is not None:
                return self._model
            try:
                import torch
                from qwen_asr import Qwen3ASRModel
            except ImportError as exc:
                raise RuntimeError(
                    "缺少本地 Qwen3-ASR 依赖，请先安装: pip install -U qwen-asr"
                ) from exc

            kwargs: Dict[str, Any] = {
                "device_map": self.device_map,
                "max_new_tokens": self.max_new_tokens,
                "max_inference_batch_size": self.max_inference_batch_size,
            }
            dtype = self._resolve_torch_dtype(torch)
            if dtype is not None:
                kwargs["dtype"] = dtype
            self._model = Qwen3ASRModel.from_pretrained(self.model_name, **kwargs)
            return self._model

    def _resolve_torch_dtype(self, torch: Any) -> Any:
        key = (self.dtype or "").strip().lower()
        if not key or key in {"auto", "none"}:
            return None
        if key in {"bf16", "bfloat16"}:
            return torch.bfloat16
        if key in {"fp16", "float16", "half"}:
            return torch.float16
        if key in {"fp32", "float32", "float"}:
            return torch.float32
        raise ValueError(f"不支持的 Qwen3-ASR dtype: {self.dtype}")

    def _call_transcribe(self, model: Any, file_path: Path) -> Any:
        kwargs: Dict[str, Any] = {"audio": str(file_path)}
        if self.language:
            kwargs["language"] = self.language
        if self.prompt:
            kwargs["context"] = self.prompt
        try:
            return model.transcribe(**kwargs)
        except TypeError:
            kwargs.pop("context", None)
            return model.transcribe(**kwargs)

    def _extract_text(self, results: Any) -> str:
        if isinstance(results, list) and results:
            return self._extract_text(results[0])
        if isinstance(results, dict):
            for key in ("text", "transcript", "prediction"):
                if results.get(key):
                    return str(results[key]).strip()
        for attr in ("text", "transcript", "prediction"):
            value = getattr(results, attr, None)
            if value:
                return str(value).strip()
        if isinstance(results, str):
            return results.strip()
        return ""


def load_hotword_lines(path: Path, limit: int = 80) -> List[str]:
    if not path.exists():
        return []
    words: List[str] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        item = line.strip()
        if item and not item.startswith("#"):
            words.append(item)
        if len(words) >= limit:
            break
    return words


def format_diarized_text(sentences: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for sentence in sentences:
        text = str(sentence.get("text") or "").strip()
        if not text:
            continue
        speaker = sentence.get("speaker_id", sentence.get("speaker"))
        if speaker is None or speaker == "":
            parts.append(text)
        else:
            parts.append(f"说话人{speaker}：{text}")
    return "，".join(parts)


class DashScopeParaformerASRAdapter(BaseASRAdapter):
    """DashScope Recognition API with optional speaker diarization (paraformer-v2)."""

    def __init__(
        self,
        model: str = "paraformer-v2",
        api_key_env: str = "DASHSCOPE_API_KEY",
        sample_rate: int = 16000,
        diarization_enabled: bool = True,
        speaker_count: int = 2,
        phrase_id: str = "",
        vocabulary_id: str = "",
        hotwords_path: Optional[Path] = None,
    ) -> None:
        self.model = model
        self.api_key_env = api_key_env
        self.sample_rate = sample_rate
        self.diarization_enabled = diarization_enabled
        self.speaker_count = speaker_count
        self.phrase_id = phrase_id.strip()
        self.vocabulary_id = vocabulary_id.strip()
        self.hotwords_path = hotwords_path
        self._lock = threading.Lock()

    def transcribe(
        self,
        file_path: Path,
        transcript_override: Optional[str] = None,
    ) -> ASRResult:
        if transcript_override:
            return ASRResult(
                text=transcript_override.strip(),
                confidence=0.99,
                engine="manual_override",
            )

        api_key = ensure_dashscope_api_key_in_env(env_name=self.api_key_env)

        suffix = file_path.suffix.lower()
        if suffix != ".wav":
            raise RuntimeError(
                f"DashScope Recognition 需要 16k mono wav，请先预处理。当前文件: {file_path.name}"
            )

        try:
            import dashscope
            from dashscope.audio.asr import Recognition, RecognitionCallback
        except ImportError as exc:
            raise RuntimeError("缺少 dashscope SDK，请安装: pip install dashscope") from exc

        dashscope.api_key = api_key
        model_name = self._resolve_model_name()

        call_kwargs: Dict[str, Any] = {
            "diarization_enabled": self.diarization_enabled,
        }
        if self.speaker_count > 0:
            call_kwargs["speaker_count"] = self.speaker_count
        if self.vocabulary_id:
            call_kwargs["vocabulary_id"] = self.vocabulary_id
        hotwords = load_hotword_lines(self.hotwords_path) if self.hotwords_path else []
        if (
            hotwords
            and not self.vocabulary_id
            and not self.phrase_id
            and "realtime" not in model_name
        ):
            call_kwargs["vocabulary"] = [{"text": word} for word in hotwords[:50]]

        recognition = Recognition(
            model=model_name,
            callback=RecognitionCallback(),
            format="wav",
            sample_rate=self.sample_rate,
            **call_kwargs,
        )

        with self._lock:
            result = recognition.call(
                file=str(file_path),
                phrase_id=self.phrase_id or None,
            )

        if result.status_code != HTTPStatus.OK:
            raise RuntimeError(
                f"DashScope ASR 失败: {getattr(result, 'code', '')} {getattr(result, 'message', result)}"
            )

        sentences = self._normalize_sentences(result.get_sentence())
        text = format_diarized_text(sentences)
        if not text:
            text = self._fallback_text(result)
        text = sanitize_asr_text(text)
        return ASRResult(
            text=text,
            confidence=0.85 if text else 0.0,
            engine=f"dashscope:{model_name}",
            sentences=sentences,
        )

    def _resolve_model_name(self) -> str:
        from app.services.asr_prompts import resolve_paraformer_model

        return resolve_paraformer_model(self.model)

    def _normalize_sentences(self, payload: Any) -> List[Dict[str, Any]]:
        if payload is None:
            return []
        rows = payload if isinstance(payload, list) else [payload]
        normalized: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            text = str(row.get("text") or "").strip()
            if not text:
                continue
            normalized.append(
                {
                    "text": text,
                    "speaker_id": row.get("speaker_id", row.get("speaker")),
                    "begin_time": row.get("begin_time", row.get("start_time")),
                    "end_time": row.get("end_time"),
                }
            )
        return normalized

    def _fallback_text(self, result: Any) -> str:
        output = getattr(result, "output", None) or {}
        if isinstance(output, dict):
            sentence = output.get("sentence")
            if isinstance(sentence, dict):
                return str(sentence.get("text") or "").strip()
            if isinstance(sentence, list):
                return "，".join(
                    str(item.get("text") or "").strip()
                    for item in sentence
                    if isinstance(item, dict) and str(item.get("text") or "").strip()
                )
        return ""


class ASRRefiner:
    """Optional second-pass ASR for improving short VHF clips after realtime decoding."""

    def __init__(
        self,
        adapter: Optional[BaseASRAdapter] = None,
        *,
        enabled: bool = False,
        min_duration_ms: int = 1000,
    ) -> None:
        self.adapter = adapter
        self.enabled = enabled and adapter is not None
        self.min_duration_ms = max(0, min_duration_ms)

    def refine(
        self,
        file_path: Path,
        base_result: ASRResult,
        *,
        duration_ms: Optional[int] = None,
    ) -> ASRResult:
        if not self.enabled or self.adapter is None:
            return base_result
        if duration_ms is not None and duration_ms < self.min_duration_ms:
            return base_result
        if not file_path.exists() or file_path.stat().st_size <= 0:
            return base_result
        if "qwen_asr:" in base_result.engine:
            return base_result
        try:
            refined = self.adapter.transcribe(file_path=file_path)
        except Exception:
            return base_result
        refined_text = sanitize_asr_text(refined.text)
        if not refined_text:
            return base_result
        return ASRResult(
            text=refined_text,
            confidence=refined.confidence if refined.confidence else base_result.confidence,
            engine=f"{base_result.engine}+refine:{refined.engine}",
            sentences=base_result.sentences or refined.sentences,
            emotion_tags=list(base_result.emotion_tags or refined.emotion_tags or []),
            event_tags=list(base_result.event_tags or refined.event_tags or []),
            stream_mode=base_result.stream_mode or refined.stream_mode,
            ttft_ms=base_result.ttft_ms,
            final_latency_ms=base_result.final_latency_ms,
            chunk_count=base_result.chunk_count,
            audio_duration_ms=base_result.audio_duration_ms,
        )


def create_asr_adapter(settings: Any) -> BaseASRAdapter:
    provider = str(getattr(settings, "asr_provider", "qwen_api") or "qwen_api").strip().lower()
    if provider == "qwen_api":
        return QwenASRAdapter(
            model=settings.asr_model or "qwen3-asr-flash",
            api_key_env=settings.qwen_asr_api_key_env,
            base_url=settings.qwen_asr_base_url,
            timeout_s=settings.qwen_asr_timeout_s,
            prompt=settings.qwen_asr_prompt,
            hotwords_path=getattr(settings, "asr_hotwords_path", None),
        )
    if provider in {"qwen_local", "local_qwen", "qwen3_asr_local"}:
        return LocalQwenASRAdapter(
            model=getattr(settings, "qwen_local_model", None) or settings.asr_model or "Qwen/Qwen3-ASR-0.6B",
            device_map=getattr(settings, "qwen_local_device_map", None) or settings.asr_device,
            dtype=getattr(settings, "qwen_local_dtype", "bfloat16"),
            language=getattr(settings, "qwen_local_language", "Chinese"),
            max_new_tokens=getattr(settings, "qwen_local_max_new_tokens", 256),
            max_inference_batch_size=getattr(settings, "qwen_local_batch_size", 8),
            prompt=getattr(settings, "qwen_asr_prompt", ""),
        )
    if provider in {"dashscope_paraformer", "paraformer_v2"}:
        from app.services.asr_prompts import resolve_dashscope_vocabulary_id, resolve_paraformer_model

        model_name = resolve_paraformer_model(settings.asr_model or "paraformer-v2")
        vocabulary_id = settings.asr_vocabulary_id or resolve_dashscope_vocabulary_id(
            target_model=model_name
        )
        return DashScopeParaformerASRAdapter(
            model=model_name,
            api_key_env=settings.dashscope_asr_api_key_env,
            sample_rate=getattr(settings, "asr_sample_rate", 16000),
            diarization_enabled=settings.asr_diarization_enabled,
            speaker_count=settings.asr_speaker_count,
            phrase_id=settings.asr_phrase_id,
            vocabulary_id=vocabulary_id,
            hotwords_path=settings.asr_hotwords_path,
        )
    return FunASRAdapter(
        model=settings.asr_model,
        vad_model=settings.asr_vad_model,
        punc_model=settings.asr_punc_model,
        device=settings.asr_device,
        hub=settings.asr_hub,
        batch_size_s=settings.asr_batch_size_s,
        model_revision=settings.asr_model_revision,
        language=settings.asr_language,
        use_itn=settings.asr_use_itn,
        vad_max_single_segment_time=settings.asr_vad_max_single_segment_time,
    )


def create_asr_refiner(settings: Any) -> ASRRefiner:
    if not getattr(settings, "asr_refine_enabled", False):
        return ASRRefiner(enabled=False)
    adapter = QwenASRAdapter(
        model=getattr(settings, "asr_refine_model", "qwen3-asr-flash"),
        api_key_env=getattr(settings, "asr_refine_api_key_env", "DASHSCOPE_API_KEY"),
        base_url=getattr(
            settings,
            "asr_refine_base_url",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
        timeout_s=getattr(settings, "asr_refine_timeout_s", 120),
        prompt=getattr(settings, "qwen_asr_prompt", ""),
        hotwords_path=getattr(settings, "asr_hotwords_path", None),
    )
    return ASRRefiner(
        adapter=adapter,
        enabled=True,
        min_duration_ms=getattr(settings, "asr_refine_min_duration_ms", 1000),
    )
