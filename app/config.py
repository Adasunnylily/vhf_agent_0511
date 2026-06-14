import os
from dataclasses import dataclass
from pathlib import Path

from app.services.asr_prompts import DEFAULT_ASR_EVAL_PROMPT


_ASR_EVAL_PROMPT = os.getenv("VHF_ASR_EVAL_PROMPT", DEFAULT_ASR_EVAL_PROMPT)


@dataclass(frozen=True)
class Settings:
    project_name: str = "VHF Agent Backend MVP"
    version: str = "0.1.0"
    data_dir: Path = Path(os.getenv("VHF_DATA_DIR", "data"))
    upload_dir: Path = data_dir / "uploads"
    normalized_dir: Path = data_dir / "normalized"
    enhanced_dir: Path = data_dir / "enhanced"
    clip_dir: Path = data_dir / "clips"
    event_dir: Path = data_dir / "events"
    max_inline_events: int = 100
    vad_frame_ms: int = int(os.getenv("VHF_VAD_FRAME_MS", "30"))
    vad_silence_ms: int = int(os.getenv("VHF_VAD_SILENCE_MS", "900"))
    vad_min_speech_ms: int = int(os.getenv("VHF_VAD_MIN_SPEECH_MS", "600"))
    vad_max_segment_ms: int = int(os.getenv("VHF_VAD_MAX_SEGMENT_MS", "8000"))
    default_channel_id: str = os.getenv("VHF_DEFAULT_CHANNEL_ID", "vhf_demo_01")
    asr_model: str = os.getenv("VHF_ASR_MODEL", "paraformer-v2")
    asr_provider: str = os.getenv("VHF_ASR_PROVIDER", "dashscope_paraformer")
    dashscope_asr_api_key_env: str = os.getenv("VHF_DASHSCOPE_API_KEY_ENV", "DASHSCOPE_API_KEY")
    asr_diarization_enabled: bool = os.getenv("VHF_ASR_DIARIZATION_ENABLED", "1") == "1"
    asr_speaker_count: int = int(os.getenv("VHF_ASR_SPEAKER_COUNT", "2"))
    asr_phrase_id: str = os.getenv("VHF_ASR_PHRASE_ID", "")
    asr_vocabulary_id: str = os.getenv("VHF_ASR_VOCABULARY_ID", "")
    asr_hotwords_path: Path = Path(
        os.getenv("VHF_ASR_HOTWORDS_PATH", str(data_dir / "hotwords" / "nbzh_hotwords.txt"))
    )
    asr_vad_model: str = os.getenv("VHF_ASR_VAD_MODEL", "fsmn-vad")
    asr_punc_model: str = os.getenv("VHF_ASR_PUNC_MODEL", "")
    asr_device: str = os.getenv("VHF_ASR_DEVICE", "cuda:0")
    asr_hub: str = os.getenv("VHF_ASR_HUB", "ms")
    asr_batch_size_s: int = int(os.getenv("VHF_ASR_BATCH_SIZE_S", "30"))
    asr_model_revision: str = os.getenv("VHF_ASR_MODEL_REVISION", "")
    asr_language: str = os.getenv("VHF_ASR_LANGUAGE", "zh")
    asr_use_itn: bool = os.getenv("VHF_ASR_USE_ITN", "1") == "1"
    qwen_asr_api_key_env: str = os.getenv("VHF_QWEN_ASR_API_KEY_ENV", "DASHSCOPE_API_KEY")
    qwen_asr_base_url: str = os.getenv(
        "VHF_QWEN_ASR_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    qwen_asr_timeout_s: int = int(os.getenv("VHF_QWEN_ASR_TIMEOUT_S", "120"))
    asr_eval_prompt: str = _ASR_EVAL_PROMPT
    qwen_asr_prompt: str = os.getenv("VHF_QWEN_ASR_PROMPT", _ASR_EVAL_PROMPT)
    asr_vad_max_single_segment_time: int = int(
        os.getenv("VHF_ASR_VAD_MAX_SINGLE_SEGMENT_TIME", "30000")
    )
    force_full_file_transcribe: bool = os.getenv("VHF_FORCE_FULL_FILE_TRANSCRIBE", "0") == "1"
    stream_simulation_speed: float = float(os.getenv("VHF_STREAM_SIMULATION_SPEED", "8.0"))
    streaming_model: str = os.getenv("VHF_STREAMING_MODEL", "paraformer-zh-streaming")
    streaming_chunk_size: str = os.getenv("VHF_STREAMING_CHUNK_SIZE", "0,10,5")
    streaming_encoder_chunk_look_back: int = int(
        os.getenv("VHF_STREAMING_ENCODER_CHUNK_LOOK_BACK", "4")
    )
    streaming_decoder_chunk_look_back: int = int(
        os.getenv("VHF_STREAMING_DECODER_CHUNK_LOOK_BACK", "1")
    )
    denoise_filter_chain: str = os.getenv(
        "VHF_DENOISE_FILTER_CHAIN",
        "highpass=f=120,lowpass=f=3800,afftdn=nf=-25",
    )
    amap_key: str = os.getenv("AMAP_KEY", "")
    entity_resolver_enabled: bool = os.getenv("VHF_ENTITY_RESOLVER_ENABLED", "1") == "1"
    entity_lexicon_path: Path = Path(
        os.getenv("VHF_ENTITY_LEXICON_PATH", str(data_dir / "lexicon_corrections.json"))
    )

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.normalized_dir.mkdir(parents=True, exist_ok=True)
        self.enhanced_dir.mkdir(parents=True, exist_ok=True)
        self.clip_dir.mkdir(parents=True, exist_ok=True)
        self.event_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()


def uses_cloud_clip_asr(provider: str) -> bool:
    """Cloud APIs that transcribe uploaded clips (Qwen chat-audio or DashScope Recognition)."""
    return (provider or "").strip().lower() in {"qwen_api", "dashscope_paraformer", "paraformer_v2"}


def uses_dashscope_recognition(provider: str) -> bool:
    return (provider or "").strip().lower() in {"dashscope_paraformer", "paraformer_v2"}
