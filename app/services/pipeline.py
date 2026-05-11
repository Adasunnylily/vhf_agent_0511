from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from app.domain.models import AudioSegment, RiskEvent
from app.services.audio_utils import slice_wav_segment
from app.services.asr import BaseASRAdapter
from app.services.preprocess import AudioPreprocessor
from app.services.risk_engine import KeywordRiskEngine
from app.services.storage import LocalStorage
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
    ) -> None:
        self.preprocessor = preprocessor
        self.vad = vad
        self.asr = asr
        self.risk_engine = risk_engine
        self.storage = storage

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
            shared_keywords = self._extract_keywords(full_result.text)
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
            keywords = self._extract_keywords(segment_result.text)
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

    def _extract_keywords(self, text: str) -> List[str]:
        lowered = text.lower()
        known_keywords = [
            "mayday",
            "求救",
            "进水",
            "起火",
            "失火",
            "着火",
            "冒烟",
            "救生筏",
            "左倾",
            "人员落水",
            "碰撞",
            "搁浅",
            "失控",
            "失去动力",
            "故障",
            "团雾",
            "让清航道",
            "避让",
            "未响应",
            "占频",
            "逆行",
            "禁止通行",
            "闯入",
            "超速",
            "未报告",
            "靠港",
            "靠泊",
            "抛锚",
            "报告线",
            "离泊",
            "出港",
        ]
        return [keyword for keyword in known_keywords if keyword.lower() in lowered]
