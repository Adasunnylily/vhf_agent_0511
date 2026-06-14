from __future__ import annotations

import asyncio
import math
import os
import time
import uuid
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings
from app.services.asr import (
    ASRResult,
    BaseASRAdapter,
    DashScopeParaformerASRAdapter,
    FunASRStreamingAdapter,
    QwenASRAdapter,
    sanitize_asr_text,
)
from app.services.audio_utils import slice_wav_segment
from app.services.vad import DetectedSegment, WavEnergyVAD
from app.services.volc_stream_asr import (
    DEFAULT_SAMPLE_RATE,
    AsrResponse,
    VolcStreamAsrClient,
    build_audio_only_request,
    build_auth_headers,
    build_full_client_request,
    collect_best_text,
    extract_stream_text,
    judge_wav,
    parse_response,
    read_wav_info,
    split_audio,
)


@dataclass(frozen=True)
class StreamTiming:
    stream_mode: str
    chunk_count: int
    ttft_ms: float
    final_latency_ms: float
    audio_duration_ms: float


def attach_stream_timing(result: ASRResult, timing: StreamTiming) -> ASRResult:
    return ASRResult(
        text=result.text,
        confidence=result.confidence,
        engine=result.engine,
        sentences=list(result.sentences or []),
        emotion_tags=list(result.emotion_tags or []),
        event_tags=list(result.event_tags or []),
        stream_mode=timing.stream_mode,
        ttft_ms=timing.ttft_ms,
        final_latency_ms=timing.final_latency_ms,
        chunk_count=timing.chunk_count,
        audio_duration_ms=timing.audio_duration_ms,
    )


def _ensure_valid_omp_threads() -> None:
    value = os.getenv("OMP_NUM_THREADS", "").strip()
    if not value:
        os.environ["OMP_NUM_THREADS"] = "1"
        return
    try:
        if int(value) <= 0:
            os.environ["OMP_NUM_THREADS"] = "1"
    except ValueError:
        os.environ["OMP_NUM_THREADS"] = "1"


def _funasr_chunk_stride_samples(chunk_size: List[int], sample_rate: int = DEFAULT_SAMPLE_RATE) -> int:
    # FunASR streaming: chunk_size[1] * 960 samples @16kHz (~600ms when chunk_size=[0,10,5]).
    if len(chunk_size) >= 2 and chunk_size[1] > 0:
        return max(1, int(chunk_size[1] * 960))
    return max(1, int(sample_rate * int(os.getenv("FUNASR_STREAM_CHUNK_MS", "600")) / 1000))


def read_pcm_chunks(
    wav_path: Path,
    *,
    chunk_duration_ms: int = 100,
) -> Tuple[bytes, int, int, List[bytes]]:
    content = wav_path.read_bytes()
    if not judge_wav(content):
        raise RuntimeError(f"流式识别需要 16k mono wav，当前文件: {wav_path.name}")
    channel_num, samp_width, frame_rate, _, wave_data = read_wav_info(content)
    if channel_num != 1 or samp_width != 2 or frame_rate != DEFAULT_SAMPLE_RATE:
        raise RuntimeError(
            f"流式识别需要 16kHz mono 16-bit PCM wav，当前: "
            f"{frame_rate}Hz ch={channel_num} width={samp_width * 8}bit"
        )
    bytes_per_ms = frame_rate * samp_width // 1000
    chunk_size = max(1, bytes_per_ms * chunk_duration_ms)
    chunks = split_audio(wave_data, chunk_size)
    duration_ms = int(len(wave_data) / bytes_per_ms)
    return wave_data, frame_rate, duration_ms, chunks


def run_volc_streaming_file(
    audio_path: Path,
    *,
    url: str,
    resource_id: str,
    segment_duration_ms: int = 200,
) -> ASRResult:
    app_key = os.getenv("VOLCENGINE_ASR_APP_KEY", "")
    access_key = os.getenv("VOLCENGINE_ASR_ACCESS_KEY", "")
    api_key = os.getenv("VOLCENGINE_ASR_API_KEY", "")
    uid = app_key or os.getenv("VOLCENGINE_ASR_UID", "vhf_agent_0511")
    headers = build_auth_headers(
        app_key=app_key,
        access_key=access_key,
        api_key=api_key,
        resource_id=resource_id,
        uid=uid,
    )

    async def _run() -> Tuple[str, StreamTiming]:
        async with VolcStreamAsrClient(
            url=url,
            headers=headers,
            uid=uid,
            segment_duration_ms=segment_duration_ms,
        ) as client:
            return await _transcribe_volc_timed(client, audio_path, segment_duration_ms)

    text, timing = asyncio.run(_run())
    result = ASRResult(
        text=sanitize_asr_text(text),
        confidence=0.0,
        engine=f"volc_stream_ws:{resource_id}",
    )
    return attach_stream_timing(result, timing)


