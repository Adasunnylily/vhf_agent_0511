from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import List, Optional, Tuple

from app.domain.models import AudioSegment, RiskEvent
from app.services.asr import BaseASRAdapter
from app.services.audio_utils import slice_wav_segment
from app.services.entity_resolver import EntityResolver, EntityResolution
from app.services.maritime_keywords import extract_maritime_keywords
from app.services.preprocess import AudioPreprocessor
from app.services.risk_engine import KeywordRiskEngine
from app.services.storage import LocalStorage
from app.services.vhf_dialogue import postprocess_vhf_dialogue
from app.services.vad import DetectedSegment, WavEnergyVAD
from app.services.ws_manager import ChannelWebSocketManager


class StreamingAudioProcessor:
    def __init__(
        self,
        preprocessor: AudioPreprocessor,
        vad: WavEnergyVAD,
        asr: BaseASRAdapter,
        risk_engine: KeywordRiskEngine,
        storage: LocalStorage,
        ws_manager: ChannelWebSocketManager,
        simulation_speed: float = 8.0,
        entity_resolver: Optional[EntityResolver] = None,
    ) -> None:
        self.preprocessor = preprocessor
        self.vad = vad
        self.asr = asr
        self.risk_engine = risk_engine
        self.storage = storage
        self.ws_manager = ws_manager
        self.simulation_speed = simulation_speed
        self.entity_resolver = entity_resolver

    def process_file_stream(
        self,
        file_path: Path,
        channel_id: str,
        transcript_override: Optional[str] = None,
        enable_denoise: bool = False,
    ) -> Tuple[List[AudioSegment], List[RiskEvent]]:
        prepared = self.preprocessor.prepare(
            file_path=file_path,
            enable_denoise=enable_denoise,
        )
        normalized_path = Path(prepared.processed_path)
        self.ws_manager.publish(
            channel_id,
            {
                "type": "stream_status",
                "stage": "preprocessed",
                "channel_id": channel_id,
                "file_path": str(normalized_path),
                "denoise_enabled": enable_denoise,
                "preprocess": prepared.to_dict(),
            },
        )

        detected = self.vad.detect(normalized_path)
        if not detected:
            detected = [DetectedSegment(start_ms=0, end_ms=0)]

        segments: List[AudioSegment] = []
        events: List[RiskEvent] = []

        self.ws_manager.publish(
            channel_id,
            {
                "type": "stream_status",
                "stage": "vad_detected",
                "channel_id": channel_id,
                "segment_count": len(detected),
            },
        )

        for index, item in enumerate(detected):
            clip_path = self.storage.allocate_clip_path(".wav")
            slice_wav_segment(
                source_path=normalized_path,
                target_path=clip_path,
                start_ms=item.start_ms,
                end_ms=item.end_ms,
            )
            self.ws_manager.publish(
                channel_id,
                {
                    "type": "vad_segment",
                    "channel_id": channel_id,
                    "index": index,
                    "start_ms": item.start_ms,
                    "end_ms": item.end_ms,
                    "duration_ms": max(0, item.end_ms - item.start_ms),
                },
            )

            result = self.asr.transcribe(
                file_path=clip_path,
                transcript_override=transcript_override if index == 0 else None,
            )
            resolution = self._resolve_entities(result.text)
            text_for_rules = postprocess_vhf_dialogue(
                resolution.resolved_text,
                asr_sentences=result.sentences,
            ).resolved_text
            segment = AudioSegment(
                id=f"seg_{uuid.uuid4().hex[:12]}",
                channel_id=channel_id,
                file_path=str(normalized_path),
                clip_path=str(clip_path),
                start_ms=item.start_ms,
                end_ms=item.end_ms,
                duration_ms=max(0, item.end_ms - item.start_ms),
                text=result.text,
                confidence=result.confidence,
                keywords=self._extract_keywords(text_for_rules),
                engine=result.engine,
                resolved_text=text_for_rules,
                entities=[candidate.to_dict() for candidate in resolution.candidates],
                asr_sentences=result.sentences,
                asr_emotion_tags=list(result.emotion_tags or []),
                asr_event_tags=list(result.event_tags or []),
            )
            segments.append(segment)
            self.ws_manager.publish(
                channel_id,
                {
                    "type": "segment_result",
                    "channel_id": channel_id,
                    "segment": segment.to_dict(),
                },
            )

            for event in self.risk_engine.evaluate(segment):
                self.storage.save_event(event)
                events.append(event)
                self.ws_manager.publish(
                    channel_id,
                    {
                        "type": "risk_event",
                        "channel_id": channel_id,
                        "event": event.to_dict(),
                    },
                )

            self._simulate_real_time(segment.duration_ms)

        self.ws_manager.publish(
            channel_id,
            {
                "type": "stream_status",
                "stage": "completed",
                "channel_id": channel_id,
                "segments": len(segments),
                "events": len(events),
            },
        )
        return segments, events

    def _simulate_real_time(self, duration_ms: int) -> None:
        if self.simulation_speed <= 0:
            return
        delay = (duration_ms / 1000.0) / self.simulation_speed
        time.sleep(min(delay, 2.0))

    def _resolve_entities(self, text: str) -> EntityResolution:
        if self.entity_resolver is None:
            return EntityResolution(original_text=text, resolved_text=text, candidates=[])
        return self.entity_resolver.resolve(text)

    def _extract_keywords(self, text: str) -> List[str]:
        return extract_maritime_keywords(text)
