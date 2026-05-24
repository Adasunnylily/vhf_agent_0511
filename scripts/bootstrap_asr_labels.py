from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.asr import QwenASRAdapter, sanitize_asr_text
from app.services.entity_resolver import EntityResolver


RISK_KEYWORDS: Dict[str, List[str]] = {
    "fire_smoke": ["冒烟", "起火", "着火", "失火", "火灾", "爆炸", "机舱烟", "烟很大"],
    "distress": ["mayday", "求救", "救命", "请求救助", "紧急救助", "遇险", "救生筏"],
    "collision": ["碰撞", "撞上", "碰上", "快碰", "快要碰上", "会碰", "擦碰"],
    "grounding": ["搁浅", "触礁", "上浅", "浅滩"],
    "flooding_sinking": ["进水", "漏水", "沉没", "快沉", "下沉"],
    "loss_control": ["失控", "失去动力", "主机故障", "机器故障", "舵机故障", "漂航", "不能控制"],
    "person_overboard": ["人员落水", "有人落水", "落水人员"],
    "medical": ["受伤", "昏迷", "医疗救助", "急救", "伤病"],
    "hazmat_pollution": ["危险货物", "油污", "溢油", "泄漏", "污染"],
    "navigation_risk": ["让清航道", "避让", "浓雾", "团雾", "能见度低", "逆行", "超速"],
}

DEPARTURE_KEYWORDS = ["离泊", "出港", "开航", "申请", "请求", "解缆", "备车", "动车"]
ROUTINE_KEYWORDS = ["靠泊", "靠港", "抛锚", "锚泊", "已靠妥", "报告线", "码头", "直接进去", "不抛锚"]


def list_audio_files(audio_dir: Path) -> List[Path]:
    patterns = ("*.wav", "*.mp3", "*.m4a", "*.flac", "*.aac", "*.webm", "*.ogg")
    files: List[Path] = []
    for p in patterns:
        files.extend(audio_dir.rglob(p))
    files = sorted(set(files))
    return files


def analyze_text(text: str) -> Dict[str, object]:
    t = text.lower()
    matched_by_subtype: Dict[str, List[str]] = {}
    for subtype, keywords in RISK_KEYWORDS.items():
        hits = [keyword for keyword in keywords if keyword.lower() in t]
        if hits:
            matched_by_subtype[subtype] = hits

    matched_keywords = [keyword for hits in matched_by_subtype.values() for keyword in hits]
    if matched_by_subtype:
        l1_subtypes = {
            "fire_smoke",
            "distress",
            "flooding_sinking",
            "person_overboard",
            "medical",
            "hazmat_pollution",
        }
        risk_level = "L1" if any(subtype in l1_subtypes for subtype in matched_by_subtype) else "L2"
        subtype_priority = {subtype: index for index, subtype in enumerate(RISK_KEYWORDS)}
        subtype_order = sorted(
            matched_by_subtype,
            key=lambda subtype: (
                0 if subtype in l1_subtypes else 1,
                -len(matched_by_subtype[subtype]),
                subtype_priority.get(subtype, 999),
            ),
        )
        return {
            "primary_label": "emergency_risk",
            "risk_level": risk_level,
            "risk_subtype": subtype_order[0],
            "matched_keywords": matched_keywords,
            "emergency_score": min(100, 70 + 8 * len(matched_keywords) + (12 if risk_level == "L1" else 0)),
            "review_priority": "urgent" if risk_level == "L1" else "high",
            "review_notes": "疑似高危，优先人工听音复核。",
        }

    if any(k in t for k in DEPARTURE_KEYWORDS):
        return {
            "primary_label": "departure_request",
            "risk_level": "business_review",
            "risk_subtype": "",
            "matched_keywords": [k for k in DEPARTURE_KEYWORDS if k in t],
            "emergency_score": 40,
            "review_priority": "high",
            "review_notes": "离泊/申请类业务，需要人工确认。",
        }
    if any(k in t for k in ROUTINE_KEYWORDS):
        return {
            "primary_label": "routine_report",
            "risk_level": "low",
            "risk_subtype": "",
            "matched_keywords": [k for k in ROUTINE_KEYWORDS if k in t],
            "emergency_score": 10,
            "review_priority": "medium",
            "review_notes": "常规报告，抽样复核船名/地名即可。",
        }
    if len(text.strip()) < 3:
        return {
            "primary_label": "invalid_or_noise",
            "risk_level": "unknown",
            "risk_subtype": "",
            "matched_keywords": [],
            "emergency_score": 0,
            "review_priority": "medium",
            "review_notes": "空文本/短文本，检查是否噪声或ASR失败。",
        }
    return {
        "primary_label": "other_business",
        "risk_level": "low",
        "risk_subtype": "",
        "matched_keywords": [],
        "emergency_score": 5,
        "review_priority": "low",
        "review_notes": "",
    }