async def _transcribe_volc_timed(
    client: VolcStreamAsrClient,
    file_path: Path,
    segment_duration_ms: int,
) -> Tuple[str, StreamTiming]:
    content = file_path.read_bytes()
    channel_num, samp_width, frame_rate, _, wave_data = read_wav_info(content)
    size_per_sec = channel_num * samp_width * frame_rate
    segment_size = max(1, size_per_sec * segment_duration_ms // 1000)
    audio_duration_ms = int(len(wave_data) / max(1, size_per_sec // 1000))

    import aiohttp

    started = time.perf_counter()
    first_text_ts: Optional[float] = None
    client.conn = await client.session.ws_connect(client.url, headers=client.headers)
    await client.conn.send_bytes(build_full_client_request(client.seq, client.uid))
    client.seq += 1
    first_msg = await client.conn.receive()
    if first_msg.type != aiohttp.WSMsgType.BINARY:
        raise RuntimeError(f"火山流式ASR握手失败: {first_msg.type}")

    responses: List[AsrResponse] = [parse_response(first_msg.data)]
    segments = split_audio(wave_data, segment_size)

    async def sender() -> None:
        for index, segment in enumerate(segments):
            is_last = index == len(segments) - 1
            await client.conn.send_bytes(
                build_audio_only_request(client.seq, segment, is_last=is_last)
            )
            if not is_last:
                client.seq += 1
            await asyncio.sleep(segment_duration_ms / 1000)

    sender_task = asyncio.create_task(sender())
    try:
        async for msg in client.conn:
            if msg.type != aiohttp.WSMsgType.BINARY:
                continue
            response = parse_response(msg.data)
            responses.append(response)
            text = extract_stream_text(response.payload_msg)
            if text and first_text_ts is None:
                first_text_ts = time.perf_counter()
            if response.is_last_package or response.code != 0:
                break
    finally:
        sender_task.cancel()
        try:
            await sender_task
        except asyncio.CancelledError:
            pass

    final_ts = time.perf_counter()
    text = collect_best_text(responses)
    if not text:
        raise RuntimeError(f"火山流式ASR未返回文本，responses={len(responses)}")

    ttft_ms = ((first_text_ts or final_ts) - started) * 1000
    timing = StreamTiming(
        stream_mode="volc_websocket",
        chunk_count=len(segments),
        ttft_ms=round(ttft_ms, 1),
        final_latency_ms=round((final_ts - started) * 1000, 1),
        audio_duration_ms=float(audio_duration_ms),
    )
    return text, timing


def run_dashscope_streaming_file(
    audio_path: Path,
    *,
    adapter: DashScopeParaformerASRAdapter,
) -> ASRResult:
    try:
        from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult
    except ImportError as exc:
        raise RuntimeError("缺少 dashscope SDK，请安装: pip install dashscope") from exc

    import dashscope

    api_key = os.getenv(adapter.api_key_env)
    if not api_key:
        raise RuntimeError(f"缺少环境变量 {adapter.api_key_env}")
    dashscope.api_key = api_key

    _, _, audio_duration_ms, pcm_chunks = read_pcm_chunks(
        audio_path,
        chunk_duration_ms=int(os.getenv("DASHSCOPE_STREAM_CHUNK_MS", "100")),
    )
    chunk_ms = int(os.getenv("DASHSCOPE_STREAM_CHUNK_MS", "100"))

    class CollectCallback(RecognitionCallback):
        def __init__(self) -> None:
            self.sentences: List[Dict[str, Any]] = []
            self.latest_text = ""
            self.error_message = ""
            self.started = time.perf_counter()
            self.first_text_ts: Optional[float] = None
            self.completed_ts: Optional[float] = None

        def on_event(self, result: RecognitionResult) -> None:
            sentence = result.get_sentence()
            rows = sentence if isinstance(sentence, list) else [sentence] if isinstance(sentence, dict) else []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                text = str(row.get("text") or "").strip()
                if not text:
                    continue
                if self.first_text_ts is None:
                    self.first_text_ts = time.perf_counter()
                self.latest_text = text
                if RecognitionResult.is_sentence_end(row):
                    self.sentences.append(
                        {
                            "text": text,
                            "speaker_id": row.get("speaker_id", row.get("speaker")),
                            "begin_time": row.get("begin_time", row.get("start_time")),
                            "end_time": row.get("end_time"),
                        }
                    )

        def on_error(self, result: RecognitionResult) -> None:
            self.error_message = str(result.message or result.code or result)

        def on_complete(self) -> None:
            self.completed_ts = time.perf_counter()

    callback = CollectCallback()
    model_name = adapter._resolve_model_name()
    call_kwargs: Dict[str, Any] = {
        "diarization_enabled": adapter.diarization_enabled,
    }
    if adapter.speaker_count > 0:
        call_kwargs["speaker_count"] = adapter.speaker_count
    if adapter.vocabulary_id:
        call_kwargs["vocabulary_id"] = adapter.vocabulary_id

    recognition = Recognition(
        model=model_name,
        callback=callback,
        format="pcm",
        sample_rate=DEFAULT_SAMPLE_RATE,
        **call_kwargs,
    )
    recognition.start(phrase_id=adapter.phrase_id or None)
    started = time.perf_counter()
    try:
        for chunk in pcm_chunks:
            recognition.send_audio_frame(chunk)
            time.sleep(chunk_ms / 1000)
    finally:
        recognition.stop()

    if callback.error_message:
        raise RuntimeError(f"DashScope 流式 ASR 失败: {callback.error_message}")

    final_ts = callback.completed_ts or time.perf_counter()
    if callback.sentences:
        text = "，".join(str(item.get("text") or "").strip() for item in callback.sentences if item.get("text"))
    else:
        text = callback.latest_text
    text = sanitize_asr_text(text)
    if not text:
        raise RuntimeError("DashScope 流式 ASR 未返回文本")

    ttft_ms = ((callback.first_text_ts or final_ts) - started) * 1000
    timing = StreamTiming(
        stream_mode="dashscope_websocket",
        chunk_count=len(pcm_chunks),
        ttft_ms=round(ttft_ms, 1),
        final_latency_ms=round((final_ts - started) * 1000, 1),
        audio_duration_ms=float(audio_duration_ms),
    )
    result = ASRResult(
        text=text,
        confidence=0.85,
        engine=f"dashscope_stream:{model_name}",
        sentences=callback.sentences,
    )
    return attach_stream_timing(result, timing)


def run_funasr_streaming_file(
    audio_path: Path,
    *,
    adapter: FunASRStreamingAdapter,
) -> ASRResult:
    try:
        import numpy as np
        import soundfile as sf
    except ImportError as exc:
        raise RuntimeError("缺少 soundfile/numpy，请安装 requirements-server.txt 中的依赖。") from exc

    _ensure_valid_omp_threads()
    audio, sample_rate = sf.read(str(audio_path), dtype="float32")
    if getattr(audio, "ndim", 1) > 1:
        audio = audio.mean(axis=1)
    if sample_rate != DEFAULT_SAMPLE_RATE:
        try:
            import librosa
        except ImportError as exc:
            raise RuntimeError(
                f"FunASR 流式识别需要 {DEFAULT_SAMPLE_RATE}Hz 音频，"
                f"当前 {sample_rate}Hz，请安装 librosa 或先走预处理。"
            ) from exc
        audio = librosa.resample(audio, orig_sr=sample_rate, target_sr=DEFAULT_SAMPLE_RATE)
        sample_rate = DEFAULT_SAMPLE_RATE

    chunk_stride_samples = _funasr_chunk_stride_samples(adapter.chunk_size, sample_rate)
    chunks: List[np.ndarray] = []
    for index in range(max(1, math.ceil(len(audio) / chunk_stride_samples))):
        start = index * chunk_stride_samples
        end = min(len(audio), start + chunk_stride_samples)
        piece = audio[start:end]
        if len(piece):
            chunks.append(np.ascontiguousarray(piece, dtype=np.float32))
    if not chunks:
        chunks = [np.ascontiguousarray(audio, dtype=np.float32)]

    started = time.perf_counter()
    first_text_ts: Optional[float] = None
    incremental = adapter.transcribe_stream(chunks)
    final_text = ""
    for item in incremental:
        if item.text:
            if first_text_ts is None:
                first_text_ts = time.perf_counter()
            final_text = item.text
    final_ts = time.perf_counter()
    text = sanitize_asr_text(final_text)
    if not text:
        raise RuntimeError("FunASR 流式 ASR 未返回文本")

    audio_duration_ms = int(len(audio) / max(1, sample_rate) * 1000)
    timing = StreamTiming(
        stream_mode="funasr_incremental",
        chunk_count=len(chunks),
        ttft_ms=round(((first_text_ts or final_ts) - started) * 1000, 1),
        final_latency_ms=round((final_ts - started) * 1000, 1),
        audio_duration_ms=float(audio_duration_ms),
    )
    result = ASRResult(
        text=text,
        confidence=incremental[-1].confidence if incremental else 0.85,
        engine=incremental[-1].engine if incremental else f"funasr_stream:{adapter.model_name}",
    )
    return attach_stream_timing(result, timing)


def run_qwen_vad_segment_stream(
    audio_path: Path,
    *,
    adapter: QwenASRAdapter,
    vad: WavEnergyVAD,
) -> ASRResult:
    """Qwen 当前无双向流式 API，这里按 VAD 切段后逐段识别并拼接。"""
    detected = vad.detect(audio_path) or [DetectedSegment(start_ms=0, end_ms=0)]
    if len(detected) == 1 and detected[0].end_ms <= detected[0].start_ms:
        segment_result = adapter.transcribe(audio_path)
        try:
            import soundfile as sf

            audio_duration_ms = int(sf.info(str(audio_path)).duration * 1000)
        except Exception:
            audio_duration_ms = 0.0
        timing = StreamTiming(
            stream_mode="qwen_vad_segment_sim",
            chunk_count=1,
            ttft_ms=0.0,
            final_latency_ms=0.0,
            audio_duration_ms=float(audio_duration_ms),
        )
        return attach_stream_timing(segment_result, timing)
    started = time.perf_counter()
    first_text_ts: Optional[float] = None
    parts: List[str] = []
    for index, item in enumerate(detected):
        duration_ms = max(1, item.end_ms - item.start_ms) if item.end_ms > item.start_ms else 0
        if duration_ms <= 0:
            clip_path = audio_path
        else:
            clip_path = audio_path.parent / f".stream_clip_{uuid.uuid4().hex[:8]}.wav"
            end_ms = item.end_ms if item.end_ms > item.start_ms else item.start_ms + duration_ms
            slice_wav_segment(
                source_path=audio_path,
                target_path=clip_path,
                start_ms=item.start_ms,
                end_ms=end_ms,
            )
        segment_result = adapter.transcribe(clip_path)
        if segment_result.text:
            if first_text_ts is None:
                first_text_ts = time.perf_counter()
            parts.append(segment_result.text.strip())
        if clip_path != audio_path and clip_path.exists():
            clip_path.unlink(missing_ok=True)
        if index < len(detected) - 1:
            time.sleep(max(0.0, duration_ms / 1000))

    final_ts = time.perf_counter()
    text = sanitize_asr_text("，".join(part for part in parts if part))
    if not text:
        raise RuntimeError("Qwen 分段流式模拟未返回文本")

    try:
        import soundfile as sf

        info = sf.info(str(audio_path))
        audio_duration_ms = int(info.duration * 1000)
    except Exception:
        audio_duration_ms = 0.0

    timing = StreamTiming(
        stream_mode="qwen_vad_segment_sim",
        chunk_count=len(detected),
        ttft_ms=round(((first_text_ts or final_ts) - started) * 1000, 1),
        final_latency_ms=round((final_ts - started) * 1000, 1),
        audio_duration_ms=float(audio_duration_ms),
    )
    result = ASRResult(
        text=text,
        confidence=0.85,
        engine=f"{adapter.model}:vad_segment_stream",
    )
    return attach_stream_timing(result, timing)


def run_streaming_file_asr(
    model_name: str,
    audio_path: Path,
    *,
    adapter: Any,
    volc_url: str = "",
    volc_resource_id: str = "",
) -> ASRResult:
    if adapter == "volc-stream-asr":
        return run_volc_streaming_file(
            audio_path,
            url=volc_url,
            resource_id=volc_resource_id,
            segment_duration_ms=int(os.getenv("VOLCENGINE_STREAM_SEGMENT_MS", "200")),
        )
    if isinstance(adapter, DashScopeParaformerASRAdapter):
        return run_dashscope_streaming_file(audio_path, adapter=adapter)
    if isinstance(adapter, FunASRStreamingAdapter):
        return run_funasr_streaming_file(audio_path, adapter=adapter)
    if isinstance(adapter, QwenASRAdapter):
        vad = WavEnergyVAD(
            frame_ms=settings.vad_frame_ms,
            silence_ms=settings.vad_silence_ms,
            min_speech_ms=settings.vad_min_speech_ms,
            max_segment_ms=settings.vad_max_segment_ms,
        )
        return run_qwen_vad_segment_stream(audio_path, adapter=adapter, vad=vad)
    raise RuntimeError(f"模型 {model_name} 未配置真流式/准流式识别路径")
