from __future__ import annotations

import audioop
import contextlib
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple


@dataclass
class DetectedSegment:
    start_ms: int
    end_ms: int


class WavEnergyVAD:
    def __init__(
        self,
        frame_ms: int = 30,
        min_speech_ms: int = 600,
        silence_ms: int = 900,
        energy_threshold: int = 450,
        max_segment_ms: int = 0,
        threshold_mode: str = "adaptive",
        noise_percentile: float = 20.0,
        speech_percentile: float = 90.0,
        threshold_ratio: float = 0.35,
    ) -> None:
        self.frame_ms = frame_ms
        self.min_speech_ms = min_speech_ms
        self.silence_ms = silence_ms
        self.energy_threshold = energy_threshold
        self.max_segment_ms = max_segment_ms
        self.threshold_mode = threshold_mode
        self.noise_percentile = noise_percentile
        self.speech_percentile = speech_percentile
        self.threshold_ratio = threshold_ratio
        self.last_threshold = float(energy_threshold)

    def detect(self, file_path: Path) -> List[DetectedSegment]:
        if file_path.suffix.lower() != ".wav":
            return []

        with contextlib.closing(wave.open(str(file_path), "rb")) as wav_file:
            sample_rate = wav_file.getframerate()
            sample_width = wav_file.getsampwidth()
            channels = wav_file.getnchannels()
            total_frames = wav_file.getnframes()

            frame_size = max(1, int(sample_rate * self.frame_ms / 1000))
            silence_frames = max(1, int(self.silence_ms / self.frame_ms))
            min_frames = max(1, int(self.min_speech_ms / self.frame_ms))
            max_frames = max(1, int(self.max_segment_ms / self.frame_ms)) if self.max_segment_ms > 0 else 0
            frames = self._read_rms_frames(wav_file, frame_size, sample_width, channels)
            threshold = self._resolve_threshold([rms for rms, _ in frames])
            self.last_threshold = threshold

            segments: List[DetectedSegment] = []
            speech_start = None
            silent_run = 0

            for frame_index, (rms, _duration_ms) in enumerate(frames):
                is_speech = rms >= threshold

                if is_speech and speech_start is None:
                    speech_start = frame_index
                    silent_run = 0
                elif is_speech:
                    silent_run = 0
                elif speech_start is not None:
                    silent_run += 1
                    if silent_run >= silence_frames:
                        speech_end = max(speech_start, frame_index - silent_run + 1)
                        if speech_end - speech_start + 1 >= min_frames:
                            segments.append(
                                DetectedSegment(
                                    start_ms=speech_start * self.frame_ms,
                                    end_ms=(speech_end + 1) * self.frame_ms,
                                )
                            )
                        speech_start = None
                        silent_run = 0

                if max_frames > 0 and speech_start is not None and frame_index - speech_start + 1 >= max_frames:
                    speech_end = frame_index
                    if speech_end - speech_start + 1 >= min_frames:
                        segments.append(
                            DetectedSegment(
                                start_ms=speech_start * self.frame_ms,
                                end_ms=(speech_end + 1) * self.frame_ms,
                            )
                        )
                    speech_start = None
                    silent_run = 0

            if speech_start is not None:
                speech_end = max(speech_start, len(frames) - 1)
                if speech_end - speech_start + 1 >= min_frames:
                    segments.append(
                        DetectedSegment(
                            start_ms=speech_start * self.frame_ms,
                            end_ms=(speech_end + 1) * self.frame_ms,
                        )
                    )

            if not segments and total_frames > 0:
                total_ms = int(total_frames * 1000 / sample_rate)
                return self._split_long_segment(total_ms)

            return segments

    def _read_rms_frames(
        self,
        wav_file: wave.Wave_read,
        frame_size: int,
        sample_width: int,
        channels: int,
    ) -> List[Tuple[int, int]]:
        frames: List[Tuple[int, int]] = []
        sample_rate = wav_file.getframerate()
        while True:
            raw = wav_file.readframes(frame_size)
            if not raw:
                break

            frame_count = max(1, len(raw) // max(1, sample_width * channels))
            if channels > 1:
                raw = audioop.tomono(raw, sample_width, 0.5, 0.5)
            rms = audioop.rms(raw, sample_width)
            duration_ms = max(1, int(frame_count * 1000 / sample_rate))
            frames.append((rms, duration_ms))
        return frames

    def _resolve_threshold(self, rms_values: List[int]) -> float:
        if self.threshold_mode == "fixed" or not rms_values:
            return float(self.energy_threshold)

        positive = sorted(value for value in rms_values if value > 0)
        if not positive:
            return float(self.energy_threshold)

        noise = self._percentile(positive, self.noise_percentile)
        speech = self._percentile(positive, self.speech_percentile)
        if speech <= noise:
            return float(self.energy_threshold)

        adaptive = noise + (speech - noise) * self.threshold_ratio
        return max(float(self.energy_threshold), adaptive)

    def _percentile(self, sorted_values: List[int], percentile: float) -> float:
        if not sorted_values:
            return 0.0
        percentile = max(0.0, min(100.0, percentile))
        index = int(round((len(sorted_values) - 1) * percentile / 100.0))
        return float(sorted_values[index])

    def _split_long_segment(self, total_ms: int) -> List[DetectedSegment]:
        if self.max_segment_ms <= 0:
            return [DetectedSegment(start_ms=0, end_ms=total_ms)]
        if total_ms <= self.max_segment_ms:
            return [DetectedSegment(start_ms=0, end_ms=total_ms)]

        segments: List[DetectedSegment] = []
        start_ms = 0
        while start_ms < total_ms:
            end_ms = min(total_ms, start_ms + self.max_segment_ms)
            segments.append(DetectedSegment(start_ms=start_ms, end_ms=end_ms))
            start_ms = end_ms
        return segments
