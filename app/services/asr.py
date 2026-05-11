from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import threading
from typing import Any, Dict, List, Optional


@dataclass
class ASRResult:
    text: str
    confidence: float
    engine: str


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
        text = self._post_process_text(text)
        confidence = self._extract_confidence(results)
        return ASRResult(
            text=sanitize_asr_text(text),
            confidence=confidence,
            engine=f"funasr:{self.model_name}",
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
