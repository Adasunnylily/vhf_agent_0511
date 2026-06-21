from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Optional

from app.config import settings


def synthesize_speech(text: str, *, voice: Optional[str] = None) -> Path:
    content = (text or "").strip()
    if not content:
        raise ValueError("播报文本不能为空")

    model = os.getenv("VHF_TTS_MODEL", "sambert-zhichu-v1")
    sample_rate = int(os.getenv("VHF_TTS_SAMPLE_RATE", "16000"))
    voice_name = voice or os.getenv("VHF_TTS_VOICE", "zhichu")
    api_key_env = os.getenv("VHF_TTS_API_KEY_ENV", settings.dashscope_asr_api_key_env)
    api_key = os.getenv(api_key_env, "")
    if not api_key:
        raise RuntimeError(f"未配置 TTS API Key（环境变量 {api_key_env}）")

    out_dir = settings.data_dir / "tts"
    out_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(f"{model}:{voice_name}:{content}".encode("utf-8")).hexdigest()[:16]
    out_path = out_dir / f"tts_{digest}.wav"
    if out_path.is_file() and out_path.stat().st_size > 1024:
        return out_path

    import dashscope
    from dashscope.audio.tts import SpeechSynthesizer

    dashscope.api_key = api_key
    result = SpeechSynthesizer.call(
        model=model,
        text=content,
        voice=voice_name,
        sample_rate=sample_rate,
        format="wav",
    )
    audio = result.get_audio_data() if hasattr(result, "get_audio_data") else None
    if not audio:
        message = getattr(result, "message", None) or getattr(result, "code", None) or "TTS 未返回音频"
        raise RuntimeError(f"TTS 合成失败：{message}")
    out_path.write_bytes(audio)
    return out_path
