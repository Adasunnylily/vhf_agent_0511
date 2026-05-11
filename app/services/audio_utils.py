from __future__ import annotations

import contextlib
import wave
from pathlib import Path


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
