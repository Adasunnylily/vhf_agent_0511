from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import contextlib
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.services.asr import FunASRAdapter  # noqa: E402
from app.services.audio_utils import slice_wav_segment  # noqa: E402
from app.services.vad import WavEnergyVAD  # noqa: E402


AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".aac", ".pcm", ".ogg"}

SHIP_PATTERNS = [
    "vts",
    "报告",
    "我船",
    "本船",
    "申请",
    "请求",
    "呼叫",
    "已靠泊",
    "已靠港",
    "已抛锚",
    "mayday",
    "求救",
    "救助",
    "遇险",
    "紧急",
    "需要援助",
    "准备离泊",
    "预计靠泊时间",
    "到达锚地",
    "通过报告线",
    "计划抛锚",
    "请问",
    "能否",
    "是否",
    "询问",
    "咨询",
]
OPERATOR_PATTERNS = [
    "vts收到",
    "收到",
    "请保持守听",
    "请待命",
    "请报告",
    "请加强瞭望",
    "等待指令",
    "按规定",
    "警告",
    "指令",
    "立即",
    "报告位置",
    "人员数量",
    "伤亡情况",
    "拖轮",
    "消防船",
    "救援",
    "撤离",
    "禁止",
    "许可",
    "允许",
    "可以",
    "建议",
    "前往",
    "泊位",
    "锚地",
    "转换频道",
    "请注意",
    "谨慎航行",
    "限速",
]
STRONG_SHIP_PATTERNS = [
    "我船",
    "本船",
    "申请",
    "请求",
    "呼叫",
    "已靠泊",
    "已靠港",
    "已抛锚",
    "mayday",
    "求救",
    "救助",
    "遇险",
    "紧急",
    "需要援助",
    "准备离泊",
    "通过报告线",
    "计划抛锚",
    "到达锚地",
]
HIGH_RISK_SCENARIOS: Dict[str, List[str]] = {
    "collision": ["碰撞", "相撞", "撞上", "撞击"],
    "grounding_or_reef": ["搁浅", "触礁"],
    "fire_or_explosion": ["失火", "着火", "起火", "火灾", "冒烟", "爆炸"],
    "listing_or_capsize": ["倾斜", "横倾", "左倾", "右倾", "倾覆", "翻沉"],
    "flooding_or_sinking": ["进水", "下沉", "沉没", "快沉", "沉没危险"],
    "loss_control_or_mechanical_failure": ["失控", "无法航行", "失去动力", "主机故障", "舵机故障", "机械故障", "需要拖轮"],
    "anchor_dragging": ["走锚", "拖锚"],
    "person_overboard_or_medical": ["人员落水", "伤病", "医疗援助", "人员受伤"],
    "piracy_or_armed_attack": ["海盗", "袭击", "武装袭击"],
    "oil_or_dangerous_cargo_spill": ["溢油", "污染", "危险货物泄漏", "危险货物入海", "泄漏"],
    "aircraft_distress": ["航空器遇险", "飞机遇险", "直升机遇险"],
    "confined_space_trapped": ["密闭舱室", "人员被困", "舱室被困"],
}

HIGH_DISTRESS_KEYWORDS = ["遇险", "mayday", "紧急", "需要援助", "求救", "救命", "救助"]

NON_HIGH_RISK_SCENARIOS: Dict[str, List[str]] = {
    "enter_or_leave_vts": ["进入vts", "驶出vts", "进入交管区", "驶出交管区"],
    "berth_or_departure": ["靠泊", "离泊", "靠港", "进港", "出港"],
    "anchoring": ["锚泊", "抛锚", "锚地"],
    "channel_navigation_or_crossing": ["航道航行", "穿越航道", "过报告线", "通过报告线"],
    "traffic_organization_or_avoidance": ["避让", "让清航道", "宽让", "保持距离"],
    "pilot_or_tug_service": ["引航", "拖轮"],
    "weather_hydro_navmark": ["气象", "水文", "航标", "水深", "能见度"],
    "safety_broadcast": ["安全信息", "广播"],
    "water_work_or_drill": ["水工作业", "演习", "试航", "过驳"],
    "violation_correction": ["违章", "纠正", "超速", "逆行", "未报告"],
}