def rule_label(text: str) -> str:
    return str(analyze_text(text)["primary_label"])


def priority_rank(row: Dict[str, object]) -> Tuple[int, int, str]:
    priority = str(row.get("review_priority", "low"))
    order = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
    return (order.get(priority, 9), -int(row.get("emergency_score_auto") or 0), str(row.get("sample_id", "")))


def preview_text(text: str, limit: int = 42) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."


def join_entities(candidates: List[object], entity_type: str, min_score: float = 0.96) -> str:
    values: List[str] = []
    for candidate in candidates:
        if getattr(candidate, "entity_type", "") != entity_type:
            continue
        if float(getattr(candidate, "score", 0.0)) < min_score:
            continue
        canonical = str(getattr(candidate, "canonical", "")).strip()
        if canonical and canonical not in values:
            values.append(canonical)
    return "；".join(values)


def serialize_candidates(candidates: List[object]) -> str:
    parts: List[str] = []
    for candidate in candidates:
        entity_type = str(getattr(candidate, "entity_type", ""))
        canonical = str(getattr(candidate, "canonical", ""))
        matched_text = str(getattr(candidate, "matched_text", ""))
        score = float(getattr(candidate, "score", 0.0))
        reason = str(getattr(candidate, "reason", ""))
        parts.append(f"{entity_type}:{canonical}|match={matched_text}|score={score:.2f}|{reason}")
    return "；".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run strong ASR API first, export CSV for human correction.")
    parser.add_argument("--audio-dir", required=True, type=Path, help="目录下递归扫描音频")
    parser.add_argument("--out", required=True, type=Path, help="输出csv")
    parser.add_argument("--limit", type=int, default=0, help="仅处理前N条，0表示全部")
    parser.add_argument(
        "--source-mode",
        default="upload_audio",
        choices=["upload_audio", "stream_replay", "live_stream_sample"],
        help="样本来源：离线上传、流式回放或现场流式抽样。",
    )
    parser.add_argument("--model", default="qwen3-asr-flash")
    parser.add_argument("--api-key-env", default="DASHSCOPE_API_KEY")
    parser.add_argument("--base-url", default="https://dashscope.aliyuncs.com/compatible-mode/v1")
    parser.add_argument("--lexicon", type=Path, default=Path("data/lexicon_corrections.json"), help="船名/地名词典")
    parser.add_argument("--entity-min-score", type=float, default=0.82, help="实体候选模糊匹配最低分")
    parser.add_argument("--high-risk-out", type=Path, default=None, help="额外导出疑似高危/高优先级清单")
    parser.add_argument("--continue-on-error", action="store_true", help="单条ASR失败时继续处理后续音频")
    parser.add_argument("--print-text-preview", action="store_true", help="终端进度中打印ASR文本预览")
    args = parser.parse_args()

    files = list_audio_files(args.audio_dir)
    if args.limit > 0:
        files = files[: args.limit]
    if not files:
        raise RuntimeError("未找到音频文件。")

    adapter = QwenASRAdapter(
        model=args.model,
        api_key_env=args.api_key_env,
        base_url=args.base_url,
        timeout_s=180,
    )
    entity_resolver = EntityResolver(
        lexicon_path=args.lexicon,
        enabled=True,
        min_score=args.entity_min_score,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "sample_id",
        "audio_path",
        "source_mode",
        "annotation_unit",
        "mixed_dialogue",
        "comm_type_gt",
        "asr_text_auto",
        "resolved_text_auto",
        "ship_entities_auto",
        "location_entities_auto",
        "entity_candidates_auto",
        "primary_label_auto",
        "risk_level_auto",
        "risk_subtype_auto",
        "matched_keywords_auto",
        "emergency_score_auto",
        "asr_engine",
        "asr_error",
        "primary_label_gt",
        "risk_subtype_gt",
        "risk_level_gt",
        "transcript_gt",
        "ship_entities_gt",
        "location_entities_gt",
        "business_action_gt",
        "auto_reply_allowed_gt",
        "approval_required_gt",
        "audio_quality_gt",
        "overlap_gt",
        "urgent_prosody_gt",
        "first_risk_cue_time_ms",
        "stream_ttft_ms",
        "stream_final_latency_ms",
        "review_status",
        "review_priority",
        "review_notes",
    ]
    high_risk_file = None
    high_risk_writer = None
    if args.high_risk_out:
        args.high_risk_out.parent.mkdir(parents=True, exist_ok=True)
        high_risk_file = args.high_risk_out.open("w", encoding="utf-8", newline="")
        high_risk_writer = csv.DictWriter(high_risk_file, fieldnames=fieldnames)
        high_risk_writer.writeheader()
        high_risk_file.flush()

    written_count = 0
    high_risk_count = 0
    try:
        with args.out.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            f.flush()

            for i, audio in enumerate(files, start=1):
                text = ""
                engine = ""
                error = ""
                try:
                    result = adapter.transcribe(audio)
                    text = sanitize_asr_text(result.text or "")
                    engine = result.engine
                except Exception as exc:
                    error = str(exc)
                    if not args.continue_on_error:
                        raise

                sample_id = audio.stem
                resolution = entity_resolver.resolve(text)
                analysis = analyze_text(resolution.resolved_text)
                row: Dict[str, object] = {
                    "sample_id": sample_id,
                    "audio_path": str(audio),
                    "source_mode": args.source_mode,
                    "annotation_unit": "conversation_segment",
                    "mixed_dialogue": "",
                    "comm_type_gt": "",
                    "asr_text_auto": text,
                    "resolved_text_auto": resolution.resolved_text,
                    "ship_entities_auto": join_entities(resolution.candidates, "ship"),
                    "location_entities_auto": join_entities(resolution.candidates, "location"),
                    "entity_candidates_auto": serialize_candidates(resolution.candidates),
                    "primary_label_auto": analysis["primary_label"],
                    "risk_level_auto": analysis["risk_level"],
                    "risk_subtype_auto": analysis["risk_subtype"],
                    "matched_keywords_auto": "；".join(str(x) for x in analysis["matched_keywords"]),
                    "emergency_score_auto": analysis["emergency_score"],
                    "asr_engine": engine,
                    "asr_error": error,
                    "primary_label_gt": "",
                    "risk_subtype_gt": "",
                    "risk_level_gt": "",
                    "transcript_gt": "",
                    "ship_entities_gt": "",
                    "location_entities_gt": "",
                    "business_action_gt": "",
                    "auto_reply_allowed_gt": "",
                    "approval_required_gt": "",
                    "audio_quality_gt": "",
                    "overlap_gt": "",
                    "urgent_prosody_gt": "",
                    "first_risk_cue_time_ms": "",
                    "stream_ttft_ms": "",
                    "stream_final_latency_ms": "",
                    "review_status": "todo",
                    "review_priority": analysis["review_priority"] if not error else "high",
                    "review_notes": analysis["review_notes"] if not error else f"ASR失败，需排查: {error[:120]}",
                }
                writer.writerow(row)
                f.flush()
                written_count += 1

                if row["primary_label_auto"] == "emergency_risk" or row["review_priority"] in {"urgent", "high"}:
                    if high_risk_writer and high_risk_file:
                        high_risk_writer.writerow(row)
                        high_risk_file.flush()
                    high_risk_count += 1

                text_part = f" text={preview_text(text)}" if args.print_text_preview else ""
                print(
                    f"[{i}/{len(files)}] {sample_id} "
                    f"{row['primary_label_auto']} {row['risk_level_auto']} "
                    f"score={row['emergency_score_auto']} hits={row['matched_keywords_auto']}{text_part}",
                    flush=True,
                )
    finally:
        if high_risk_file:
            high_risk_file.close()

    print(f"[ok] wrote: {args.out} ({written_count} rows)")
    if args.high_risk_out:
        print(f"[ok] high risk candidates: {args.high_risk_out} ({high_risk_count} rows)")


if __name__ == "__main__":
    main()
