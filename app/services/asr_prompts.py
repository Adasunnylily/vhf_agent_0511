from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

# 所有 ASR 对比/评测场景共用的听写约束（支持 prompt 的模型应使用同一份）。
DEFAULT_ASR_EVAL_PROMPT = """这是一段宁波海事交管VHF海事通信音频。
你是海事VHF通话听写助手，场景为宁波舟山港、北仑山、穿山、大榭、梅山等港区的船岸/船船通信。

请优先识别以下信息：
1. 船名、呼号、MMSI、拖轮/引航船/货船名称；
2. 地名、水域、码头、泊位、锚地、警戒区、航道、报告线；
3. 业务动作：靠泊、靠妥、抛锚、起锚、锚离底、离泊、解缆、备车、开航、穿越、追越、掉头、加车、慢车、避让；
4. 风险词：冒烟、着火、碰撞、搁浅、失控、失火、进水、人员落水、故障、危险品、求救、Mayday。

要求：
- 语言只可能是中文，夹杂少量英文船名、呼号、MAYDAY、VTS、ETA、AIS等海事术语；绝不会出现日语或韩语。
- 请逐字转写原话，不要翻译，不要总结，不要补充。
- 只输出转写文本，不要解释。
- 保留船名、地名、泊位号、锚地、频道号和数字。
- “幺、两、洞、拐、勾”等VHF数字读法请尽量还原为阿拉伯数字。
- 如果听到交管回复，如“请讲、收到、注意安全、再会”，请准确保留。
- 不要生成表情、无关符号或与语音无关的内容。
- 常见词包括：交管、汇报、船舶动态、加车、靠泊、离泊、抛锚、进港、出港、碰撞、搁浅、进水、失火、人员落水、保持守听。"""

# DashScope Recognition 在当前账号下可用的是 realtime 系列，paraformer-v2 需映射。
PARAFORMER_MODEL_ALIASES = {
    "paraformer-v2": "paraformer-realtime-v2",
}

DEFAULT_VOCABULARY_WEIGHT = 4
DEFAULT_VOCABULARY_PREFIX = "vhfnbzh"
MAX_DASHSCOPE_VOCABULARY_SIZE = 500
MAX_QWEN_PROMPT_HOTWORDS = 50


def resolve_eval_prompt() -> str:
    return os.getenv("VHF_ASR_EVAL_PROMPT", DEFAULT_ASR_EVAL_PROMPT).strip() or DEFAULT_ASR_EVAL_PROMPT


def resolve_paraformer_sample_rate(model: str, fallback: int = 16000) -> int:
    key = model.strip().lower()
    if "8k" in key:
        return 8000
    return fallback


def resolve_paraformer_model(model: str) -> str:
    key = model.strip()
    return PARAFORMER_MODEL_ALIASES.get(key, key)


def resolve_dashscope_api_key(*, env_name: str = "DASHSCOPE_API_KEY") -> str:
    """读取并校验 DashScope API Key，避免非 ASCII 字符导致 HTTP 头编码失败。"""
    raw = os.getenv(env_name, "")
    api_key = raw.strip().strip("'\"")
    if not api_key:
        raise RuntimeError(f"缺少环境变量 {env_name}")

    for index, char in enumerate(api_key):
        if ord(char) > 127:
            raise RuntimeError(
                f"{env_name} 含非 ASCII 字符（位置 {index}: {char!r}）。"
                "HTTP Authorization 头只能使用 ASCII，请检查 .env 或 shell 里是否混入了中文标签/空格。"
                "若 shell 已 export 了错误值，请 unset 后重试，或直接用 .env 中的 sk- 开头密钥。"
            )
    if not api_key.startswith("sk-"):
        raise RuntimeError(
            f"{env_name} 格式异常，应以 sk- 开头；当前前缀: {api_key[:8]!r}"
        )
    return api_key


def ensure_dashscope_api_key_in_env(*, env_name: str = "DASHSCOPE_API_KEY") -> str:
    """解析 API Key 并写回环境变量，避免 shell 中污染的非 ASCII 值影响后续请求。"""
    api_key = resolve_dashscope_api_key(env_name=env_name)
    os.environ[env_name] = api_key
    return api_key


