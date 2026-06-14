from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, List, Optional


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
    *,
    sentence_resolver: Optional[Callable[[str], str]] = None,
    map_speaker_roles: bool = False,
) -> VHFDialogueResult:
    resolved = repair_vhf_text(text)
    dialogue_sentences = asr_sentences
    if asr_sentences:
        dialogue_sentences = _prepare_diarization_sentences(asr_sentences, sentence_resolver)
    dialogue_review_text = build_vhf_dialogue_review(
        resolved,
        asr_sentences=dialogue_sentences,
        map_speaker_roles=map_speaker_roles,
    )
    return VHFDialogueResult(
        original_text=text,
        resolved_text=resolved,
        dialogue_review_text=dialogue_review_text,
    )


def _prepare_diarization_sentences(
    asr_sentences: List[dict],
    sentence_resolver: Optional[Callable[[str], str]] = None,
) -> List[dict]:
    prepared: List[dict] = []
    for sentence in asr_sentences:
        content = str(sentence.get("text") or "").strip()
        if not content:
            continue
        content = repair_vhf_text(content)
        if sentence_resolver is not None:
            content = sentence_resolver(content)
        prepared.append({**sentence, "text": content})
    return prepared


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
    *,
    map_speaker_roles: bool = False,
) -> str:
    if asr_sentences:
        if map_speaker_roles:
            return _build_role_mapped_dialogue_review(asr_sentences)
        rows: List[str] = []
        for sentence in asr_sentences:
            content = str(sentence.get("text") or "").strip()
            if not content:
                continue
            speaker = sentence.get("speaker_id", sentence.get("speaker"))
            label = format_diarization_speaker_label(speaker)
            rows.append(f"{label}：{content}。")
        if rows:
            return "\n".join(rows)

    return _build_role_mapped_dialogue_review(_sentences_from_text(text))


def _sentences_from_text(text: str) -> List[dict]:
    return [{"text": sentence} for sentence in _split_sentences(text)]


def _build_role_mapped_dialogue_review(asr_sentences: List[dict]) -> str:
    last_ship = ""
    last_speaker = ""
    pending_reply_speaker = ""
    rows: List[str] = []
    for sentence in asr_sentences:
        content = str(sentence.get("text") or "").strip()
        if not content:
            continue
        speaker = _infer_speaker(content, last_ship, last_speaker, pending_reply_speaker)
        ship = _extract_ship_name(content)
        if ship:
            last_ship = ship
            if speaker.startswith("疑似船方"):
                speaker = ship
        rows.append(f"{speaker}：{content}。")
        relay_target = _extract_relay_target(content)
        if relay_target:
            pending_reply_speaker = relay_target
        elif pending_reply_speaker and speaker == pending_reply_speaker:
            pending_reply_speaker = ""
        if speaker != "待确认说话人":
            last_speaker = speaker
    if not rows:
        return "等待 ASR 后生成对话轮次复核模板"
    return "\n".join(rows)


def format_diarization_speaker_label(speaker: object) -> str:
    if speaker in (None, ""):
        return "待确认说话人"
    return f"说话人{speaker}"


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


def _infer_speaker(
    sentence: str,
    last_ship: str,
    last_speaker: str = "",
    pending_reply_speaker: str = "",
) -> str:
    normalized = sentence.strip(" ，,。")
    if _is_vts_control_sentence(normalized):
        return "宁波交管"

    if pending_reply_speaker and _is_short_radio_reply(normalized):
        return pending_reply_speaker

    relay_caller = _extract_relay_caller(normalized)
    if relay_caller:
        return relay_caller

    if _is_ship_ack_to_vts(normalized):
        return last_ship or _last_ship_speaker(last_speaker) or "疑似船方A"

    ship = _extract_ship_name(normalized)
    if ship and re.search(r"(宁波交管|舟山交管|交管)", normalized):
        return ship
    if ship and _looks_like_ship_self_statement(normalized):
        return ship

    if _looks_like_ship_business_statement(normalized):
        return ship or last_ship or _last_ship_speaker(last_speaker) or "疑似船方A"

    if _looks_like_vts_instruction(normalized):
        return "宁波交管"

    if re.search(r"(我加车了|我减速了|我转向了|我避让|我知道了|明白)", normalized):
        return last_ship or _last_ship_speaker(last_speaker) or "疑似船方A"

    return "待确认说话人"


def _is_vts_control_sentence(sentence: str) -> bool:
    return bool(
        re.fullmatch(
            r"(请讲|收到|收到[,，]?再会|注意安全|好[,，]?注意安全|好的[,，]?注意安全|再会|好[,，]?下一个.*|下一个.*)",
            sentence,
        )
    )


def _looks_like_vts_instruction(sentence: str) -> bool:
    return bool(
        re.search(
            r"^(请讲|收到[,，]?再会|注意安全|好[,，]?注意安全|好[,，]?下一个|下一个|保持联系|加强联系)",
            sentence,
        )
    )


def _is_ship_ack_to_vts(sentence: str) -> bool:
    return bool(
        re.search(
            r"(谢谢交管|谢谢老师|谢谢[,，]?交管|好的好的[,，]?谢谢|哎[,，]?好的|好的[,，]?收到|明白[,，]?谢谢)",
            sentence,
        )
    )


def _is_short_radio_reply(sentence: str) -> bool:
    return bool(re.fullmatch(r"(哎[,，]?讲|讲|请讲|收到|好的|好|明白)", sentence))


def _looks_like_ship_self_statement(sentence: str) -> bool:
    return bool(re.search(r"(叫|报告|向您报告|向你报告|申请|靠妥|靠泊|离泊|抛锚|起锚|开航|解缆|备车)", sentence))


def _looks_like_ship_business_statement(sentence: str) -> bool:
    return bool(
        re.search(
            r"(交管.*(报告|申请|靠妥|靠泊|离泊|抛锚|起锚|开航|解缆|备车)|向您报告|向你报告|申请|靠妥|靠泊|离泊|抛锚|起锚|开航|解缆|备车)",
            sentence,
        )
    )


def _extract_relay_caller(sentence: str) -> str:
    match = re.search(r"你后面的([\u4e00-\u9fa5A-Za-z0-9]{2,12})叫", sentence)
    if not match:
        return ""
    caller = match.group(1).strip(" ，,。")
    if caller in {"后面", "前面"}:
        return ""
    return caller


def _extract_relay_target(sentence: str) -> str:
    if "你后面的" not in sentence:
        return ""
    prefix = sentence.split("你后面的", 1)[0]
    return _extract_ship_name(prefix)


def _last_ship_speaker(last_speaker: str) -> str:
    if last_speaker and last_speaker not in {"宁波交管", "待确认说话人"} and not last_speaker.startswith("说话人"):
        return last_speaker
    return ""