AUTO_REPLY_SCENARIOS: Dict[str, List[str]] = {
    "berth_completed": ["靠泊完毕", "靠港完毕", "已靠泊", "已靠港", "已靠妥", "系泊"],
    "anchor_completed": ["抛锚完毕", "抛好锚", "已抛锚", "到达锚地", "锚泊"],
    "report_line": ["报告线", "通过报告线", "过报告线"],
    "departure_report": ["离泊报备", "准备离泊", "离泊", "出港"],
    "arrival_plan": ["进入vts", "准备靠港", "预计靠泊时间", "eta", "目的港"],
}

MANUAL_ADVICE_SCENARIOS: Dict[str, List[str]] = {
    "navmark_depth_weather_query": ["询问", "请问", "能否", "是否", "气象", "水深", "航标", "能见度"],
    "other_ship_dynamics_query": ["他船位置", "他船动态"],
    "drill_trial_lightering": ["申请演习", "演习", "试航", "过驳"],
    "bridge_or_ice_navigation": ["桥区", "冰区"],
    "equipment_fault_not_loss_control": ["设备故障", "信号差", "频道干扰"],
    "routine_avoidance_coordination": ["避让", "让清航道", "宽让", "保持距离"],
}

SHIP_REPORT_KEYWORDS = [
    "报告",
    "通过报告线",
    "计划抛锚",
    "申请靠泊",
    "准备离泊",
    "到达锚地",
    "预计靠泊时间",
    "抛锚完毕",
    "靠泊完毕",
    "吃水",
    "船名",
    "呼号",
    "eta",
    "目的港",
]

OPERATOR_INSTRUCTION_KEYWORDS = [
    "警告",
    "指令",
    "立即",
    "报告位置",
    "人员数量",
    "伤亡情况",
    "火势",
    "进水",
    "堵漏",
    "拖轮",
    "消防船",
    "救援",
    "撤离",
    "禁止",
    "保持守听",
    "许可",
    "允许",
    "可以",
    "建议",
    "前往",
    "锚地",
    "泊位",
    "等待",
    "报告动态",
    "转换频道",
    "请注意",
    "谨慎航行",
    "限速",
]


@dataclass
class RoleResult:
    role: str
    confidence: float
    evidence: List[str]


@dataclass
class RiskResult:
    risk_label: str
    risk_type: str
    confidence: float
    evidence: List[str]
    risk_category: str
    scenario: str
    automation_label: str
    matched_ship_keywords: List[str]
    matched_operator_keywords: List[str]


@dataclass
class ModelAnalysis:
    source: str
    role_label: str
    role_confidence: float
    crisis_label: str
    crisis_confidence: float
    automation_label: str
    scenario: str
    evidence: List[str]
    rationale: str


@dataclass
class FinalAnalysis:
    source: str
    role_label: str
    role_confidence: float
    crisis_label: str
    crisis_confidence: float
    automation_label: str
    scenario: str
    evidence: List[str]
    rationale: str
    disagreement: str


def normalize_text(text: str) -> str:
    return (text or "").lower().replace(" ", "").replace("，", "").replace(",", "")


def match_keywords(text: str, keywords: Iterable[str]) -> List[str]:
    normalized = normalize_text(text)
    return [keyword for keyword in keywords if keyword.lower() in normalized]


def match_scenario(text: str, scenario_map: Dict[str, List[str]]) -> tuple[str, List[str]]:
    best_scenario = "unknown"
    best_hits: List[str] = []
    for scenario, keywords in scenario_map.items():
        hits = match_keywords(text, keywords)
        if len(hits) > len(best_hits):
            best_scenario = scenario
            best_hits = hits
    return best_scenario, best_hits