def load_project_env(
    env_path: Path,
    *,
    override_keys: tuple[str, ...] = ("DASHSCOPE_API_KEY",),
) -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if not key:
            continue
        if key in override_keys or key not in os.environ:
            os.environ[key] = value


def default_hotwords_path() -> Path:
    return Path(os.getenv("VHF_ASR_HOTWORDS_PATH", "data/hotwords/nbzh_hotwords.txt"))


def default_vocabulary_cache_path() -> Path:
    return Path(os.getenv("VHF_ASR_VOCABULARY_CACHE", "data/hotwords/dashscope_vocabulary_id.txt"))


def load_eval_hotwords(hotwords_path: Optional[Path] = None, limit: int = MAX_QWEN_PROMPT_HOTWORDS) -> List[str]:
    path = hotwords_path or default_hotwords_path()
    if not path.exists():
        return []
    from app.services.asr import load_hotword_lines

    return load_hotword_lines(path, limit=limit)


def infer_hotword_lang(text: str) -> str:
    if all(ord(char) < 128 for char in text.replace(" ", "")):
        return "en"
    return "zh"


def validate_hotword_text(text: str) -> bool:
    cleaned = text.strip()
    if not cleaned:
        return False
    if all(ord(char) < 128 for char in cleaned):
        return len(cleaned.split()) <= 7
    return len(cleaned) <= 15


def build_dashscope_vocabulary_entries(
    hotwords_path: Optional[Path] = None,
    *,
    weight: int = DEFAULT_VOCABULARY_WEIGHT,
    limit: int = MAX_DASHSCOPE_VOCABULARY_SIZE,
) -> List[Dict[str, Any]]:
    """将 nbzh_hotwords.txt 转为 DashScope 热词 JSON 数组。"""
    entries: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for word in load_eval_hotwords(hotwords_path, limit=limit):
        text = word.strip()
        key = text.lower()
        if not text or key in seen or not validate_hotword_text(text):
            continue
        seen.add(key)
        item: Dict[str, Any] = {"text": text, "weight": weight}
        lang = infer_hotword_lang(text)
        if lang:
            item["lang"] = lang
        entries.append(item)
    return entries


def resolve_dashscope_vocabulary_id(*, target_model: Optional[str] = None) -> str:
    explicit = os.getenv("VHF_ASR_VOCABULARY_ID", "").strip()
    if explicit:
        return explicit
    cache_path = default_vocabulary_cache_path()
    if not cache_path.exists():
        return ""
    cached_model = ""
    cached_id = ""
    for line in cache_path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        if raw.startswith("model="):
            cached_model = raw.split("=", 1)[1].strip()
            continue
        if raw.startswith("id="):
            cached_id = raw.split("=", 1)[1].strip()
            continue
        if not cached_id:
            cached_id = raw
    if target_model and cached_model and cached_model != target_model:
        return ""
    return cached_id


