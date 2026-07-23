from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from app.services.llm_dialogue import LLMDialogueRefiner


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
    original_text: Optional[str] = None,
    sentence_resolver: Optional[Callable[[str], str]] = None,
    map_speaker_roles: bool = False,
    entity_candidates: Optional[List[Dict[str, object]]] = None,
    dialogue_refiner: Optional[LLMDialogueRefiner] = None,
    use_llm_refiner: bool = True,
    domain_hotwords: Optional[List[str]] = None,
) -> VHFDialogueResult:
    source_text = original_text or text
    resolved = repair_vhf_text(text)
    dialogue_sentences = asr_sentences
    if asr_sentences:
        dialogue_sentences = _prepare_diarization_sentences(asr_sentences, sentence_resolver)
    dialogue_review_text = build_vhf_dialogue_review(
        resolved,
        asr_sentences=dialogue_sentences,
        map_speaker_roles=map_speaker_roles,
    )
    if use_llm_refiner:
        refiner = dialogue_refiner or LLMDialogueRefiner()
        refinement = refiner.refine(
            original_text=source_text,
            rule_resolved_text=resolved,
            rule_dialogue_review_text=dialogue_review_text,
            entity_candidates=entity_candidates,
            asr_sentences=dialogue_sentences,
            domain_hotwords=domain_hotwords,
        )
        if refinement is not None:
            resolved = refinement.corrected_text
            dialogue_review_text = refinement.dialogue_review_text
    resolved, dialogue_review_text = reconcile_event_ship_name(
        source_text,
        resolved,
        dialogue_review_text,
    )
    return VHFDialogueResult(
        original_text=source_text,
        resolved_text=resolved,
        dialogue_review_text=dialogue_review_text,
    )


def reconcile_event_ship_name(
    source_text: str,
    corrected_text: str,
    dialogue_review_text: str,
) -> tuple[str, str]:
    sentences = [item.strip() for item in re.split(r"[\n。！？!?；;]+", source_text) if item.strip()]
    evidence: Dict[str, Dict[str, bool]] = {}
    business_pattern = re.compile(r"(报告|申请|靠泊|靠妥|抛锚|起锚|离泊|开航|解缆|穿越|接码头通知)")
    for sentence in sentences:
        names = SHIP_NAME_PATTERN.findall(sentence)
        for name in names:
            item = evidence.setdefault(name, {"business": False, "short_call": False})
            if business_pattern.search(sentence):
                item["business"] = True
            if len(sentence) <= 20 and "交管" in sentence and not business_pattern.search(sentence):
                item["short_call"] = True

    strong_names = [name for name, item in evidence.items() if item["business"]]
    if len(strong_names) != 1:
        return corrected_text, dialogue_review_text
    strong = strong_names[0]
    strong_prefix = re.sub(r"\d+$", "", strong)
    weak_names = [
        name
        for name, item in evidence.items()
        if name != strong
        and item["short_call"]
        and re.sub(r"\d+$", "", name) == strong_prefix
    ]
    if len(weak_names) != 1:
        return corrected_text, dialogue_review_text
    weak = weak_names[0]
    return corrected_text.replace(weak, strong), dialogue_review_text.replace(weak, strong)


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
    if os.getenv("VHF_DIALOGUE_LEGACY_RULE_REPAIR", "0") == "1":
        from app.services.vhf_legacy_rules import legacy_repair_vhf_text

        return legacy_repair_vhf_text(text)
    return normalize_vhf_text(text)


def normalize_vhf_text(text: str) -> str:
    resolved = text or ""
    resolved = re.sub(r"\s+", " ", resolved)
    resolved = re.sub(r"[。！？!?；;]+", "。", resolved)
    resolved = re.sub(r"，+", "，", resolved)
    resolved = re.sub(r"([。！？])+", r"\1", resolved)
    return resolved.strip(" ，,。")


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
        for content in _split_speaker_turns(str(sentence.get("text") or "")):
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
    normalized = _normalize_punctuation(text)
    return [part.strip(" ，,。") for part in normalized.split("。") if part.strip(" ，,。")]


def _split_speaker_turns(text: str) -> List[str]:
    normalized = _normalize_punctuation(text)
    normalized = re.sub(r"(请讲)(?=(呃|啊|嗯|交管|[\u4e00-\u9fa5A-Za-z0-9]{2,12}))", r"\1。", normalized)
    normalized = re.sub(r"((?:好，)?注意安全)(?=(好的|谢谢|哎|诶|嗯|啊))", r"\1。", normalized)
    normalized = re.sub(r"(收到，再会|再会)(?=(好的|谢谢|哎|诶|嗯|啊))", r"\1。", normalized)
    return [part.strip(" ，,。") for part in normalized.split("。") if part.strip(" ，,。")]


def _normalize_punctuation(text: str) -> str:
    normalized = str(text or "")
    normalized = re.sub(r"[，,]\s*([。！？；;])", r"\1", normalized)
    normalized = re.sub(r"([。！？；;])\s*[，,]", r"\1", normalized)
    normalized = re.sub(r"[。]{2,}", "。", normalized)
    normalized = re.sub(r"[，,]{2,}", "，", normalized)
    normalized = re.sub(r"[。！？；;\n]+", "。", normalized)
    return normalized


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
    if pending_reply_speaker and _is_short_radio_reply(normalized):
        return pending_reply_speaker

    relay_caller = _extract_relay_caller(normalized)
    if relay_caller:
        return relay_caller

    if _is_ship_ack_to_vts(normalized):
        return last_ship or _last_ship_speaker(last_speaker) or "疑似船方A"

    if _is_vts_control_sentence(normalized):
        return "宁波交管"

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
            r"((嗯|啊|好)?[,，]?(请讲)|收到|收到[,，]?再会|注意安全|好[,，]?注意安全|好的[,，]?注意安全|再会|好[,，]?下一个.*|下一个.*)",
            sentence,
        )
    )


def _looks_like_vts_instruction(sentence: str) -> bool:
    return bool(
        re.search(
            r"^((嗯|啊|好)?[,，]?请讲|收到[,，]?再会|注意安全|好[,，]?注意安全|好[,，]?下一个|下一个|保持联系|加强联系)",
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
