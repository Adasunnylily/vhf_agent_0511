from __future__ import annotations

import contextlib
from dataclasses import asdict, dataclass
import os
import shutil
import subprocess
import wave
from pathlib import Path

from app.config import settings
from app.services.storage import LocalStorage


@dataclass
class PreprocessResult:
    original_path: str
    normalized_path: str
    processed_path: str
    denoise_enabled: bool
    denoise_filter_chain: str

    def to_dict(self) -> dict:
        return asdict(self)


class AudioPreprocessor:
    def __init__(self, storage: LocalStorage) -> None:
        self.storage = storage

    def prepare(self, file_path: Path, enable_denoise: bool = False) -> PreprocessResult:
        normalized = self.normalize_to_wav(file_path)
        processed = normalized
        if enable_denoise:
            processed = self.enhance_wav(normalized)
        return PreprocessResult(
            original_path=str(file_path),
            normalized_path=str(normalized),
            processed_path=str(processed),
            denoise_enabled=enable_denoise,
            denoise_filter_chain=settings.denoise_filter_chain if enable_denoise else "",
        )

    def normalize_to_wav(self, file_path: Path) -> Path:
        if self._is_standard_wav(file_path):
            return file_path

        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError(
                "未找到 ffmpeg。当前服务需要 ffmpeg 将输入统一转换为 16k mono PCM wav。"
            )

        target = self.storage.allocate_normalized_path(".wav")
        cmd = [
            ffmpeg,
            "-y",
            "-i",
            str(file_path),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-acodec",
            "pcm_s16le",
            str(target),
        ]
        try:
            subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self._safe_env(),
            )
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode("utf-8", errors="ignore")
            raise RuntimeError(f"ffmpeg 预处理失败: {stderr}") from exc
        return target

    def enhance_wav(self, file_path: Path) -> Path:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError(
                "未找到 ffmpeg。当前服务需要 ffmpeg 执行降噪/增强。"
            )
        target = self.storage.allocate_enhanced_path(".wav")
        cmd = [
            ffmpeg,
            "-y",
            "-i",
            str(file_path),
            "-af",
            settings.denoise_filter_chain,
            "-ac",
            "1",
            "-ar",
            "16000",
            "-acodec",
            "pcm_s16le",
            str(target),
        ]
        try:
            subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self._safe_env(),
            )
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode("utf-8", errors="ignore")
            raise RuntimeError(f"ffmpeg 降噪增强失败: {stderr}") from exc
        return target

    def _is_standard_wav(self, file_path: Path) -> bool:
        if file_path.suffix.lower() != ".wav":
            return False
        try:
            with contextlib.closing(wave.open(str(file_path), "rb")) as wav_file:
                return (
                    wav_file.getframerate() == 16000
                    and wav_file.getnchannels() == 1
                    and wav_file.getsampwidth() == 2
                )
        except Exception:
            return False

    def _safe_env(self) -> dict:
        env = os.environ.copy()
        value = env.get("OMP_NUM_THREADS", "").strip()
        if value:
            try:
                if int(value) <= 0:
                    env["OMP_NUM_THREADS"] = "1"
            except Exception:
                env["OMP_NUM_THREADS"] = "1"
        return env
