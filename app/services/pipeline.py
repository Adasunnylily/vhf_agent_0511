from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from app.domain.models import AudioSegment, RiskEvent
from app.services.audio_utils import slice_wav_segment
from app.services.entity_resolver import EntityResolver
from app.services.asr import BaseASRAdapter
from app.services.maritime_keywords import extract_maritime_keywords
from app.services.preprocess import AudioPreprocessor
from app.services.risk_engine import KeywordRiskEngine
from app.services.storage import LocalStorage
from app.services.vhf_dialogue import postprocess_vhf_dialogue
from app.services.vad import DetectedSegment, WavEnergyVAD


@dataclass
class PipelineRunResult:
    segments: List[AudioSegment]
    events: List[RiskEvent]
    preprocess: dict


class AudioPipeline:
    def __init__(
        self,
        preprocessor: AudioPreprocessor,
        vad: WavEnergyVAD,
        asr: BaseASRAdapter,
        risk_engine: KeywordRiskEngine,
        storage: LocalStorage,
        entity_resolver: Optional[EntityResolver] = None,
    ) -> None:
        self.preprocessor = preprocessor
        self.vad = vad
        self.asr = asr
        self.risk_engine = risk_engine
        self.storage = storage
        self.entity_resolver = entity_resolver

    def process(
        self,
        file_path: Path,
        channel_id: str,
        transcript_override: Optional[str] = None,
        force_full_file_transcribe: bool = False,
        enable_denoise: bool = False,
    ) -> PipelineRunResult:
        prepared = self.preprocessor.prepare(
            file_path=file_path,
            enable_denoise=enable_denoise,
        )
        processed_path = Path(prepared.processed_path)
        detected = self.vad.detect(processed_path)
        if not detected:
            detected = [DetectedSegment(start_ms=0, end_ms=0)]

        segments: List[AudioSegment] = []
        events: List[RiskEvent] = []

        if force_full_file_transcribe:
            full_result = self.asr.transcribe(
                file_path=processed_path,
                transcript_override=transcript_override,
            )
            resolution = self._resolve_entities(full_result.text)
            text_for_rules = postprocess_vhf_dialogue(resolution.resolved_text).resolved_text
            shared_keywords = self._extract_keywords(text_for_rules)
            item = detected[0]
            segment = AudioSegment(
                id=f"seg_{uuid.uuid4().hex[:12]}",
                channel_id=channel_id,
                file_path=str(processed_path),
                clip_path=str(processed_path),
                start_ms=item.start_ms,
                end_ms=item.end_ms,
                duration_ms=max(0, item.end_ms - item.start_ms),
                text=full_result.text,
                confidence=full_result.confidence,
                keywords=shared_keywords,
                engine=full_result.engine,
                resolved_text=text_for_rules,
                entities=[candidate.to_dict() for candidate in resolution.candidates],
            )
            segments.append(segment)
            for event in self.risk_engine.evaluate(segment):
                self.storage.save_event(event)
                events.append(event)
            return PipelineRunResult(
                segments=segments,
                events=events,
                preprocess=prepared.to_dict(),
            )

        for index, item in enumerate(detected):
            duration_ms = max(0, item.end_ms - item.start_ms)
            clip_path = self.storage.allocate_clip_path(".wav")
            slice_wav_segment(
                source_path=processed_path,
                target_path=clip_path,
                start_ms=item.start_ms,
                end_ms=item.end_ms,
            )
            segment_result = self.asr.transcribe(
                file_path=clip_path,
                transcript_override=transcript_override if index == 0 else None,
            )
            resolution = self._resolve_entities(segment_result.text)
            text_for_rules = postprocess_vhf_dialogue(resolution.resolved_text).resolved_text
            keywords = self._extract_keywords(text_for_rules)
            segment = AudioSegment(
                id=f"seg_{uuid.uuid4().hex[:12]}",
                channel_id=channel_id,
                file_path=str(processed_path),
                clip_path=str(clip_path),
                start_ms=item.start_ms,
                end_ms=item.end_ms,
                duration_ms=duration_ms,
                text=segment_result.text,
                confidence=segment_result.confidence,
                keywords=keywords,
                engine=segment_result.engine,
                resolved_text=text_for_rules,
                entities=[candidate.to_dict() for candidate in resolution.candidates],
            )
            segments.append(segment)
            for event in self.risk_engine.evaluate(segment):
                self.storage.save_event(event)
                events.append(event)

        return PipelineRunResult(
            segments=segments,
            events=events,
            preprocess=prepared.to_dict(),
        )

    def _resolve_entities(self, text: str):
        if self.entity_resolver is None:
            from app.services.entity_resolver import EntityResolution

            return EntityResolution(original_text=text, resolved_text=text, candidates=[])
        return self.entity_resolver.resolve(text)

    def _extract_keywords(self, text: str) -> List[str]:
        return extract_maritime_keywords(text)