def read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def read_jsonl(path: Path) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_csv(path: Path, rows: List[Dict[str, object]], fieldnames: Optional[List[str]] = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_evidence(value: object) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    if "|" in text:
        return [item for item in text.split("|") if item]
    if "；" in text:
        return [item for item in text.split("；") if item]
    if ";" in text:
        return [item for item in text.split(";") if item]
    return [text]


def is_standard_pcm_wav(source: Path) -> bool:
    if source.suffix.lower() != ".wav":
        return False
    try:
        with contextlib.closing(wave.open(str(source), "rb")) as wav_file:
            return (
                wav_file.getframerate() == 16000
                and wav_file.getnchannels() == 1
                and wav_file.getsampwidth() == 2
            )
    except Exception:
        return False


def normalize_to_16k_wav(source: Path, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    if is_standard_pcm_wav(source):
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        return target

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("未找到 ffmpeg，无法把音频统一转换为 16k mono PCM wav。")
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(source),
        "-ac",
        "1",
        "-ar",
        "16000",
        "-acodec",
        "pcm_s16le",
        str(target),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return target


def build_raw_manifest(audio_dir: Path, output: Path, channel_id: str) -> None:
    files = sorted(
        path
        for path in audio_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
    )
    rows = [
        {
            "audio_id": f"raw_{index:06d}",
            "audio_path": str(path.resolve()),
            "channel_id": channel_id,
            "recorded_at": "",
        }
        for index, path in enumerate(files, start=1)
    ]
    write_csv(output, rows, ["audio_id", "audio_path", "channel_id", "recorded_at"])
    print(f"wrote {len(rows)} raw audio rows -> {output}")


def split_vad(
    raw_manifest: Path,
    output: Path,
    clip_dir: Path,
    normalized_dir: Path,
    frame_ms: int,
    silence_ms: int,
    min_speech_ms: int,
    max_segment_ms: int,
    energy_threshold: int,
) -> None:
    vad = WavEnergyVAD(
        frame_ms=frame_ms,
        silence_ms=silence_ms,
        min_speech_ms=min_speech_ms,
        max_segment_ms=max_segment_ms,
        energy_threshold=energy_threshold,
    )
    rows: List[Dict[str, object]] = []
    for raw in read_csv(raw_manifest):
        audio_id = raw["audio_id"]
        source = Path(raw["audio_path"])
        normalized = normalized_dir / f"{audio_id}.wav"
        normalize_to_16k_wav(source, normalized)
        detected = vad.detect(normalized)
        for index, segment in enumerate(detected, start=1):
            segment_id = f"{audio_id}_seg_{index:04d}"
            clip_path = clip_dir / f"{segment_id}.wav"
            clip_path.parent.mkdir(parents=True, exist_ok=True)
            slice_wav_segment(normalized, clip_path, segment.start_ms, segment.end_ms)
            rows.append(
                {
                    "segment_id": segment_id,
                    "raw_audio_id": audio_id,
                    "channel_id": raw.get("channel_id", ""),
                    "clip_path": str(clip_path.resolve()),
                    "start_ms": segment.start_ms,
                    "end_ms": segment.end_ms,
                    "duration_ms": segment.end_ms - segment.start_ms,
                    "source_audio_path": str(source.resolve()),
                    "normalized_audio_path": str(normalized.resolve()),
                }
            )
    write_csv(
        output,
        rows,
        [
            "segment_id",
            "raw_audio_id",
            "channel_id",
            "clip_path",
            "start_ms",
            "end_ms",
            "duration_ms",
            "source_audio_path",
            "normalized_audio_path",
        ],
    )
    print(f"wrote {len(rows)} vad segment rows -> {output}")


def transcribe_segments(
    vad_manifest: Path,
    output: Path,
    model: str,
    vad_model: str,
    punc_model: str,
    device: str,
    hub: str,
    language: str,
    batch_size_s: int,
    limit: int,
) -> None:
    rows = read_csv(vad_manifest)
    if limit > 0:
        rows = rows[:limit]
    asr = FunASRAdapter(
        model=model,
        vad_model=vad_model,
        punc_model=punc_model,
        device=device,
        hub=hub,
        language=language,
        batch_size_s=batch_size_s,
    )
    output_rows: List[Dict[str, object]] = []
    for index, row in enumerate(rows, start=1):
        clip_path = Path(row["clip_path"])
        result = asr.transcribe(clip_path)
        merged = dict(row)
        merged.update(
            {
                "asr_text": result.text,
                "asr_model": result.engine,
                "asr_confidence": result.confidence,
            }
        )
        output_rows.append(merged)
        print(f"asr {index}/{len(rows)} {row['segment_id']} {result.text[:40]}", flush=True)
    write_csv(output, output_rows)
    print(f"wrote {len(output_rows)} asr rows -> {output}")


def classify_role(asr_text: str) -> RoleResult:
    text = normalize_text(asr_text)
    ship_hits = [keyword for keyword in SHIP_PATTERNS if keyword in text]
    operator_hits = [keyword for keyword in OPERATOR_PATTERNS if keyword in text]
    strong_ship_hits = [keyword for keyword in STRONG_SHIP_PATTERNS if keyword in text]

    if ship_hits and not operator_hits:
        return RoleResult("ship", 0.82, ship_hits)
    if operator_hits and not ship_hits:
        return RoleResult("operator", 0.82, operator_hits)
    if ship_hits and operator_hits:
        if operator_hits and not strong_ship_hits:
            return RoleResult("operator", 0.76, operator_hits)
        return RoleResult("mixed", 0.58, ship_hits + operator_hits)
    return RoleResult("unclear", 0.30, [])


def weak_label_risk(asr_text: str, role: str) -> RiskResult:
    ship_keyword_hits = match_keywords(asr_text, SHIP_REPORT_KEYWORDS + HIGH_DISTRESS_KEYWORDS)
    operator_keyword_hits = [] if role == "ship" else match_keywords(asr_text, OPERATOR_INSTRUCTION_KEYWORDS)

    if role != "ship":
        return RiskResult(
            risk_label="not_target",
            risk_type="none",
            confidence=0.90,
            evidence=[],
            risk_category="not_target",
            scenario="not_target",
            automation_label="not_target",
            matched_ship_keywords=ship_keyword_hits,
            matched_operator_keywords=operator_keyword_hits,
        )

    high_scenario, high_hits = match_scenario(asr_text, HIGH_RISK_SCENARIOS)
    distress_hits = match_keywords(asr_text, HIGH_DISTRESS_KEYWORDS)
    high_hits = unique_list([*distress_hits, *high_hits])
    auto_scenario, auto_hits = match_scenario(asr_text, AUTO_REPLY_SCENARIOS)
    manual_scenario, manual_hits = match_scenario(asr_text, MANUAL_ADVICE_SCENARIOS)
    non_high_scenario, non_high_hits = match_scenario(asr_text, NON_HIGH_RISK_SCENARIOS)

    if high_hits:
        return RiskResult(
            risk_label="high",
            risk_type=high_scenario if high_scenario != "unknown" else "distress_call",
            confidence=0.90,
            evidence=high_hits,
            risk_category="high_risk",
            scenario=high_scenario if high_scenario != "unknown" else "distress_call",
            automation_label="manual_immediate",
            matched_ship_keywords=ship_keyword_hits,
            matched_operator_keywords=operator_keyword_hits,
        )
    if auto_hits:
        return RiskResult(
            risk_label="normal",
            risk_type=auto_scenario,
            confidence=0.84,
            evidence=auto_hits,
            risk_category="non_high_risk",
            scenario=auto_scenario,
            automation_label="auto_reply",
            matched_ship_keywords=ship_keyword_hits,
            matched_operator_keywords=operator_keyword_hits,
        )
    if manual_hits:
        return RiskResult(
            risk_label="uncertain",
            risk_type=manual_scenario,
            confidence=0.70,
            evidence=manual_hits,
            risk_category="non_high_risk",
            scenario=manual_scenario,
            automation_label="llm_advice",
            matched_ship_keywords=ship_keyword_hits,
            matched_operator_keywords=operator_keyword_hits,
        )
    if non_high_hits:
        return RiskResult(
            risk_label="normal",
            risk_type=non_high_scenario,
            confidence=0.72,
            evidence=non_high_hits,
            risk_category="non_high_risk",
            scenario=non_high_scenario,
            automation_label="manual_or_rule_review",
            matched_ship_keywords=ship_keyword_hits,
            matched_operator_keywords=operator_keyword_hits,
        )
    return RiskResult(
        risk_label="uncertain",
        risk_type="unknown",
        confidence=0.35,
        evidence=[],
        risk_category="non_high_risk",
        scenario="unknown",
        automation_label="llm_advice",
        matched_ship_keywords=ship_keyword_hits,
        matched_operator_keywords=operator_keyword_hits,
    )


def unique_list(items: Iterable[str]) -> List[str]:
    result: List[str] = []
    for item in items:
        if item not in result:
            result.append(item)
    return result


def load_model_analysis(path: Optional[Path], source: str) -> Dict[str, ModelAnalysis]:
    if not path:
        return {}
    if not path.exists():
        raise FileNotFoundError(f"{source} analysis file not found: {path}")

    raw_rows: List[Dict[str, object]]
    if path.suffix.lower() == ".jsonl":
        raw_rows = read_jsonl(path)
    else:
        raw_rows = [dict(row) for row in read_csv(path)]

    analyses: Dict[str, ModelAnalysis] = {}
    for row in raw_rows:
        segment_id = str(row.get("segment_id") or row.get("id") or "").strip()
        if not segment_id:
            continue
        analyses[segment_id] = ModelAnalysis(
            source=source,
            role_label=normalize_role_label(row.get("role_label") or row.get("role") or row.get("speaker_side")),
            role_confidence=parse_float(row.get("role_confidence"), 0.0),
            crisis_label=normalize_crisis_label(row.get("crisis_label") or row.get("risk_label") or row.get("risk")),
            crisis_confidence=parse_float(row.get("crisis_confidence") or row.get("risk_confidence"), 0.0),
            automation_label=normalize_automation_label(row.get("automation_label") or row.get("route")),
            scenario=str(row.get("scenario") or row.get("risk_type") or "unknown").strip() or "unknown",
            evidence=parse_evidence(row.get("evidence") or row.get("keywords")),
            rationale=str(row.get("rationale") or row.get("reason") or row.get("notes") or "").strip(),
        )
    return analyses


def normalize_role_label(value: object) -> str:
    text = str(value or "").strip().lower()
    mapping = {
        "ship": "ship",
        "vessel": "ship",
        "船方": "ship",
        "船舶": "ship",
        "operator": "operator",
        "manager": "operator",
        "vts": "operator",
        "管理方": "operator",
        "值班员": "operator",
        "mixed": "mixed",
        "混合": "mixed",
        "unclear": "unclear",
        "unknown": "unclear",
        "不确定": "unclear",
    }
    return mapping.get(text, text if text in {"ship", "operator", "mixed", "unclear"} else "unclear")


def normalize_crisis_label(value: object) -> str:
    text = str(value or "").strip().lower()
    mapping = {
        "high": "crisis",
        "danger": "crisis",
        "emergency": "crisis",
        "crisis": "crisis",
        "高危": "crisis",
        "危机": "crisis",
        "险情": "crisis",
        "normal": "non_crisis",
        "non_high": "non_crisis",
        "non_crisis": "non_crisis",
        "routine": "non_crisis",
        "非高危": "non_crisis",
        "非危机": "non_crisis",
        "uncertain": "uncertain",
        "unknown": "uncertain",
        "不确定": "uncertain",
        "not_target": "not_target",
    }
    return mapping.get(text, text if text in {"crisis", "non_crisis", "uncertain", "not_target"} else "uncertain")


def normalize_automation_label(value: object) -> str:
    text = str(value or "").strip().lower()
    mapping = {
        "manual_immediate": "manual_immediate",
        "emergency_manual": "manual_immediate",
        "人工处理": "manual_immediate",
        "auto": "auto_reply",
        "auto_reply": "auto_reply",
        "自动化": "auto_reply",
        "自动回复": "auto_reply",
        "llm": "llm_advice",
        "llm_advice": "llm_advice",
        "manual_advice": "llm_advice",
        "非自动化": "llm_advice",
        "not_target": "not_target",
    }
    return mapping.get(text, text if text in {"manual_immediate", "auto_reply", "llm_advice", "not_target", "unknown"} else "unknown")


def fallback_analysis_from_rules(asr_text: str) -> FinalAnalysis:
    role = classify_role(asr_text)
    risk = weak_label_risk(asr_text, role.role)
    crisis_label = {
        "high": "crisis",
        "normal": "non_crisis",
        "uncertain": "uncertain",
        "not_target": "not_target",
    }.get(risk.risk_label, "uncertain")
    return FinalAnalysis(
        source="rule_fallback",
        role_label=role.role,
        role_confidence=role.confidence,
        crisis_label=crisis_label,
        crisis_confidence=risk.confidence,
        automation_label=risk.automation_label,
        scenario=risk.scenario,
        evidence=unique_list([*role.evidence, *risk.evidence]),
        rationale="规则兜底结果，仅用于冷启动和人工复核排序，不作为最终可靠标签。",
        disagreement="",
    )


def choose_final_analysis(
    segment_id: str,
    asr_text: str,
    llm_map: Dict[str, ModelAnalysis],
    audio_map: Dict[str, ModelAnalysis],
) -> FinalAnalysis:
    llm = llm_map.get(segment_id)
    audio = audio_map.get(segment_id)
    fallback = fallback_analysis_from_rules(asr_text)
    disagreement = detect_disagreement(llm, audio)

    # 优先使用 ASR+LLM 的结构化分析；当 ASR文本为空或LLM缺失时，用音频大模型结果。
    if llm and llm.role_label != "unclear":
        selected = llm
        source = "llm_analysis"
    elif audio:
        selected = audio
        source = "audio_model_analysis"
    elif llm:
        selected = llm
        source = "llm_analysis"
    else:
        return fallback

    role_label = selected.role_label
    crisis_label = selected.crisis_label
    automation_label = selected.automation_label
    if role_label != "ship":
        crisis_label = "not_target"
        automation_label = "not_target"
    elif crisis_label == "crisis":
        automation_label = "manual_immediate"
    elif crisis_label == "non_crisis" and automation_label == "unknown":
        automation_label = "llm_advice"

    return FinalAnalysis(
        source=source,
        role_label=role_label,
        role_confidence=selected.role_confidence or fallback.role_confidence,
        crisis_label=crisis_label,
        crisis_confidence=selected.crisis_confidence or fallback.crisis_confidence,
        automation_label=automation_label,
        scenario=selected.scenario if selected.scenario != "unknown" else fallback.scenario,
        evidence=selected.evidence or fallback.evidence,
        rationale=selected.rationale,
        disagreement=disagreement,
    )


def detect_disagreement(llm: Optional[ModelAnalysis], audio: Optional[ModelAnalysis]) -> str:
    if not llm or not audio:
        return ""
    flags = []
    if llm.role_label != audio.role_label:
        flags.append("role")
    if llm.crisis_label != audio.crisis_label:
        flags.append("crisis")
    if llm.automation_label != audio.automation_label:
        flags.append("automation")
    return "|".join(flags)


def build_weak_labels(
    asr_manifest: Path,
    output: Path,
    stats_output: Optional[Path],
    llm_analysis: Optional[Path] = None,
    audio_analysis: Optional[Path] = None,
) -> None:
    rows = []
    stats: Dict[str, Dict[str, int]] = {
        "role": {},
        "crisis_label": {},
        "automation_label": {},
        "scenario": {},
        "source": {},
    }
    llm_map = load_model_analysis(llm_analysis, "llm") if llm_analysis else {}
    audio_map = load_model_analysis(audio_analysis, "audio_model") if audio_analysis else {}

    for row in read_csv(asr_manifest):
        asr_text = row.get("asr_text", "")
        segment_id = row.get("segment_id", "")
        fallback = fallback_analysis_from_rules(asr_text)
        final = choose_final_analysis(segment_id, asr_text, llm_map, audio_map)

        # 保留规则兜底字段，方便人工核实模型结果是否偏离明显业务关键词。
        fallback_role = classify_role(asr_text)
        fallback_risk = weak_label_risk(asr_text, fallback_role.role)
        merged = dict(row)
        merged.update(
            {
                "analysis_source": final.source,
                "role_pred": final.role_label,
                "role_confidence": final.role_confidence,
                "crisis_label_pred": final.crisis_label,
                "crisis_confidence": final.crisis_confidence,
                "automation_label_pred": final.automation_label,
                "scenario_pred": final.scenario,
                "analysis_evidence": "|".join(final.evidence),
                "analysis_rationale": final.rationale,
                "analysis_disagreement": final.disagreement,
                "fallback_role_pred": fallback.role_label,
                "fallback_crisis_label_pred": fallback.crisis_label,
                "fallback_automation_label_pred": fallback.automation_label,
                "fallback_scenario_pred": fallback.scenario,
                "ship_keyword_hits": "|".join(fallback_risk.matched_ship_keywords),
                "operator_keyword_hits": "|".join(fallback_risk.matched_operator_keywords),
                # Backward-compatible columns used by older review scripts/tests.
                "risk_label_pred": {
                    "crisis": "high",
                    "non_crisis": "normal",
                    "uncertain": "uncertain",
                    "not_target": "not_target",
                }.get(final.crisis_label, "uncertain"),
                "risk_type_pred": final.scenario,
                "risk_category_pred": {
                    "crisis": "high_risk",
                    "non_crisis": "non_high_risk",
                    "uncertain": "non_high_risk",
                    "not_target": "not_target",
                }.get(final.crisis_label, "non_high_risk"),
                "weak_confidence": final.crisis_confidence,
                "risk_evidence": "|".join(final.evidence),
            }
        )
        rows.append(merged)
        bump(stats["role"], final.role_label)
        bump(stats["crisis_label"], final.crisis_label)
        bump(stats["automation_label"], final.automation_label)
        bump(stats["scenario"], final.scenario)
        bump(stats["source"], final.source)
    write_csv(output, rows)
    if stats_output:
        stats_output.parent.mkdir(parents=True, exist_ok=True)
        stats_output.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(rows)} weak label rows -> {output}")


def bump(bucket: Dict[str, int], key: str) -> None:
    bucket[key] = bucket.get(key, 0) + 1


def priority_score(row: Dict[str, str]) -> int:
    risk = row.get("risk_label_pred", "")
    role = row.get("role_pred", "")
    automation = row.get("automation_label_pred", "")
    confidence = float(row.get("weak_confidence") or 0)
    text = row.get("asr_text", "")
    score = 0
    if risk == "high":
        score += 100
    if risk == "uncertain":
        score += 80
    if automation == "llm_advice":
        score += 45
    if automation == "auto_reply":
        score += 20
    if role in {"mixed", "unclear"}:
        score += 55
    if confidence < 0.6:
        score += 35
    if len(text.strip()) < 4:
        score += 25
    return score


def build_review_manifest(weak_manifest: Path, output: Path, limit: int) -> None:
    rows = []
    for row in read_csv(weak_manifest):
        merged = dict(row)
        merged.update(
            {
                "review_priority": priority_score(row),
                "human_role": "",
                "human_risk_label": "",
                "human_risk_type": "",
                "human_risk_category": "",
                "human_scenario": "",
                "human_automation_label": "",
                "human_reference_text": "",
                "notes": "",
            }
        )
        rows.append(merged)
    rows.sort(key=lambda item: int(item["review_priority"]), reverse=True)
    if limit > 0:
        rows = rows[:limit]
    write_csv(output, rows)
    print(f"wrote {len(rows)} review rows -> {output}")


def run_all(args: argparse.Namespace) -> None:
    base = args.output_dir
    manifests = base / "manifests"
    clips = base / "clips"
    raw_manifest = manifests / "raw_audio_manifest.csv"
    vad_manifest = manifests / "vad_segments_manifest.csv"
    asr_manifest = manifests / "asr_segments_manifest.csv"
    weak_manifest = manifests / "weak_labeled_manifest.csv"
    review_manifest = manifests / "human_review_manifest.csv"
    stats_output = base / "reports" / "label_stats.json"

    build_raw_manifest(args.audio_dir, raw_manifest, args.channel_id)
    split_vad(
        raw_manifest=raw_manifest,
        output=vad_manifest,
        clip_dir=clips / "vad_segments",
        normalized_dir=clips / "normalized",
        frame_ms=args.frame_ms,
        silence_ms=args.silence_ms,
        min_speech_ms=args.min_speech_ms,
        max_segment_ms=args.max_segment_ms,
        energy_threshold=args.energy_threshold,
    )
    transcribe_segments(
        vad_manifest=vad_manifest,
        output=asr_manifest,
        model=args.model,
        vad_model=args.asr_vad_model,
        punc_model=args.punc_model,
        device=args.device,
        hub=args.hub,
        language=args.language,
        batch_size_s=args.batch_size_s,
        limit=args.limit,
    )
    build_weak_labels(
        asr_manifest,
        weak_manifest,
        stats_output,
        llm_analysis=args.llm_analysis,
        audio_analysis=args.audio_analysis,
    )
    build_review_manifest(weak_manifest, review_manifest, args.review_limit)


def add_common_vad_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--frame-ms", type=int, default=30)
    parser.add_argument("--silence-ms", type=int, default=1200)
    parser.add_argument("--min-speech-ms", type=int, default=600)
    parser.add_argument(
        "--max-segment-ms",
        type=int,
        default=0,
        help="0 means do not force fixed-length cuts; use silence gaps as utterance boundaries.",
    )
    parser.add_argument("--energy-threshold", type=int, default=450)


def add_common_asr_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", default="iic/SenseVoiceSmall")
    parser.add_argument("--asr-vad-model", default="fsmn-vad")
    parser.add_argument("--punc-model", default="")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--hub", default="ms")
    parser.add_argument("--language", default="auto")
    parser.add_argument("--batch-size-s", type=int, default=30)
    parser.add_argument("--limit", type=int, default=0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Construct VHF ship-call high-risk classification dataset.")
    sub = parser.add_subparsers(dest="command", required=True)

    raw = sub.add_parser("raw-manifest")
    raw.add_argument("--audio-dir", required=True, type=Path)
    raw.add_argument("--output", required=True, type=Path)
    raw.add_argument("--channel-id", default="beilun_vhf_01")

    vad = sub.add_parser("vad-split")
    vad.add_argument("--raw-manifest", required=True, type=Path)
    vad.add_argument("--output", required=True, type=Path)
    vad.add_argument("--clip-dir", required=True, type=Path)
    vad.add_argument("--normalized-dir", required=True, type=Path)
    add_common_vad_args(vad)

    asr = sub.add_parser("asr-transcribe")
    asr.add_argument("--vad-manifest", required=True, type=Path)
    asr.add_argument("--output", required=True, type=Path)
    add_common_asr_args(asr)

    weak = sub.add_parser("weak-label")
    weak.add_argument("--asr-manifest", required=True, type=Path)
    weak.add_argument("--output", required=True, type=Path)
    weak.add_argument("--stats-output", type=Path, default=None)
    weak.add_argument("--llm-analysis", type=Path, default=None)
    weak.add_argument("--audio-analysis", type=Path, default=None)

    review = sub.add_parser("review-manifest")
    review.add_argument("--weak-manifest", required=True, type=Path)
    review.add_argument("--output", required=True, type=Path)
    review.add_argument("--limit", type=int, default=500)

    all_cmd = sub.add_parser("run-all")
    all_cmd.add_argument("--audio-dir", required=True, type=Path)
    all_cmd.add_argument("--output-dir", required=True, type=Path)
    all_cmd.add_argument("--channel-id", default="beilun_vhf_01")
    all_cmd.add_argument("--review-limit", type=int, default=500)
    all_cmd.add_argument("--llm-analysis", type=Path, default=None)
    all_cmd.add_argument("--audio-analysis", type=Path, default=None)
    add_common_vad_args(all_cmd)
    add_common_asr_args(all_cmd)

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "raw-manifest":
        build_raw_manifest(args.audio_dir, args.output, args.channel_id)
    elif args.command == "vad-split":
        split_vad(
            args.raw_manifest,
            args.output,
            args.clip_dir,
            args.normalized_dir,
            args.frame_ms,
            args.silence_ms,
            args.min_speech_ms,
            args.max_segment_ms,
            args.energy_threshold,
        )
    elif args.command == "asr-transcribe":
        transcribe_segments(
            args.vad_manifest,
            args.output,
            args.model,
            args.asr_vad_model,
            args.punc_model,
            args.device,
            args.hub,
            args.language,
            args.batch_size_s,
            args.limit,
        )
    elif args.command == "weak-label":
        build_weak_labels(
            args.asr_manifest,
            args.output,
            args.stats_output,
            llm_analysis=args.llm_analysis,
            audio_analysis=args.audio_analysis,
        )
    elif args.command == "review-manifest":
        build_review_manifest(args.weak_manifest, args.output, args.limit)
    elif args.command == "run-all":
        run_all(args)


if __name__ == "__main__":
    main()
