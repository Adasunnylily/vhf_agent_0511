from __future__ import annotations

from typing import Dict, List


ASR_COMPARE_OPTIONS: List[Dict[str, object]] = [
    {
        "provider": "Qwen ASR",
        "model": "qwen3-asr-flash / qwen3-asr-flash-filetrans",
        "fit_for": "中文海事通话主链、短音频直传、长音频异步批处理",
        "strengths": [
            "OpenAI 兼容接入快",
            "支持 26 种语言",
            "支持词级时间戳",
            "支持情绪检测与上下文偏置",
        ],
        "limits": [
            "Flash OpenAI 兼容模式建议 10MB 以内",
            "长音频需要改走 DashScope 异步",
        ],
        "local_deploy": "可切换到开源 Qwen3-ASR 本地部署",
        "official_url": "https://www.alibabacloud.com/help/en/model-studio/qwen-asr-api-reference",
        "recommended_role": "主 ASR 候选",
    },
    {
        "provider": "Volcengine Seed-ASR",
        "model": "大模型录音文件极速版 / bigmodel flash",
        "fit_for": "长录音快速转写、批量选型、中文口语与多说话人录音",
        "strengths": [
            "单请求直接返回结果",
            "单文件可到 2h / 100MB",
            "返回 utterance / word 级结果",
            "平台支持热词与替换词",
        ],
        "limits": [
            "需要火山专有鉴权头",
            "更适合文件识别，不是页面内即时低时延主链",
        ],
        "local_deploy": "当前以云 API 为主",
        "official_url": "https://www.volcengine.com/docs/6561/1631584",
        "recommended_role": "长音频对比候选",
    },
    {
        "provider": "OpenAI Speech to Text",
        "model": "gpt-4o-transcribe / gpt-4o-mini-transcribe / diarize / whisper-1",
        "fit_for": "高质量转写、多模型对比、说话人 diarize 实验",
        "strengths": [
            "转写模型谱系完整",
            "有内置 diarize 候选",
            "适合和现有 LLM 流程统一",
        ],
        "limits": [
            "按 token 计费，长音频成本敏感",
            "Whisper 对海事专名仍需热词和后处理",
        ],
        "local_deploy": "whisper 可本地，4o 系列以云 API 为主",
        "official_url": "https://platform.openai.com/docs/guides/speech-to-text",
        "recommended_role": "高质量对照组",
    },
    {
        "provider": "Gemini Audio",
        "model": "gemini-2.5-flash / gemini-3.5-flash",
        "fit_for": "音频理解、模糊风险辅助判断、非纯转写链路",
        "strengths": [
            "最长单次可处理 9.5 小时音频",
            "能理解非语音音频事件",
            "适合作为 ASR 之外的辅助理解通路",
        ],
        "limits": [
            "更偏音频理解，不是专用 ASR 引擎",
            "要靠 prompt 稳住逐字转写风格",
        ],
        "local_deploy": "以云 API 为主",
        "official_url": "https://ai.google.dev/gemini-api/docs/audio",
        "recommended_role": "风险辅助理解",
    },
]


def list_asr_compare_options() -> List[Dict[str, object]]:
    return ASR_COMPARE_OPTIONS
