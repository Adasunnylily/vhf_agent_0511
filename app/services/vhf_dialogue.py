from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional


SHIP_NAME_PATTERN = re.compile(r"([\u4e00-\u9fa5]{2,8}(?:\d{1,4}|幺五|一五|1五))")
KNOWN_SHIP_NAMES = ["宁远梅山", "湘远15"]


@dataclass(frozen=True)
class VHFDialogueResult:
    original_text: str
    resolved_text: str
    dialogue_review_text: str


def postprocess_vhf_dialogue(
    text: str,
    asr_sentences: Optional[List[dict]] = None,
) -> VHFDialogueResult:
    resolved = repair_vhf_text(text)
    dialogue_review_text = build_vhf_dialogue_review(resolved, asr_sentences=asr_sentences)
    return VHFDialogueResult(
        original_text=text,
        resolved_text=resolved,
        dialogue_review_text=dialogue_review_text,
    )


def repair_vhf_text(text: str) -> str:
    resolved = text or ""
    replacements = [
        (r"什么中山交管", "宁波舟山交管"),
        (r"中山交管", "舟山交管"),
        (r"宁远[，, ]?眉山", "宁远梅山"),
        (r"宁远煤山", "宁远梅山"),
        (r"北龙二区", "北仑二期"),
        (r"通达七号泊位", "通达7号泊位"),
        (r"谢谢教官", "谢谢交管"),
        (r"现在\s*(?:159|幺五|一五|1五|15)", "湘远15"),
        (r"限\s*(?:幺五|一五|1五|15)", "湘远15"),
        (r"湘远\s*(?:幺五|一五|1五)", "湘远15"),
        (r"大榭集装箱码头一号泊位", "大榭集装箱码头1号泊位"),
        (r"散会", "再会"),
    ]
    for pattern, value in replacements:
        resolved = re.sub(pattern, value, resolved)

    resolved = re.sub(r"(?<=湘远15)靠左(?=，?大榭|大榭)", "靠妥", resolved)
    resolved = re.sub(r"宁波交管[，, ]?(湘远15)(?:[，, ]?请讲)?", r"宁波交管，\1叫。请讲", resolved)
    resolved = re.sub(r"(湘远15)靠妥[，, ]?(大榭)", r"\1靠妥\2", resolved)
    resolved = re.sub(r"([。！？])+", r"\1", resolved)
    return resolved.strip()


def build_vhf_dialogue_review(
    text: str,
    asr_sentences: Optional[List[dict]] = None,
) -> str:
    if asr_sentences:
        rows: List[str] = []
        for sentence in asr_sentences:
            content = str(sentence.get("text") or "").strip()
            if not content:
                continue
            speaker = sentence.get("speaker_id", sentence.get("speaker"))
            label = f"说话人{speaker}" if speaker not in (None, "") else "待确认说话人"
            rows.append(f"{label}：{content}。")
        if rows:
            return "\n".join(rows)

    sentences = _split_sentences(text)
    if not sentences:
        return "等待 ASR 后生成对话轮次复核模板"

    last_ship = _extract_ship_name(text)
    rows: List[str] = []
    for sentence in sentences:
        speaker = _infer_speaker(sentence, last_ship)
        ship = _extract_ship_name(sentence)
        if ship:
            last_ship = ship
            if speaker.startswith("疑似船方"):
                speaker = ship
        rows.append(f"{speaker}：{sentence}。")
    return "\n".join(rows)


def _split_sentences(text: str) -> List[str]:
    normalized = re.sub(r"[。！？；;\n]+", "。", text or "")
    return [part.strip(" ，,。") for part in normalized.split("。") if part.strip(" ，,。")]


def _extract_ship_name(text: str) -> str:
    for name in KNOWN_SHIP_NAMES:
        if name in (text or ""):
            return name
    matches = SHIP_NAME_PATTERN.findall(text or "")
    for item in matches:
        if any(stop in item for stop in ["宁波交管", "舟山交管", "大榭集装箱", "北仑", "通达"]):
            continue
        return item
    return ""


def _infer_speaker(sentence: str, last_ship: str) -> str:
    if re.search(r"(谢谢交管|谢谢|哎，好的|好的)", sentence) and last_ship:
        return last_ship
    if re.fullmatch(r"(请讲|收到|收到，再会|注意安全|好的，注意安全|再会)", sentence):
        return "宁波交管"
    if re.search(r"^(收到|请讲|注意安全|好，下一个)", sentence):
        return "宁波交管"
    ship = _extract_ship_name(sentence)
    if ship and re.search(r"(叫|报告|申请|靠妥|靠泊|离泊|抛锚|起锚|开航)", sentence):
        return ship
    if re.search(r"(交管|向您报告|向你报告|申请|靠妥|靠泊|离泊|谢谢交管)", sentence):
        return last_ship or "疑似船方A"
    return "待确认说话人"
