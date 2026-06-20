from __future__ import annotations

import contextlib
import wave
from array import array
from pathlib import Path


def pcm_rms(pcm_bytes: bytes) -> float:
    samples = array("h")
    samples.frombytes(pcm_bytes[: len(pcm_bytes) - len(pcm_bytes) % 2])
    if not samples:
        return 0.0
    return (sum(int(sample) * int(sample) for sample in samples) / len(samples)) ** 0.5


def write_pcm_wav(path: Path, pcm_bytes: bytes, sample_rate: int = 16000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_bytes)


def slice_wav_segment(
    source_path: Path,
    target_path: Path,
    start_ms: int,
    end_ms: int,
) -> Path:
    with contextlib.closing(wave.open(str(source_path), "rb")) as src:
        params = src.getparams()
        frame_rate = src.getframerate()
        start_frame = max(0, int(start_ms * frame_rate / 1000))
        end_frame = max(start_frame, int(end_ms * frame_rate / 1000))
        src.setpos(start_frame)
        frames = src.readframes(end_frame - start_frame)

    with contextlib.closing(wave.open(str(target_path), "wb")) as dst:
        dst.setparams(params)
        dst.writeframes(frames)

    return target_path
