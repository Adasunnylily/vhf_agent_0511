from __future__ import annotations

import math
from pathlib import Path
from typing import List, Optional, Tuple

from app.domain.models import RiskEvent
from app.services.asr import ASRResult, BaseStreamingASRAdapter
from app.services.entity_resolver import EntityResolver, EntityResolution
from app.services.maritime_keywords import extract_maritime_keywords
from app.services.preprocess import AudioPreprocessor
from app.services.risk_engine import KeywordRiskEngine
from app.services.vhf_dialogue import postprocess_vhf_dialogue
from app.services.ws_manager import ChannelWebSocketManager


class RealtimeStreamingProcessor:
    def __init__(
        self,
        preprocessor: AudioPreprocessor,
        asr: BaseStreamingASRAdapter,
        risk_engine: KeywordRiskEngine,
        ws_manager: ChannelWebSocketManager,
        chunk_size: List[int],
        entity_resolver: Optional[EntityResolver] = None,
    ) -> None:
        self.preprocessor = preprocessor
        self.asr = asr
        self.risk_engine = risk_engine
        self.ws_manager = ws_manager
        self.chunk_size = chunk_size
        self.entity_resolver = entity_resolver

    def process_file_stream(
        self,
        file_path: Path,
        channel_id: str,
        enable_denoise: bool = False,
    ) -> Tuple[List[ASRResult], List[RiskEvent]]:
        prepared = self.preprocessor.prepare(
            file_path=file_path,
            enable_denoise=enable_denoise,
        )
        normalized_path = Path(prepared.processed_path)
        audio, sample_rate = self._read_audio(normalized_path)

        self.ws_manager.publish(
            channel_id,
            {
                "type": "stream_status",
                "stage": "preprocessed",
                "mode": "paraformer_streaming",
                "channel_id": channel_id,
                "sample_rate": sample_rate,
                "file_path": str(normalized_path),
                "denoise_enabled": enable_denoise,
                "preprocess": prepared.to_dict(),
            },
        )

        chunks = self._split_chunks(audio, sample_rate)
        self.ws_manager.publish(
            channel_id,
            {
                "type": "stream_status",
                "stage": "chunk_ready",
                "mode": "paraformer_streaming",
                "channel_id": channel_id,
                "chunk_count": len(chunks),
                "chunk_size": self.chunk_size,
            },
        )

        incremental_results = self.asr.transcribe_stream(chunks)
        events: List[RiskEvent] = []
        cumulative_text = ""

        for index, result in enumerate(incremental_results):
            if result.text:
                cumulative_text = result.text
            self.ws_manager.publish(
                channel_id,
                {
                    "type": "stream_chunk_result",
                    "mode": "paraformer_streaming",
                    "channel_id": channel_id,
                    "index": index,
                    "text": result.text,
                    "cumulative_text": cumulative_text,
                    "confidence": result.confidence,
                    "engine": result.engine,
                },
            )

        if cumulative_text:
            from app.domain.models import AudioSegment

            resolution = self._resolve_entities(cumulative_text)
            dialogue_result = postprocess_vhf_dialogue(resolution.resolved_text)
            segment = AudioSegment(
                id="streaming_final",
                channel_id=channel_id,
                file_path=str(normalized_path),
                clip_path=str(normalized_path),
                start_ms=0,
                end_ms=int(len(audio) * 1000 / sample_rate),
                duration_ms=int(len(audio) * 1000 / sample_rate),
                text=cumulative_text,
                confidence=incremental_results[-1].confidence if incremental_results else 0.85,
                keywords=self._extract_keywords(dialogue_result.resolved_text),
                engine=incremental_results[-1].engine if incremental_results else "funasr:streaming",
                resolved_text=dialogue_result.resolved_text,
                entities=[candidate.to_dict() for candidate in resolution.candidates],
            )
            self.ws_manager.publish(
                channel_id,
                {
                    "type": "stream_final_result",
                    "mode": "paraformer_streaming",
                    "channel_id": channel_id,
                    "segment": segment.to_dict(),
                },
            )
            events = self.risk_engine.evaluate(segment)
            for event in events:
                self.ws_manager.publish(
                    channel_id,
                    {
                        "type": "risk_event",
                        "mode": "paraformer_streaming",
                        "channel_id": channel_id,
                        "event": event.to_dict(),
                    },
                )

        self.ws_manager.publish(
            channel_id,
            {
                "type": "stream_status",
                "stage": "completed",
                "mode": "paraformer_streaming",
                "channel_id": channel_id,
                "chunk_count": len(chunks),
                "events": len(events),
            },
        )
        return incremental_results, events

    def _read_audio(self, file_path: Path) -> Tuple[List[float], int]:
        try:
            import soundfile as sf
        except ImportError as exc:
            raise RuntimeError("缺少 soundfile，请安装 requirements-server.txt 中的依赖。") from exc

        audio, sample_rate = sf.read(str(file_path), dtype="float32")
        if getattr(audio, "ndim", 1) > 1:
            audio = audio.mean(axis=1)
        return audio.tolist(), int(sample_rate)

    def _split_chunks(self, audio: List[float], sample_rate: int) -> List[List[float]]:
        chunk_ms = 60 * self.chunk_size[1]
        chunk_samples = max(1, int(sample_rate * chunk_ms / 1000))
        total_chunks = max(1, math.ceil(len(audio) / chunk_samples))
        chunks: List[List[float]] = []
        for index in range(total_chunks):
            start = index * chunk_samples
            end = min(len(audio), start + chunk_samples)
            chunk = audio[start:end]
            if chunk:
                chunks.append(chunk)
        if not chunks:
            chunks = [audio]
        return chunks

    def _resolve_entities(self, text: str) -> EntityResolution:
        if self.entity_resolver is None:
            return EntityResolution(original_text=text, resolved_text=text, candidates=[])
        return self.entity_resolver.resolve(text)

    def _extract_keywords(self, text: str) -> List[str]:
        return extract_maritime_keywords(text)
