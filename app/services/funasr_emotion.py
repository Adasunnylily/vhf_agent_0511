from __future__ import annotations

import re
from typing import List

FUNASR_RICH_TOKEN_PATTERN = re.compile(r"<\|([A-Za-z_]+)\|>")

FUNASR_EMOTION_LABELS = {
    "HAPPY": "高兴",
    "SAD": "悲伤",
    "ANGRY": "愤怒",
    "FEARFUL": "恐惧/焦虑",
    "DISGUSTED": "厌恶",
    "SURPRISED": "惊讶",
}

FUNASR_EVENT_LABELS = {
    "Laughter": "笑声",
    "Cry": "哭泣",
    "Cough": "咳嗽",
    "Sneeze": "打喷嚏",
    "Applause": "鼓掌",
}


def extract_funasr_emotion_tags(raw_text: str) -> List[str]:
    """Parse SenseVoice rich-transcription tokens before postprocess strips them."""
    if not raw_text:
        return []

    seen = set()
    tags: List[str] = []
    for token in FUNASR_RICH_TOKEN_PATTERN.findall(raw_text):
        label = FUNASR_EMOTION_LABELS.get(token)
        if not label or token in seen or token == "NEUTRAL":
            continue
        seen.add(token)
        tags.append(f"{label}({token})")
    return tags


def extract_funasr_event_tags(raw_text: str) -> List[str]:
    if not raw_text:
        return []

    seen = set()
    tags: List[str] = []
    for token in FUNASR_RICH_TOKEN_PATTERN.findall(raw_text):
        label = FUNASR_EVENT_LABELS.get(token)
        if not label or token in seen:
            continue
        seen.add(token)
        tags.append(f"{label}({token})")
    return tags


def format_funasr_emotion_evidence(emotion_tags: List[str], event_tags: List[str] | None = None) -> List[str]:
    evidence: List[str] = []
    if emotion_tags:
        evidence.append(f"FunASR情感标签: {', '.join(emotion_tags)}")
    if event_tags:
        evidence.append(f"FunASR事件标签: {', '.join(event_tags)}")
    return evidence
