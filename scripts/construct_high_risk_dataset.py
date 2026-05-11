from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
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


def normalize_to_16k_wav(source: Path, target: Path) -> Path:
    if source.suffix.lower() == ".wav":
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        return target

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("未找到 ffmpeg，无法把非 wav 音频转换为 16k mono PCM wav。")
    target.parent.mkdir(parents=True, exist_ok=True)
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


def build_weak_labels(asr_manifest: Path, output: Path, stats_output: Optional[Path]) -> None:
    rows = []
    stats: Dict[str, Dict[str, int]] = {"role": {}, "risk_label": {}, "risk_type": {}}
    for row in read_csv(asr_manifest):
        role = classify_role(row.get("asr_text", ""))
        risk = weak_label_risk(row.get("asr_text", ""), role.role)
        merged = dict(row)
        merged.update(
            {
                "role_pred": role.role,
                "role_confidence": role.confidence,
                "role_evidence": "|".join(role.evidence),
                "risk_label_pred": risk.risk_label,
                "risk_type_pred": risk.risk_type,
                "risk_category_pred": risk.risk_category,
                "scenario_pred": risk.scenario,
                "automation_label_pred": risk.automation_label,
                "weak_confidence": risk.confidence,
                "risk_evidence": "|".join(risk.evidence),
                "ship_keyword_hits": "|".join(risk.matched_ship_keywords),
                "operator_keyword_hits": "|".join(risk.matched_operator_keywords),
            }
        )
        rows.append(merged)
        bump(stats["role"], role.role)
        bump(stats["risk_label"], risk.risk_label)
        bump(stats["risk_type"], risk.risk_type)
        stats.setdefault("risk_category", {})
        stats.setdefault("scenario", {})
        stats.setdefault("automation_label", {})
        bump(stats["risk_category"], risk.risk_category)
        bump(stats["scenario"], risk.scenario)
        bump(stats["automation_label"], risk.automation_label)
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
    build_weak_labels(asr_manifest, weak_manifest, stats_output)
    build_review_manifest(weak_manifest, review_manifest, args.review_limit)


def add_common_vad_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--frame-ms", type=int, default=30)
    parser.add_argument("--silence-ms", type=int, default=900)
    parser.add_argument("--min-speech-ms", type=int, default=600)
    parser.add_argument("--max-segment-ms", type=int, default=8000)
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

    review = sub.add_parser("review-manifest")
    review.add_argument("--weak-manifest", required=True, type=Path)
    review.add_argument("--output", required=True, type=Path)
    review.add_argument("--limit", type=int, default=500)

    all_cmd = sub.add_parser("run-all")
    all_cmd.add_argument("--audio-dir", required=True, type=Path)
    all_cmd.add_argument("--output-dir", required=True, type=Path)
    all_cmd.add_argument("--channel-id", default="beilun_vhf_01")
    all_cmd.add_argument("--review-limit", type=int, default=500)
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
        build_weak_labels(args.asr_manifest, args.output, args.stats_output)
    elif args.command == "review-manifest":
        build_review_manifest(args.weak_manifest, args.output, args.limit)
    elif args.command == "run-all":
        run_all(args)


if __name__ == "__main__":
    main()