def save_dashscope_vocabulary_id(vocabulary_id: str, *, target_model: str) -> Path:
    cache_path = default_vocabulary_cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        "\n".join(
            [
                "# DashScope 热词列表 ID，由 scripts/sync_dashscope_vocabulary.py 生成",
                f"model={target_model}",
                f"id={vocabulary_id}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return cache_path


def _vocabulary_status(query_result: Any) -> str:
    if isinstance(query_result, dict):
        return str(query_result.get("status", ""))
    if isinstance(query_result, list) and query_result:
        first = query_result[0]
        if isinstance(first, dict):
            return str(first.get("status", ""))
    return ""


def sync_dashscope_vocabulary(
    *,
    target_model: Optional[str] = None,
    prefix: Optional[str] = None,
    hotwords_path: Optional[Path] = None,
    weight: int = DEFAULT_VOCABULARY_WEIGHT,
    replace_existing: bool = False,
) -> str:
    """创建 DashScope 热词列表并返回 vocabulary_id。"""
    try:
        import dashscope
        from dashscope.audio.asr.vocabulary import VocabularyService
    except ImportError as exc:
        raise RuntimeError("缺少 dashscope SDK，请安装: pip install dashscope") from exc

    api_key = resolve_dashscope_api_key()
    dashscope.api_key = api_key
    dashscope.base_http_api_url = os.getenv(
        "DASHSCOPE_HTTP_BASE_URL",
        "https://dashscope.aliyuncs.com/api/v1",
    )
    dashscope.base_websocket_api_url = os.getenv(
        "DASHSCOPE_WS_BASE_URL",
        "wss://dashscope.aliyuncs.com/api-ws/v1/inference",
    )

    model = resolve_paraformer_model(
        target_model or os.getenv("VHF_ASR_VOCABULARY_TARGET_MODEL", os.getenv("VHF_ASR_MODEL", "paraformer-v2"))
    )
    vocabulary = build_dashscope_vocabulary_entries(hotwords_path, weight=weight)
    if not vocabulary:
        raise RuntimeError("没有可用的热词，请检查热词文件格式与长度限制。")

    service = VocabularyService()
    vocab_prefix = (prefix or os.getenv("VHF_ASR_VOCABULARY_PREFIX", DEFAULT_VOCABULARY_PREFIX)).strip()

    existing_id = resolve_dashscope_vocabulary_id(target_model=model)
    if existing_id and not replace_existing:
        status = _vocabulary_status(service.query_vocabulary(existing_id))
        if status.upper() == "OK":
            return existing_id

    vocabulary_id = service.create_vocabulary(
        target_model=model,
        prefix=vocab_prefix,
        vocabulary=vocabulary,
    )
    status = _vocabulary_status(service.query_vocabulary(vocabulary_id))
    if status.upper() != "OK":
        raise RuntimeError(f"DashScope 热词列表创建后状态异常: {status}")

    save_dashscope_vocabulary_id(vocabulary_id, target_model=model)
    return vocabulary_id


def format_hotwords_for_prompt(hotwords: List[str]) -> str:
    if not hotwords:
        return ""
    return "热词：" + "、".join(hotwords)


def build_qwen_eval_prompt(
    *,
    base_prompt: Optional[str] = None,
    hotwords_path: Optional[Path] = None,
) -> str:
    parts = [(base_prompt or resolve_eval_prompt()).strip()]
    hotwords = load_eval_hotwords(hotwords_path, limit=MAX_QWEN_PROMPT_HOTWORDS)
    hotword_line = format_hotwords_for_prompt(hotwords)
    if hotword_line:
        parts.append(hotword_line)
    return "\n".join(part for part in parts if part)


def build_volc_corpus(*, streaming: bool = False) -> Dict[str, Any]:
    """豆包/火山 ASR 不支持文本 prompt，用热词表 + dialog context 近似对齐。"""
    import json

    corpus: Dict[str, Any] = {}
    table_id = os.getenv("VOLCENGINE_ASR_BOOSTING_TABLE_ID", "").strip()
    if table_id:
        corpus["boosting_table_id"] = table_id

    context_data: List[Dict[str, str]] = []
    prompt = resolve_eval_prompt()
    if prompt:
        context_data.append({"text": prompt[:800]})
    for word in load_eval_hotwords(limit=30):
        context_data.append({"text": word})
    if context_data:
        context_obj = {
            "context_type": "dialog_ctx",
            "context_data": context_data,
        }
        # 流式 WebSocket 接口要求 context 为 JSON 字符串。
        corpus["context"] = json.dumps(context_obj, ensure_ascii=False) if streaming else context_obj
    return corpus


def build_volc_request_options(*, streaming: bool = False) -> Dict[str, Any]:
    request: Dict[str, Any] = {
        "model_name": os.getenv("VOLCENGINE_ASR_MODEL_NAME", "bigmodel"),
        "enable_itn": True,
        "enable_punc": True,
    }
    if streaming:
        request["show_utterances"] = True
    corpus = build_volc_corpus(streaming=streaming)
    if corpus:
        request["corpus"] = corpus
    return request
