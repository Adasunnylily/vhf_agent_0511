from __future__ import annotations

import threading
import uuid
import re
import csv
import io
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, File, Form, HTTPException, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from app.domain.models import AudioSegment
from app.config import settings, uses_cloud_clip_asr, uses_dashscope_recognition
from app.main import (
    event_store,
    entity_resolver,
    inspection_simulator,
    knowledge_repository,
    pipeline,
    preprocessor,
    quality_stream_processor,
    realtime_stream_processor,
    scenario_simulator,
    shared_asr,
    shared_mic_asr,
    shared_asr_refiner,
    storage,
    stream_processor,
    task_manager,
    ws_manager,
)
from app.services.asr_compare import list_asr_compare_options
from app.services.asr import ASRResult, DashScopeParaformerASRAdapter
from app.services.audio_utils import pcm_rms, slice_wav_segment, write_pcm_wav
from app.services.ais_risk_analyzer import AISRiskAnalyzer
from app.services.demo_inspection import InspectionShip
from app.services.maritime_keywords import extract_maritime_keywords
from app.services.risk_engine import KEYWORD_GROUPS, KeywordRiskEngine
from app.services.streaming_file_asr import run_dashscope_streaming_file
from app.services.vhf_dialogue import build_vhf_dialogue_review, postprocess_vhf_dialogue

router = APIRouter(prefix="/api")
mic_risk_engine = KeywordRiskEngine()
stream_rule_risk_engine = KeywordRiskEngine(decision_mode="rules")
ais_risk_analyzer = AISRiskAnalyzer()
mic_sessions: Dict[str, Dict[str, Any]] = {}
mic_lock = threading.Lock()


@router.get("/config/public")
async def public_config() -> Dict[str, object]:
    return {
        "default_channel_id": settings.default_channel_id,
        "amap_key": settings.amap_key,
        "amap_security_js_code": settings.amap_security_js_code,
    }


def _sync_dynamic_ais_lexicon() -> None:
    entity_resolver.set_dynamic_lexicon(inspection_simulator.dynamic_lexicon_payload())


def _best_ais_context_from_entities(entities: List[Dict[str, Any]]) -> Optional[Dict[str, object]]:
    for entity in entities:
        if entity.get("entity_type") != "ship":
            continue
        metadata = entity.get("metadata")
        if isinstance(metadata, dict) and metadata:
            return metadata
        context = inspection_simulator.find_ship_context(str(entity.get("canonical") or ""))
        if context:
            return context
    return None


def _attach_high_risk_inspection(payload: Dict[str, Any]) -> Dict[str, Any]:
    if str(payload.get("risk_level") or "") not in {"L1", "L2", "L3"}:
        return payload
    ais_context = payload.get("ais_context")
    if not isinstance(ais_context, dict):
        ais_context = {}
    try:
        lng = float(ais_context.get("lng"))
        lat = float(ais_context.get("lat"))
    except (TypeError, ValueError):
        payload["inspection_context"] = {
            "triggered": False,
            "reason": "高危事件尚未匹配到可定位 AIS 船舶",
            "radius_m": 3000,
            "matched_ships": [],
        }
        return payload

    nearby = inspection_simulator.nearby_ships(
        lng=lng,
        lat=lat,
        radius_m=3000,
        exclude_ship_id=str(ais_context.get("ship_id") or ""),
    )
    payload["inspection_context"] = {
        "triggered": True,
        "reason": "高危事件自动触发周边船舶点验",
        "radius_m": 3000,
        "center_ship": ais_context,
        "matched_count": len(nearby),
        "matched_ships": nearby,
    }
    evidence = list(payload.get("evidence") or [])
    evidence.append(f"高危周边点验: 3公里内{len(nearby)}艘船舶")
    payload["evidence"] = evidence
    return payload


def _parse_time_to_ms(value: Any) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    text = text.replace("，", ".")
    if ":" not in text:
        try:
            return int(float(text) * 1000)
        except ValueError:
            return 0
    parts = [part.strip() for part in text.split(":")]
    try:
        if len(parts) == 3:
            hours, minutes, seconds = parts
            total = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        elif len(parts) == 2:
            minutes, seconds = parts
            total = int(minutes) * 60 + float(seconds)
        else:
            total = float(parts[-1])
        return int(total * 1000)
    except ValueError:
        return 0


def _pick_row_value(row: Dict[str, Any], candidates: List[str]) -> str:
    normalized = {str(key).strip().lower(): value for key, value in row.items()}
    for key in candidates:
        if key.lower() in normalized and str(normalized[key.lower()] or "").strip():
            return str(normalized[key.lower()]).strip()
    for raw_key, value in row.items():
        key = str(raw_key or "").strip().lower()
        if any(candidate.lower() in key for candidate in candidates) and str(value or "").strip():
            return str(value).strip()
    return ""


def _enrich_event_payloads(
    events: List[Dict[str, Any]],
    segments: List[AudioSegment],
) -> List[Dict[str, Any]]:
    segment_map = {segment.id: segment for segment in segments}
    enriched: List[Dict[str, Any]] = []
    for event in events:
        payload = dict(event)
        segment = segment_map.get(str(payload.get("segment_id")))
        if segment:
            payload["asr_text"] = segment.text
            payload["resolved_text"] = segment.resolved_text or segment.text
            payload["entities"] = segment.entities
            payload["ais_context"] = _best_ais_context_from_entities(segment.entities) or {}
            payload = ais_risk_analyzer.enrich_event(payload)
            payload = _attach_high_risk_inspection(payload)
        enriched.append(payload)
    return enriched


def _decision_business_type(payload: Dict[str, Any]) -> str:
    explicit = str(payload.get("business_type") or "").strip()
    if explicit in {
        "routine_report",
        "departure_request",
        "emergency_risk",
        "other_business",
        "invalid_or_noise",
    }:
        return explicit
    risk_level = str(payload.get("risk_level") or "")
    action_type = str(payload.get("action_type") or "")
    if risk_level in {"L1", "L2", "L3"}:
        return "emergency_risk"
    if action_type == "auto_reply":
        return "routine_report"
    if action_type == "manual_business":
        return "departure_request"
    if action_type == "manual_review":
        return "other_business"
    return "other_business"


def _default_decision_payload(segment: AudioSegment) -> Dict[str, Any]:
    requires_review = segment.confidence < 0.8
    event_id = f"evt_{uuid.uuid4().hex[:12]}"
    return {
        "event_id": event_id,
        "id": event_id,
        "segment_id": segment.id,
        "channel_id": segment.channel_id,
        "event_type": "低置信度语音" if requires_review else "一般业务通话",
        "risk_level": "MANUAL" if requires_review else "INFO",
        "summary": (
            "识别置信度较低，进入人工复核。"
            if requires_review
            else "未发现高危、自动回复或审批信号，保持监听并归档。"
        ),
        "evidence": [f"ASR置信度: {segment.confidence:.2f}"],
        "suggestion": "建议值班员复核原音。" if requires_review else "持续守听，无需主动回复。",
        "broadcast_text": "",
        "action_type": "manual_review" if requires_review else "archive_only",
        "requires_human_review": requires_review,
        "is_auto_reply": False,
        "review_status": "pending" if requires_review else "archived",
        "business_type": "other_business",
    }


def _persist_decisions(
    *,
    source_type: str,
    audio_path: str,
    segments: List[AudioSegment],
    events: List[Dict[str, Any]],
) -> List[Dict[str, object]]:
    event_by_segment = {str(event.get("segment_id") or ""): dict(event) for event in events}
    decisions: List[Dict[str, object]] = []
    for segment in segments:
        payload = event_by_segment.get(segment.id)
        if payload is None:
            payload = _default_decision_payload(segment)
        payload["source_type"] = source_type
        payload["audio_path"] = audio_path
        payload["asr_text"] = segment.text
        payload["resolved_text"] = segment.resolved_text or segment.text
        payload["entities"] = segment.entities
        payload["ais_context"] = _best_ais_context_from_entities(segment.entities) or {}
        payload = ais_risk_analyzer.enrich_event(payload)
        payload = _attach_high_risk_inspection(payload)
        payload["business_type"] = _decision_business_type(payload)
        payload["dialogue_review_text"] = _build_dialogue_review_template(
            str(payload["resolved_text"])
        )
        decisions.append(payload)
    if not segments:
        for event in events:
            payload = dict(event)
            payload["source_type"] = source_type
            payload["audio_path"] = audio_path
            payload = ais_risk_analyzer.enrich_event(payload)
            payload = _attach_high_risk_inspection(payload)
            payload["business_type"] = _decision_business_type(payload)
            decisions.append(payload)
    event_store.extend(decisions)
    return decisions


def _build_dialogue_review_template(text: str) -> str:
    return build_vhf_dialogue_review(text)


@router.get("/demo/scenarios")
async def list_demo_scenarios() -> Dict[str, List[Dict[str, object]]]:
    return {"items": scenario_simulator.list_scenarios()}


@router.get("/demo/inspection/ships")
async def list_demo_inspection_ships() -> Dict[str, object]:
    items = inspection_simulator.list_mock_ships()
    return {
        "items": items,
        "visible_count": len(items),
        "total_count": inspection_simulator.named_ship_count(),
    }


@router.get("/inspection/ships")
async def list_inspection_ships() -> Dict[str, object]:
    items = inspection_simulator.list_mock_ships()
    return {
        "items": items,
        "visible_count": len(items),
        "total_count": inspection_simulator.named_ship_count(),
    }


@router.get("/ais/ships")
async def list_ais_ships() -> Dict[str, object]:
    items = inspection_simulator.list_mock_ships()
    return {
        "items": items,
        "visible_count": len(items),
        "total_count": inspection_simulator.named_ship_count(),
    }


@router.post("/ais/analyze")
async def analyze_text_with_ais(
    text: str = Body(..., embed=True),
) -> Dict[str, object]:
    resolution = entity_resolver.resolve(text)
    entities = [candidate.to_dict() for candidate in resolution.candidates]
    ais_context = _best_ais_context_from_entities(entities) or {}
    analysis = ais_risk_analyzer.analyze(resolution.resolved_text, ais_context)
    return {
        "original_text": text,
        "resolved_text": resolution.resolved_text,
        "entities": entities,
        "ais_context": ais_context,
        "analysis": analysis,
    }


@router.post("/ais/ships/import")
async def import_ais_ships(
    file: UploadFile = File(...),
) -> Dict[str, object]:
    raw = await file.read()
    text = raw.decode("utf-8-sig")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix == ".json":
        payload = json.loads(text)
        if isinstance(payload, dict):
            rows = list(payload.get("items") or payload.get("ships") or [])
        elif isinstance(payload, list):
            rows = payload
        else:
            rows = []
    else:
        rows = list(csv.DictReader(io.StringIO(text)))
    ships = [
        inspection_simulator._ship_from_row(row)
        for row in rows
        if isinstance(row, dict) and (row.get("ship_name") or row.get("name"))
    ]
    result = inspection_simulator.upsert_ships(ships)
    _sync_dynamic_ais_lexicon()
    return {"ok": True, **result}


@router.post("/inspection/ships")
async def add_inspection_ship(
    ship_name: str = Form(...),
    ship_type: str = Form(...),
    tonnage_t: int = Form(...),
    draft_m: float = Form(...),
    destination: str = Form(""),
    position_label: str = Form(""),
    lng: float = Form(...),
    lat: float = Form(...),
    mmsi: str = Form(""),
    callsign: str = Form(""),
    imo: str = Form(""),
    length_m: float = Form(0),
    width_m: float = Form(0),
    sog_kn: float = Form(0),
    cog_deg: float = Form(0),
    heading_deg: float = Form(0),
    nav_status: str = Form("under_way"),
    cargo_type: str = Form(""),
    eta: str = Form(""),
    ais_update_time: str = Form(""),
    ais_source: str = Form("manual"),
) -> Dict[str, object]:
    if not (-180.0 <= lng <= 180.0 and -90.0 <= lat <= 90.0):
        raise HTTPException(status_code=400, detail="经纬度范围非法。")
    ship = InspectionShip(
        ship_id="",
        ship_name=ship_name.strip(),
        ship_type=ship_type.strip(),
        tonnage_t=int(tonnage_t),
        draft_m=float(draft_m),
        destination=destination.strip() or "待定",
        position_label=position_label.strip() or "自定义点位",
        lng=float(lng),
        lat=float(lat),
        mmsi=mmsi.strip(),
        callsign=callsign.strip(),
        imo=imo.strip(),
        length_m=float(length_m),
        width_m=float(width_m),
        sog_kn=float(sog_kn),
        cog_deg=float(cog_deg),
        heading_deg=float(heading_deg),
        nav_status=nav_status.strip() or "under_way",
        cargo_type=cargo_type.strip(),
        eta=eta.strip(),
        ais_update_time=ais_update_time.strip(),
        ais_source=ais_source.strip() or "manual",
    )
    item = inspection_simulator.add_ship(ship=ship)
    _sync_dynamic_ais_lexicon()
    return {"item": item}


@router.post("/inspection/ships/delete")
async def delete_inspection_ship(
    ship_id: str = Form(...),
) -> Dict[str, object]:
    removed = inspection_simulator.remove_ship(ship_id=ship_id)
    if not removed:
        raise HTTPException(status_code=404, detail="未找到该船舶。")
    _sync_dynamic_ais_lexicon()
    return {"ok": True, "ship_id": ship_id}


@router.get("/inspection/scenarios")
async def list_inspection_scenarios() -> Dict[str, List[Dict[str, object]]]:
    return {"items": inspection_simulator.list_scenarios()}


@router.post("/inspection/scenarios")
async def add_inspection_scenario(
    scenario_name: str = Form(...),
    notice_template: str = Form(...),
) -> Dict[str, object]:
    if not scenario_name.strip() or not notice_template.strip():
        raise HTTPException(status_code=400, detail="场景名称和模板不能为空。")
    item = inspection_simulator.add_scenario(
        scenario_name=scenario_name,
        notice_template=notice_template,
    )
    return {"item": item}


@router.get("/inspection/areas")
async def list_inspection_areas() -> Dict[str, List[Dict[str, object]]]:
    return {"items": inspection_simulator.list_areas()}


@router.post("/inspection/areas")
async def add_inspection_area(
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, object]:
    area_name = str(payload.get("area_name") or "").strip()
    geometry_type = str(payload.get("geometry_type") or "").strip()
    geometry = payload.get("geometry")
    if not area_name or geometry_type not in {"rect", "line", "polygon"}:
        raise HTTPException(status_code=400, detail="区域名称或区域类型非法。")
    if not isinstance(geometry, list) or len(geometry) < 2:
        raise HTTPException(status_code=400, detail="区域经纬度点位不足。")
    if geometry_type == "polygon" and len(geometry) < 3:
        raise HTTPException(status_code=400, detail="多边形至少需要三个点。")
    points = [
        [float(point[0]), float(point[1])]
        for point in geometry
        if isinstance(point, list) and len(point) >= 2
    ]
    item = inspection_simulator.add_area(
        area_name=area_name,
        geometry_type=geometry_type,
        geometry=points,
        line_buffer_m=float(payload.get("line_buffer_m") or 500.0),
    )
    return {"item": item}


@router.delete("/inspection/areas/{area_id}")
async def delete_inspection_area(area_id: str) -> Dict[str, object]:
    if not inspection_simulator.remove_area(area_id):
        raise HTTPException(status_code=404, detail="未找到该点验区域。")
    return {"ok": True, "area_id": area_id}


@router.post("/inspection/filter")
async def filter_inspection_ships(
    area_name: str = Form("北仑主航道A3段"),
    min_draft_m: float = Form(10.0),
    min_tonnage_t: int = Form(5000),
    area_geometry: str = Form(""),
    ship_types: str = Form(""),
    min_speed_kn: float = Form(0.0),
    max_speed_kn: float = Form(999.0),
    destination_keyword: str = Form(""),
    ship_ids: str = Form(""),
) -> Dict[str, object]:
    allowed_ship_types = [item.strip() for item in ship_types.split(",") if item.strip()]
    specific_ship_ids = [item.strip() for item in ship_ids.split(",") if item.strip()]
    matched = inspection_simulator.filter_ships(
        area_name=area_name,
        min_draft_m=min_draft_m,
        min_tonnage_t=min_tonnage_t,
        area_geometry=area_geometry,
        allowed_ship_types=allowed_ship_types,
        min_speed_kn=min_speed_kn,
        max_speed_kn=max_speed_kn,
        destination_keyword=destination_keyword,
        specific_ship_ids=specific_ship_ids,
    )
    return {
        "area_name": area_name,
        "min_draft_m": min_draft_m,
        "min_tonnage_t": min_tonnage_t,
        "ship_types": allowed_ship_types,
        "min_speed_kn": min_speed_kn,
        "max_speed_kn": max_speed_kn,
        "destination_keyword": destination_keyword,
        "ship_ids": specific_ship_ids,
        "matched_count": len(matched),
        "items": [ship.to_dict() for ship in matched],
    }


@router.post("/inspection/preview-notices")
async def preview_inspection_notices(
    area_name: str = Form("北仑主航道A3段"),
    min_draft_m: float = Form(10.0),
    min_tonnage_t: int = Form(5000),
    notice_template: str = Form("{船名}，请注意，您已进入{区域}，请按规定守听并回复。"),
    area_geometry: str = Form(""),
    ship_types: str = Form(""),
    min_speed_kn: float = Form(0.0),
    max_speed_kn: float = Form(999.0),
    destination_keyword: str = Form(""),
    ship_ids: str = Form(""),
) -> Dict[str, object]:
    allowed_ship_types = [item.strip() for item in ship_types.split(",") if item.strip()]
    specific_ship_ids = [item.strip() for item in ship_ids.split(",") if item.strip()]
    matched = inspection_simulator.filter_ships(
        area_name=area_name,
        min_draft_m=min_draft_m,
        min_tonnage_t=min_tonnage_t,
        area_geometry=area_geometry,
        allowed_ship_types=allowed_ship_types,
        min_speed_kn=min_speed_kn,
        max_speed_kn=max_speed_kn,
        destination_keyword=destination_keyword,
        specific_ship_ids=specific_ship_ids,
    )
    notices = [
        {
            "ship": ship.to_dict(),
            "notice_text": inspection_simulator.build_notice_text(ship, area_name, notice_template),
        }
        for ship in matched
    ]
    return {
        "matched_count": len(matched),
        "items": notices,
    }


@router.get("/asr/compare-options")
async def get_asr_compare_options() -> Dict[str, List[Dict[str, object]]]:
    return {"items": list_asr_compare_options()}


@router.get("/knowledge/documents")
async def list_knowledge_documents() -> Dict[str, List[Dict[str, str]]]:
    return {"items": knowledge_repository.list_entries()}


@router.get("/knowledge/search")
async def search_knowledge(q: str = "") -> Dict[str, object]:
    items = knowledge_repository.search(q)
    return {"query": q, "count": len(items), "items": items[:20]}


@router.post("/knowledge/documents/import")
async def import_knowledge_document(
    file: UploadFile = File(...),
    category: str = Form("法规资料"),
) -> Dict[str, object]:
    item = knowledge_repository.import_document(
        source=file.file,
        filename=file.filename or "knowledge.bin",
        category=category,
    )
    return {"item": item}


@router.post("/demo/scenario/{scenario_id}")
async def run_demo_scenario(
    scenario_id: str,
    channel_id: str = Form("vhf_demo_01"),
) -> Dict[str, str]:
    task = task_manager.create(filename=f"scenario:{scenario_id}", channel_id=channel_id)

    def runner() -> None:
        segments, events, meta = scenario_simulator.run(
            scenario_id=scenario_id,
            channel_id=channel_id,
        )
        persisted_events = _persist_decisions(
            source_type="demo_scenario",
            audio_path=f"scenario:{scenario_id}",
            segments=segments,
            events=[event.to_dict() for event in events],
        )
        task_manager.update(
            task.id,
            status="completed",
            segments=[segment.to_dict() for segment in segments],
            events=persisted_events,
            meta=meta,
        )

    task_manager.run_async(task.id, runner)
    return {
        "task_id": task.id,
        "status": "queued",
        "channel_id": channel_id,
        "scenario_id": scenario_id,
    }


@router.get("/demo/continuous-test-set")
async def list_continuous_test_set(
    limit: int = 20,
) -> Dict[str, object]:
    root = settings.continuous_demo_dir
    if not root.exists():
        return {
            "root": str(root),
            "exists": False,
            "items": [],
            "message": "连续守听测试集目录不存在，请在服务器配置 VHF_CONTINUOUS_DEMO_DIR。",
        }
    demo_items = _continuous_demo_items(root, limit=max(1, min(limit, 200)))
    return {
        "root": str(root),
        "concat_root": str(settings.continuous_concat_dir),
        "exists": True,
        "mode": "concat_labeled_stream" if demo_items and demo_items[0].get("kind") == "concat_segment" else "file_sequence",
        "count": len(demo_items),
        "items": [
            {
                "filename": str(item.get("filename") or Path(item["source"]).name),
                "path": str(item["source"]),
                "start_ms": item.get("start_ms"),
                "end_ms": item.get("end_ms"),
                "duration_ms": (
                    int(item["end_ms"]) - int(item["start_ms"])
                    if item.get("start_ms") is not None and item.get("end_ms") is not None
                    else None
                ),
                "class_label": item.get("class_label") or "",
                "source_file": item.get("source_file") or "",
            }
            for item in demo_items
        ],
    }


@router.get("/demo/continuous-test-set/audio/{index}")
async def get_continuous_test_audio(index: int) -> FileResponse:
    root = settings.continuous_demo_dir
    if not root.exists():
        raise HTTPException(status_code=404, detail=f"连续守听测试集目录不存在: {root}")
    demo_items = _continuous_demo_items(root, limit=200)
    if index < 0 or index >= len(demo_items):
        raise HTTPException(status_code=404, detail="音频片段不存在")
    item = demo_items[index]
    preview_path = _materialize_continuous_item_audio(item)
    return FileResponse(preview_path, media_type="audio/wav", filename=f"{Path(item['source']).stem}_{index:03d}_preview.wav")


@router.post("/demo/continuous-test-set")
async def run_continuous_test_set(
    channel_id: str = Form("vhf_demo_01"),
    limit: int = Form(8),
    speed_ms: int = Form(600),
) -> Dict[str, object]:
    root = settings.continuous_demo_dir
    if not root.exists():
        raise HTTPException(
            status_code=404,
            detail=f"连续守听测试集目录不存在: {root}",
        )
    demo_items = _continuous_demo_items(root, limit=max(1, min(limit, 50)))
    if not demo_items:
        raise HTTPException(status_code=404, detail=f"目录内未找到音频文件: {root}")

    task = task_manager.create(filename=f"continuous:{root.name}", channel_id=channel_id)

    def runner() -> None:
        all_segments: List[AudioSegment] = []
        all_events: List[Dict[str, object]] = []
        conversations: List[Dict[str, object]] = []
        ws_manager.publish(
            channel_id,
            {
                "type": "continuous_status",
                "stage": "started",
                "channel_id": channel_id,
                "total": len(demo_items),
            },
        )
        for index, item in enumerate(demo_items):
            audio_path = Path(item["source"])
            ws_manager.publish(
                channel_id,
                {
                    "type": "continuous_status",
                    "stage": "listening",
                    "channel_id": channel_id,
                    "index": index,
                    "filename": str(item.get("filename") or audio_path.name),
                    "start_ms": item.get("start_ms"),
                    "end_ms": item.get("end_ms"),
                },
            )
            try:
                processing_path = _materialize_continuous_item_audio(item)
                run = pipeline.process(
                    file_path=processing_path,
                    channel_id=channel_id,
                    force_full_file_transcribe=False,
                    enable_denoise=False,
                )
                event_payloads = _enrich_event_payloads(
                    [event.to_dict() for event in run.events],
                    run.segments,
                )
                persisted_events = _persist_decisions(
                    source_type="continuous_listening_demo",
                    audio_path=str(processing_path),
                    segments=run.segments,
                    events=event_payloads,
                )
                all_segments.extend(run.segments)
                all_events.extend(persisted_events)
                dialogue_text = build_vhf_dialogue_review(
                    "\n".join(segment.resolved_text or segment.text for segment in run.segments)
                )
                ais_alignment = _build_continuous_ais_alignment(
                    index=index,
                    segments=run.segments,
                    events=persisted_events,
                )
                conversation = {
                    "index": index,
                    "filename": str(item.get("filename") or audio_path.name),
                    "audio_path": str(processing_path),
                    "source_audio_path": str(audio_path),
                    "audio_url": f"/api/demo/continuous-test-set/audio/{index}",
                    "start_ms": item.get("start_ms"),
                    "end_ms": item.get("end_ms"),
                    "class_label": item.get("class_label") or "",
                    "source_file": item.get("source_file") or "",
                    "segments": [segment.to_dict() for segment in run.segments],
                    "events": persisted_events,
                    "ais_alignment": ais_alignment,
                    "dialogue_review_text": dialogue_text,
                    "status": "completed",
                }
            except Exception as exc:  # noqa: BLE001 - keep the demo stream alive.
                conversation = {
                    "index": index,
                    "filename": str(item.get("filename") or audio_path.name),
                    "audio_path": str(audio_path),
                    "audio_url": f"/api/demo/continuous-test-set/audio/{index}",
                    "start_ms": item.get("start_ms"),
                    "end_ms": item.get("end_ms"),
                    "class_label": item.get("class_label") or "",
                    "source_file": item.get("source_file") or "",
                    "segments": [],
                    "events": [],
                    "ais_alignment": _build_continuous_ais_alignment(index=index, segments=[], events=[]),
                    "dialogue_review_text": "",
                    "status": "failed",
                    "error": str(exc),
                }
            conversations.append(conversation)
            task_manager.update(
                task.id,
                status="running",
                segments=[segment.to_dict() for segment in all_segments],
                events=all_events,
                meta={
                    "task_type": "continuous_listening_demo",
                    "root": str(root),
                    "mode": "concat_labeled_stream" if demo_items and demo_items[0].get("kind") == "concat_segment" else "file_sequence",
                    "total": len(demo_items),
                    "completed": len(conversations),
                    "conversations": conversations,
                },
            )
            ws_manager.publish(
                channel_id,
                {
                    "type": "continuous_conversation",
                    "channel_id": channel_id,
                    **conversation,
                },
            )
            if speed_ms > 0:
                threading.Event().wait(min(speed_ms, 3000) / 1000)

        task_manager.update(
            task.id,
            status="completed",
            segments=[segment.to_dict() for segment in all_segments],
            events=all_events,
            meta={
                "task_type": "continuous_listening_demo",
                "root": str(root),
                "mode": "concat_labeled_stream" if demo_items and demo_items[0].get("kind") == "concat_segment" else "file_sequence",
                "total": len(demo_items),
                "completed": len(conversations),
                "conversations": conversations,
            },
        )
        ws_manager.publish(
            channel_id,
            {
                "type": "continuous_status",
                "stage": "completed",
                "channel_id": channel_id,
                "total": len(demo_items),
                "events": len(all_events),
            },
        )

    task_manager.run_async(task.id, runner)
    return {
        "task_id": task.id,
        "status": "queued",
        "channel_id": channel_id,
        "root": str(root),
        "count": len(demo_items),
    }


def _continuous_audio_files(root: Path, *, limit: int) -> List[Path]:
    suffixes = {".wav", ".mp3", ".m4a", ".flac", ".aac", ".ogg", ".webm"}
    files = [
        item
        for item in root.rglob("*")
        if item.is_file() and item.suffix.lower() in suffixes
    ]
    return sorted(files, key=lambda item: item.name)[:limit]


def _continuous_concat_items(limit: int) -> List[Dict[str, Any]]:
    root = settings.continuous_concat_dir
    audio_path = root / "shuffled_concat.wav"
    labels_path = root / "shuffled_concat_labels.csv"
    manifest_path = root / "shuffled_concat_manifest.json"
    if not audio_path.exists():
        return []

    items: List[Dict[str, Any]] = []
    if labels_path.exists():
        with labels_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for index, row in enumerate(reader):
                if index >= limit:
                    break
                range_text = _pick_row_value(row, ["起止时间", "time_range", "range"])
                start_ms = _parse_time_to_ms(_pick_row_value(row, ["start_ms", "start_sec", "start", "开始", "起始时间", "开始时间"]))
                end_ms = _parse_time_to_ms(_pick_row_value(row, ["end_ms", "end_sec", "end", "结束", "结束时间"]))
                if range_text and (not start_ms or not end_ms):
                    parts = re.split(r"\s*(?:-|~|—|–|至|到)\s*", range_text, maxsplit=1)
                    if len(parts) == 2:
                        start_ms = _parse_time_to_ms(parts[0])
                        end_ms = _parse_time_to_ms(parts[1])
                if end_ms <= start_ms:
                    continue
                class_label = _pick_row_value(row, ["分类", "label", "business_type", "category_code", "category"])
                source_name = _pick_row_value(row, ["原文件名", "filename", "source", "source_file", "文件"])
                items.append(
                    {
                        "kind": "concat_segment",
                        "source": audio_path,
                        "index": len(items),
                        "start_ms": start_ms,
                        "end_ms": end_ms,
                        "filename": f"{len(items) + 1:03d}_{class_label or 'unknown'}_{source_name or audio_path.name}",
                        "class_label": class_label,
                        "source_file": source_name,
                    }
                )
    elif manifest_path.exists():
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        rows = data if isinstance(data, list) else data.get("items") or data.get("segments") or []
        for row in rows[:limit]:
            start_ms = int(row.get("start_ms") or _parse_time_to_ms(row.get("start_time") or row.get("start") or "0"))
            end_ms = int(row.get("end_ms") or _parse_time_to_ms(row.get("end_time") or row.get("end") or "0"))
            if end_ms <= start_ms:
                continue
            class_label = str(row.get("classification") or row.get("category") or row.get("label") or "")
            source_name = str(row.get("filename") or row.get("source_file") or row.get("source") or "")
            items.append(
                {
                    "kind": "concat_segment",
                    "source": audio_path,
                    "index": len(items),
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "filename": f"{len(items) + 1:03d}_{class_label or 'unknown'}_{source_name or audio_path.name}",
                    "class_label": class_label,
                    "source_file": source_name,
                }
            )
    return items[:limit]


def _continuous_demo_items(root: Path, *, limit: int) -> List[Dict[str, Any]]:
    concat_items = _continuous_concat_items(limit)
    if concat_items:
        return concat_items
    return [
        {
            "kind": "file",
            "source": audio_path,
            "index": index,
            "start_ms": None,
            "end_ms": None,
            "filename": audio_path.name,
            "class_label": "",
            "source_file": audio_path.name,
        }
        for index, audio_path in enumerate(_continuous_audio_files(root, limit=limit))
    ]


def _continuous_preview_path(item: Dict[str, Any]) -> Path:
    source = Path(item["source"])
    preview_dir = settings.data_dir / "audio_preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    start = item.get("start_ms")
    end = item.get("end_ms")
    suffix = f"_{start}_{end}" if start is not None and end is not None else ""
    return preview_dir / f"{source.stem}{suffix}_{int(source.stat().st_mtime)}_preview.wav"


def _ensure_browser_wav(
    source_path: Path,
    target_path: Path,
    *,
    start_ms: Optional[int] = None,
    end_ms: Optional[int] = None,
) -> Path:
    if target_path.exists():
        return target_path
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise HTTPException(status_code=500, detail="未找到 ffmpeg，无法生成浏览器可播放预览音频")
    command = [ffmpeg, "-y"]
    if start_ms is not None:
        command.extend(["-ss", f"{start_ms / 1000:.3f}"])
    command.extend(["-i", str(source_path)])
    if start_ms is not None and end_ms is not None and end_ms > start_ms:
        command.extend(["-t", f"{(end_ms - start_ms) / 1000:.3f}"])
    command.extend(["-vn", "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le", str(target_path)])
    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="ignore")
        raise HTTPException(status_code=500, detail=f"音频预览转码失败: {stderr}") from exc
    return target_path


def _materialize_continuous_item_audio(item: Dict[str, Any]) -> Path:
    return _ensure_browser_wav(
        Path(item["source"]),
        _continuous_preview_path(item),
        start_ms=item.get("start_ms"),
        end_ms=item.get("end_ms"),
    )


def _build_continuous_ais_alignment(
    *,
    index: int,
    segments: List[AudioSegment],
    events: List[Dict[str, Any]],
) -> Dict[str, object]:
    entities = [
        entity
        for segment in segments
        for entity in getattr(segment, "entities", []) or []
        if isinstance(entity, dict)
    ]
    ship_context = _best_ais_context_from_entities(entities)
    if not ship_context:
        named_ships = inspection_simulator.list_mock_ships(limit=15)
        if named_ships:
            ship_context = named_ships[index % len(named_ships)]
    ship_context = ship_context or {}
    lng = float(ship_context.get("lng") or 121.8842)
    lat = float(ship_context.get("lat") or 29.9138)
    confidence = 0.88 if ship_context.get("ship_name") else 0.42
    if entities:
        confidence = min(0.96, confidence + 0.06)
    return {
        "vhf_event_id": (events[0].get("event_id") if events else "") or f"continuous_{index}",
        "matched_ship_id": ship_context.get("ship_id") or ship_context.get("mmsi") or f"sim_ship_{index}",
        "ship_name": ship_context.get("ship_name") or f"模拟船舶{index + 1}",
        "mmsi": ship_context.get("mmsi") or "",
        "callsign": ship_context.get("callsign") or "",
        "ship_type": ship_context.get("ship_type") or "待核验船舶",
        "confidence_score": round(confidence, 2),
        "time_offset_s": 0,
        "spatial_distance_m": 120 + index * 35,
        "position_label": ship_context.get("position_label") or "北仑山甚高频覆盖水域",
        "sog_kn": ship_context.get("sog_kn"),
        "heading_deg": ship_context.get("heading_deg") or ship_context.get("cog_deg"),
        "lng": lng,
        "lat": lat,
        "route": [
            [round(lng - 0.012, 6), round(lat - 0.006, 6)],
            [round(lng, 6), round(lat, 6)],
            [round(lng + 0.011, 6), round(lat + 0.007, 6)],
        ],
        "source": "simulated_ais_from_voice",
    }


@router.post("/demo/inspection-task")
async def run_demo_inspection_task(
    channel_id: str = Form("vhf_demo_01"),
    area_name: str = Form("北仑主航道A3段"),
    min_draft_m: float = Form(10.0),
    min_tonnage_t: int = Form(5000),
    scenario_id: str = Form(""),
    notice_template: str = Form("{船名}，请注意，您已进入{区域}，请按规定守听并回复。"),
    area_geometry: str = Form(""),
    ship_types: str = Form(""),
    min_speed_kn: float = Form(0.0),
    max_speed_kn: float = Form(999.0),
    destination_keyword: str = Form(""),
    ship_ids: str = Form(""),
) -> Dict[str, str]:
    task = task_manager.create(filename=f"inspection:{area_name}", channel_id=channel_id)
    allowed_ship_types = [item.strip() for item in ship_types.split(",") if item.strip()]
    specific_ship_ids = [item.strip() for item in ship_ids.split(",") if item.strip()]

    def runner() -> None:
        resolved_template = inspection_simulator.resolve_template(
            scenario_id=scenario_id,
            fallback_template=notice_template,
        )
        meta = inspection_simulator.run(
            channel_id=channel_id,
            area_name=area_name,
            min_draft_m=min_draft_m,
            min_tonnage_t=min_tonnage_t,
            notice_template=resolved_template,
            area_geometry=area_geometry,
            allowed_ship_types=allowed_ship_types,
            min_speed_kn=min_speed_kn,
            max_speed_kn=max_speed_kn,
            destination_keyword=destination_keyword,
            specific_ship_ids=specific_ship_ids,
        )
        task_manager.update(
            task.id,
            status="completed",
            segments=[],
            events=[],
            meta={
                "task_type": "ais_inspection_notice",
                **meta,
            },
        )
        inspection_events = [
            {
                "event_id": f"evt_{uuid.uuid4().hex[:12]}",
                "event_type": "AIS点验通知",
                "risk_level": "INFO",
                "business_type": "inspection_notice",
                "action_type": "inspection_notice",
                "requires_human_review": False,
                "is_auto_reply": True,
                "review_status": "broadcasted",
                "summary": f"{notice['ship']['ship_name']} 已生成点验通知。",
                "evidence": [f"点验区域: {area_name}"],
                "suggestion": notice["notice_text"],
                "broadcast_text": notice["notice_text"],
                "ais_context": notice["ship"],
                "source_type": "inspection",
                "audio_path": "",
            }
            for notice in meta["notices"]
        ]
        event_store.extend(inspection_events)

    task_manager.run_async(task.id, runner)
    return {
        "task_id": task.id,
        "status": "queued",
        "channel_id": channel_id,
        "area_name": area_name,
    }


@router.post("/inspection/run")
async def run_inspection_task(
    channel_id: str = Form("vhf_demo_01"),
    area_name: str = Form("北仑主航道A3段"),
    min_draft_m: float = Form(10.0),
    min_tonnage_t: int = Form(5000),
    scenario_id: str = Form(""),
    notice_template: str = Form("{船名}，请注意，您已进入{区域}，请按规定守听并回复。"),
    area_geometry: str = Form(""),
    ship_types: str = Form(""),
    min_speed_kn: float = Form(0.0),
    max_speed_kn: float = Form(999.0),
    destination_keyword: str = Form(""),
    ship_ids: str = Form(""),
) -> Dict[str, str]:
    return await run_demo_inspection_task(
        channel_id=channel_id,
        area_name=area_name,
        min_draft_m=min_draft_m,
        min_tonnage_t=min_tonnage_t,
        scenario_id=scenario_id,
        notice_template=notice_template,
        area_geometry=area_geometry,
        ship_types=ship_types,
        min_speed_kn=min_speed_kn,
        max_speed_kn=max_speed_kn,
        destination_keyword=destination_keyword,
        ship_ids=ship_ids,
    )


@router.post("/inspection/tts")
async def run_inspection_tts(
    channel_id: str = Form("vhf_demo_01"),
    area_name: str = Form("北仑主航道A3段"),
    min_draft_m: float = Form(10.0),
    min_tonnage_t: int = Form(5000),
    scenario_id: str = Form(""),
    notice_template: str = Form("{船名}，请注意，您已进入{区域}，请按规定守听并回复。"),
    area_geometry: str = Form(""),
    ship_types: str = Form(""),
    min_speed_kn: float = Form(0.0),
    max_speed_kn: float = Form(999.0),
    destination_keyword: str = Form(""),
    ship_ids: str = Form(""),
) -> Dict[str, str]:
    return await run_demo_inspection_task(
        channel_id=channel_id,
        area_name=area_name,
        min_draft_m=min_draft_m,
        min_tonnage_t=min_tonnage_t,
        scenario_id=scenario_id,
        notice_template=notice_template,
        area_geometry=area_geometry,
        ship_types=ship_types,
        min_speed_kn=min_speed_kn,
        max_speed_kn=max_speed_kn,
        destination_keyword=destination_keyword,
        ship_ids=ship_ids,
    )


@router.post("/audio/upload")
async def upload_audio(
    file: UploadFile = File(...),
    channel_id: str = Form("vhf_demo_01"),
    transcript_override: Optional[str] = Form(None),
    denoise_mode: str = Form("off"),
) -> Dict[str, str]:
    task = task_manager.create(filename=file.filename or "unknown", channel_id=channel_id)
    saved_path = storage.save_upload(file.file, file.filename or "upload.bin")

    def runner() -> None:
        mode = denoise_mode.strip().lower()
        if mode not in {"off", "on", "compare"}:
            raise RuntimeError("denoise_mode 仅支持 off、on、compare。")

        if mode == "compare":
            base_run = pipeline.process(
                file_path=saved_path,
                channel_id=channel_id,
                transcript_override=transcript_override,
                force_full_file_transcribe=False,
                enable_denoise=False,
            )
            denoise_run = pipeline.process(
                file_path=saved_path,
                channel_id=channel_id,
                transcript_override=transcript_override,
                force_full_file_transcribe=False,
                enable_denoise=True,
            )
            combined_events = _enrich_event_payloads(
                [*[event.to_dict() for event in base_run.events], *[event.to_dict() for event in denoise_run.events]],
                [*base_run.segments, *denoise_run.segments],
            )
            persisted_events = _persist_decisions(
                source_type="audio_upload",
                audio_path=str(saved_path),
                segments=[*base_run.segments, *denoise_run.segments],
                events=combined_events,
            )
            task_manager.update(
                task.id,
                status="completed",
                segments=[
                    {
                        "variant": "original",
                        "items": [segment.to_dict() for segment in base_run.segments],
                    },
                    {
                        "variant": "denoised",
                        "items": [segment.to_dict() for segment in denoise_run.segments],
                    },
                ],
                events=persisted_events,
                meta={
                    "denoise_mode": "compare",
                    "original_preprocess": base_run.preprocess,
                    "denoised_preprocess": denoise_run.preprocess,
                    "original_texts": [segment.text for segment in base_run.segments],
                    "denoised_texts": [segment.text for segment in denoise_run.segments],
                },
            )
            return

        run = pipeline.process(
            file_path=saved_path,
            channel_id=channel_id,
            transcript_override=transcript_override,
            force_full_file_transcribe=False,
            enable_denoise=(mode == "on"),
        )
        event_payloads = _enrich_event_payloads([event.to_dict() for event in run.events], run.segments)
        persisted_events = _persist_decisions(
            source_type="audio_upload",
            audio_path=str(saved_path),
            segments=run.segments,
            events=event_payloads,
        )
        task_manager.update(
            task.id,
            status="completed",
            segments=[segment.to_dict() for segment in run.segments],
            events=persisted_events,
            meta={
                "denoise_mode": mode,
                "preprocess": run.preprocess,
            },
        )

    task_manager.run_async(task.id, runner)
    return {"task_id": task.id, "status": "queued", "denoise_mode": denoise_mode}


@router.post("/stream/upload")
async def upload_stream_simulation(
    file: UploadFile = File(...),
    channel_id: str = Form("vhf_demo_01"),
    transcript_override: Optional[str] = Form(None),
    denoise_mode: str = Form("off"),
    asr_mode: str = Form("primary"),
) -> Dict[str, str]:
    task = task_manager.create(filename=file.filename or "unknown", channel_id=channel_id)
    saved_path = storage.save_upload(file.file, file.filename or "upload.bin")

    def runner() -> None:
        live_segments: List[AudioSegment] = []
        live_events: List[Dict[str, object]] = []
        use_quality_asr = asr_mode.strip().lower() == "quality"
        active_processor = quality_stream_processor if use_quality_asr else stream_processor
        mode = "qwen_vad_quality_replay" if use_quality_asr else "vad_incremental_replay"

        def on_segment(
            segment: AudioSegment,
            segment_events: List[Any],
            index: int,
            total: int,
        ) -> None:
            live_segments.append(segment)
            payloads = _enrich_event_payloads(
                [event.to_dict() for event in segment_events],
                [segment],
            )
            if not payloads:
                fallback = _default_decision_payload(segment)
                fallback["asr_text"] = segment.text
                fallback["resolved_text"] = segment.resolved_text or segment.text
                fallback["entities"] = segment.entities
                fallback["ais_context"] = _best_ais_context_from_entities(segment.entities) or {}
                payloads = [ais_risk_analyzer.enrich_event(fallback)]
            for payload in payloads:
                payload["business_type"] = _decision_business_type(payload)
            live_events.extend(payloads)
            task_manager.update(
                task.id,
                status="running",
                segments=[item.to_dict() for item in live_segments],
                events=live_events,
                meta={
                    "denoise_mode": denoise_mode.strip().lower(),
                    "mode": mode,
                    "asr_model": settings.mic_asr_model if use_quality_asr else settings.asr_model,
                    "processed_path": segment.file_path,
                    "completed_segments": index + 1,
                    "total_segments": total,
                },
            )

        segments, events = active_processor.process_file_stream(
            file_path=saved_path,
            channel_id=channel_id,
            transcript_override=transcript_override,
            enable_denoise=denoise_mode.strip().lower() == "on",
            on_segment=on_segment,
        )
        event_payloads = _enrich_event_payloads([event.to_dict() for event in events], segments)
        persisted_events = _persist_decisions(
            source_type="stream_sim",
            audio_path=str(saved_path),
            segments=segments,
            events=event_payloads,
        )
        task_manager.update(
            task.id,
            status="completed",
            segments=[segment.to_dict() for segment in segments],
            events=persisted_events,
            meta={
                "denoise_mode": denoise_mode.strip().lower(),
                "mode": mode,
                "asr_model": settings.mic_asr_model if use_quality_asr else settings.asr_model,
                "processed_path": segments[0].file_path if segments else str(saved_path),
                "completed_segments": len(segments),
                "total_segments": len(segments),
            },
        )

    task_manager.run_async(task.id, runner)
    return {
        "task_id": task.id,
        "status": "queued",
        "channel_id": channel_id,
        "denoise_mode": denoise_mode,
        "mode": "qwen_vad_quality_replay" if asr_mode.strip().lower() == "quality" else "vad_incremental_replay",
    }


@router.post("/streaming/upload")
async def upload_true_streaming(
    file: UploadFile = File(...),
    channel_id: str = Form("vhf_demo_01"),
    denoise_mode: str = Form("off"),
) -> Dict[str, str]:
    task = task_manager.create(filename=file.filename or "unknown", channel_id=channel_id)
    saved_path = storage.save_upload(file.file, file.filename or "upload.bin")

    def runner() -> None:
        if uses_cloud_clip_asr(settings.asr_provider):
            # Cloud clip ASR: Qwen accepts compressed audio; DashScope Recognition needs 16k wav.
            if uses_dashscope_recognition(settings.asr_provider):
                chunk_results, events = stream_processor.process_file_stream(
                    file_path=saved_path,
                    channel_id=channel_id,
                    enable_denoise=denoise_mode.strip().lower() == "on",
                )
                mode = "dashscope_paraformer_chunk_replay"
            else:
                chunk_results, events = stream_processor.process_file_stream(
                    file_path=saved_path,
                    channel_id=channel_id,
                    enable_denoise=denoise_mode.strip().lower() == "on",
                )
                mode = "qwen_api_chunk_replay"
        else:
            chunk_results, events = realtime_stream_processor.process_file_stream(
                file_path=saved_path,
                channel_id=channel_id,
                enable_denoise=denoise_mode.strip().lower() == "on",
            )
            mode = "paraformer_streaming"
        event_payloads = (
            _enrich_event_payloads([event.to_dict() for event in events], chunk_results)  # type: ignore[arg-type]
            if chunk_results and hasattr(chunk_results[0], "to_dict") and hasattr(chunk_results[0], "id")
            else [event.to_dict() for event in events]
        )
        typed_segments = [
            item for item in chunk_results if isinstance(item, AudioSegment)
        ]
        persisted_events = _persist_decisions(
            source_type="stream_replay",
            audio_path=str(saved_path),
            segments=typed_segments,
            events=event_payloads,
        )
        task_manager.update(
            task.id,
            status="completed",
            segments=[_as_segment_payload(item, index) for index, item in enumerate(chunk_results)],
            events=persisted_events,
            meta={"denoise_mode": denoise_mode.strip().lower(), "mode": mode},
        )

    task_manager.run_async(task.id, runner)
    return {
        "task_id": task.id,
        "status": "queued",
        "channel_id": channel_id,
        "mode": (
            "dashscope_paraformer_chunk_replay"
            if uses_dashscope_recognition(settings.asr_provider)
            else "qwen_api_chunk_replay"
            if settings.asr_provider == "qwen_api"
            else "paraformer_streaming"
        ),
    }


@router.post("/streaming/replay")
async def upload_websocket_streaming_replay(
    file: UploadFile = File(...),
    channel_id: str = Form("vhf_demo_01"),
    playback_speed: float = Form(1.0),
) -> Dict[str, str]:
    if not isinstance(shared_asr, DashScopeParaformerASRAdapter):
        raise HTTPException(
            status_code=400,
            detail="当前 ASR Provider 不支持 DashScope WebSocket partial 流式回放。",
        )
    task = task_manager.create(filename=file.filename or "stream.wav", channel_id=channel_id)
    saved_path = storage.save_upload(file.file, file.filename or "stream.wav")

    def runner() -> None:
        prepared = preprocessor.prepare(file_path=saved_path, enable_denoise=False)
        processed_path = Path(prepared.processed_path) if prepared.processed_path else saved_path
        stream_started_at = time.perf_counter()
        partial_state: Dict[str, Any] = {
            "finalized": [],
            "utterances": [],
            "latest": "",
            "count": 0,
            "ttft_ms": None,
        }

        def on_partial(text: str, is_final: bool, row: Dict[str, Any]) -> None:
            partial_state["count"] += 1
            if partial_state["ttft_ms"] is None:
                partial_state["ttft_ms"] = round(
                    (time.perf_counter() - stream_started_at) * 1000,
                    1,
                )
            if is_final:
                if not partial_state["finalized"] or partial_state["finalized"][-1] != text:
                    partial_state["finalized"].append(text)
                    sentence = {
                        "text": text,
                        "speaker_id": row.get("speaker_id", row.get("speaker")),
                        "begin_time": row.get("begin_time", row.get("start_time")),
                        "end_time": row.get("end_time"),
                    }
                    start_ms = int(float(sentence.get("begin_time") or 0))
                    end_ms = int(float(sentence.get("end_time") or start_ms + 1000))
                    if end_ms <= start_ms:
                        end_ms = start_ms + 1000
                    resolution = entity_resolver.resolve(text)
                    resolved_text = resolution.resolved_text
                    segment = AudioSegment(
                        id=f"stream_utt_{len(partial_state['utterances']):04d}",
                        channel_id=channel_id,
                        file_path=str(processed_path),
                        clip_path=str(processed_path),
                        start_ms=start_ms,
                        end_ms=end_ms,
                        duration_ms=end_ms - start_ms,
                        text=text,
                        confidence=0.85,
                        keywords=_extract_keywords(resolved_text),
                        engine="dashscope_stream_partial",
                        resolved_text=resolved_text,
                        entities=[candidate.to_dict() for candidate in resolution.candidates],
                        asr_sentences=[sentence],
                    )
                    rule_events = stream_rule_risk_engine.evaluate(segment)
                    event_payloads = _enrich_event_payloads(
                        [event.to_dict() for event in rule_events],
                        [segment],
                    )
                    decision = event_payloads[0] if event_payloads else _default_decision_payload(segment)
                    decision["business_type"] = _decision_business_type(decision)
                    partial_state["utterances"].append(
                        {
                            "utterance_id": segment.id,
                            "start_ms": start_ms,
                            "end_ms": end_ms,
                            "text": text,
                            "resolved_text": resolved_text,
                            "dialogue_review_text": build_vhf_dialogue_review(
                                resolved_text,
                                asr_sentences=[sentence],
                                map_speaker_roles=True,
                            ),
                            "confidence": segment.confidence,
                            "event": decision,
                        }
                    )
                partial_state["latest"] = ""
            else:
                partial_state["latest"] = text
            pieces = [*partial_state["finalized"]]
            if partial_state["latest"]:
                pieces.append(partial_state["latest"])
            cumulative_text = "，".join(piece for piece in pieces if piece)
            high_risk_term = next(
                (
                    keyword
                    for keyword in KEYWORD_GROUPS["L1"]["keywords"]  # type: ignore[index]
                    if str(keyword).lower() in cumulative_text.lower()
                ),
                "",
            )
            task_manager.update(
                task.id,
                status="running",
                segments=[],
                events=[],
                meta={
                    "mode": "dashscope_websocket_partial",
                    "partial_text": text,
                    "cumulative_text": cumulative_text,
                    "partial_is_final": is_final,
                    "partial_count": partial_state["count"],
                    "finalized_utterances": list(partial_state["utterances"]),
                    "processed_path": str(processed_path),
                    "ttft_ms": partial_state["ttft_ms"],
                    "early_risk_term": high_risk_term,
                    "row": row,
                },
            )

        result = run_dashscope_streaming_file(
            processed_path,
            adapter=shared_asr,
            on_partial=on_partial,
            playback_speed=max(0.1, min(playback_speed, 4.0)),
        )
        sentence_rows = list(result.sentences or [])
        if not sentence_rows:
            sentence_rows = [
                {
                    "text": result.text,
                    "begin_time": 0,
                    "end_time": int(result.audio_duration_ms or 0),
                }
            ]

        segments: List[AudioSegment] = []
        events: List[Any] = []
        cursor_ms = 0
        for index, sentence in enumerate(sentence_rows):
            text = str(sentence.get("text") or "").strip()
            if not text:
                continue
            start_ms = int(float(sentence.get("begin_time") or sentence.get("start_time") or cursor_ms))
            end_ms = int(float(sentence.get("end_time") or max(start_ms + 1, cursor_ms)))
            if end_ms <= start_ms:
                end_ms = start_ms + 1000
            cursor_ms = end_ms
            resolution = entity_resolver.resolve(text)
            dialogue = postprocess_vhf_dialogue(
                resolution.resolved_text,
                asr_sentences=[sentence],
                entity_candidates=[candidate.to_dict() for candidate in resolution.candidates],
            )
            segment = AudioSegment(
                id=f"seg_{uuid.uuid4().hex[:12]}",
                channel_id=channel_id,
                file_path=str(processed_path),
                clip_path=str(processed_path),
                start_ms=start_ms,
                end_ms=end_ms,
                duration_ms=end_ms - start_ms,
                text=text,
                confidence=result.confidence,
                keywords=_extract_keywords(dialogue.resolved_text),
                engine=result.engine,
                resolved_text=dialogue.resolved_text,
                entities=[candidate.to_dict() for candidate in resolution.candidates],
                asr_sentences=[sentence],
            )
            segments.append(segment)
            events.extend(mic_risk_engine.evaluate(segment))

        event_payloads = _enrich_event_payloads([event.to_dict() for event in events], segments)
        persisted_events = _persist_decisions(
            source_type="stream_replay",
            audio_path=str(processed_path),
            segments=segments,
            events=event_payloads,
        )
        task_manager.update(
            task.id,
            status="completed",
            segments=[segment.to_dict() for segment in segments],
            events=persisted_events,
            meta={
                "mode": "dashscope_websocket_partial",
                "partial_text": result.text,
                "cumulative_text": result.text,
                "partial_is_final": True,
                "partial_count": partial_state["count"],
                "finalized_utterances": list(partial_state["utterances"]),
                "processed_path": str(processed_path),
                "ttft_ms": result.ttft_ms,
                "final_latency_ms": result.final_latency_ms,
                "audio_duration_ms": result.audio_duration_ms,
                "chunk_count": result.chunk_count,
            },
        )

    task_manager.run_async(task.id, runner)
    return {
        "task_id": task.id,
        "status": "queued",
        "channel_id": channel_id,
        "mode": "dashscope_websocket_partial",
    }


def _long_audio_demo_path() -> Optional[Path]:
    configured = os.getenv("VHF_LONG_AUDIO_DEMO_FILE", "").strip()
    candidates = [Path(configured)] if configured else []
    candidates.append(
        Path("test_data_0614")
        / "音频分类_打乱拼接"
        / "shuffled_concat.wav"
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    matches = list(Path("test_data_0614").glob("**/shuffled_concat.wav"))
    return matches[0].resolve() if matches else None


@router.get("/streaming/replay/demo-info")
async def websocket_streaming_demo_info() -> Dict[str, object]:
    path = _long_audio_demo_path()
    return {
        "available": path is not None,
        "filename": path.name if path else "",
        "size_bytes": path.stat().st_size if path else 0,
    }


@router.get("/streaming/replay/demo-audio")
async def websocket_streaming_demo_audio() -> FileResponse:
    path = _long_audio_demo_path()
    if path is None:
        raise HTTPException(status_code=404, detail="服务器演示长音频不存在")
    return FileResponse(path, media_type="audio/wav", filename=path.name)


@router.post("/streaming/replay/demo")
async def start_websocket_streaming_demo(
    channel_id: str = Form("vhf_demo_01"),
    playback_speed: float = Form(1.0),
) -> Dict[str, str]:
    path = _long_audio_demo_path()
    if path is None:
        raise HTTPException(status_code=404, detail="服务器演示长音频不存在")
    with path.open("rb") as source:
        upload = UploadFile(filename=path.name, file=source)
        return await upload_websocket_streaming_replay(
            file=upload,
            channel_id=channel_id,
            playback_speed=playback_speed,
        )


@router.post("/streaming/replay/quality-demo")
async def start_quality_streaming_demo(
    channel_id: str = Form("vhf_demo_01"),
) -> Dict[str, str]:
    path = _long_audio_demo_path()
    if path is None:
        raise HTTPException(status_code=404, detail="服务器演示长音频不存在")
    with path.open("rb") as source:
        upload = UploadFile(filename=path.name, file=source)
        return await upload_stream_simulation(
            file=upload,
            channel_id=channel_id,
            transcript_override=None,
            denoise_mode="off",
            asr_mode="quality",
        )


@router.post("/streaming/refine-event")
def refine_streaming_business_event(
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, object]:
    raw_text = str(payload.get("asr_text") or "").strip()
    if not raw_text:
        raise HTTPException(status_code=400, detail="缺少待精修的ASR文本")
    original_event_text = raw_text
    channel_id = str(payload.get("channel_id") or settings.default_channel_id)
    utterances = payload.get("utterances")
    asr_sentences = []
    if isinstance(utterances, list):
        for item in utterances:
            if not isinstance(item, dict) or not str(item.get("text") or "").strip():
                continue
            asr_sentences.append(
                {
                    "text": str(item.get("text") or "").strip(),
                    "speaker_id": item.get("speaker_id"),
                    "begin_time": item.get("start_ms"),
                    "end_time": item.get("end_ms"),
                }
            )

    refinement_engine = "text_only"
    task_id = str(payload.get("task_id") or "").strip()
    start_ms = int(payload.get("start_ms") or 0)
    end_ms = int(payload.get("end_ms") or 0)
    task = task_manager.get(task_id) if task_id else None
    processed_path = Path(str((task.meta if task else {}).get("processed_path") or ""))
    if processed_path.is_file() and end_ms > start_ms:
        clip_path = storage.allocate_clip_path(".wav")
        _ensure_browser_wav(
            processed_path,
            clip_path,
            start_ms=start_ms,
            end_ms=end_ms,
        )
        base_result = ASRResult(
            text=raw_text,
            confidence=float(payload.get("confidence") or 0.85),
            engine="dashscope_stream_event",
            sentences=asr_sentences,
        )
        refined_asr = shared_asr_refiner.refine(
            clip_path,
            base_result,
            duration_ms=end_ms - start_ms,
        )
        if refined_asr.text.strip():
            raw_text = refined_asr.text.strip()
            refinement_engine = refined_asr.engine

    resolution = entity_resolver.resolve(raw_text)
    candidates = [candidate.to_dict() for candidate in resolution.candidates]
    dialogue = postprocess_vhf_dialogue(
        resolution.resolved_text,
        asr_sentences=asr_sentences or None,
        original_text=original_event_text,
        sentence_resolver=lambda text: entity_resolver.resolve(text).resolved_text,
        map_speaker_roles=True,
        entity_candidates=candidates,
    )
    segment = AudioSegment(
        id=f"refined_{uuid.uuid4().hex[:12]}",
        channel_id=channel_id,
        file_path=str(payload.get("audio_path") or ""),
        clip_path=None,
        start_ms=start_ms,
        end_ms=end_ms,
        duration_ms=max(0, end_ms - start_ms),
        text=raw_text,
        confidence=float(payload.get("confidence") or 0.85),
        keywords=_extract_keywords(dialogue.resolved_text),
        engine="stream_event_refinement",
        resolved_text=dialogue.resolved_text,
        entities=candidates,
        asr_sentences=asr_sentences,
    )
    evaluated = mic_risk_engine.evaluate(segment)
    event_payloads = _enrich_event_payloads(
        [event.to_dict() for event in evaluated],
        [segment],
    )
    decision = event_payloads[0] if event_payloads else _default_decision_payload(segment)
    decision["business_type"] = _decision_business_type(decision)
    return {
        "resolved_text": dialogue.resolved_text,
        "dialogue_review_text": dialogue.dialogue_review_text,
        "event": decision,
        "refinement": {
            "asr_engine": refinement_engine,
            "dialogue_mode": os.getenv("VHF_DIALOGUE_MODE", "rules"),
            "decision_mode": os.getenv("VHF_DECISION_MODE", "rules"),
        },
    }


def _extract_keywords(text: str) -> List[str]:
    return extract_maritime_keywords(text)


def _is_informative_text(text: str) -> bool:
    cleaned = re.sub(r"[\s，。！？,.!?；;：:、…]+", "", text or "")
    if not cleaned:
        return False
    if cleaned in {"嗯", "啊", "呃", "哦", "是", "好", "好的"}:
        return False
    return bool(re.search(r"[\u4e00-\u9fffA-Za-z0-9]", cleaned))


def _recognize_mic_utterance(
    *,
    session_id: str,
    channel_id: str,
    seq: int,
    pcm_bytes: bytes,
    sample_rate: int,
    is_final: bool,
) -> Dict[str, object]:
    duration_ms = round(len(pcm_bytes) / 2 / sample_rate * 1000)
    suffix = "final" if is_final else "partial"
    wav_path = settings.normalized_dir / f"{session_id}_{seq}_{suffix}.wav"
    write_pcm_wav(wav_path, pcm_bytes, sample_rate)
    result = shared_mic_asr.transcribe(file_path=wav_path)
    result = shared_asr_refiner.refine(wav_path, result, duration_ms=duration_ms)
    text = result.text.strip()
    if not _is_informative_text(text):
        return {
            "session_id": session_id,
            "seq": seq,
            "status": "skipped",
            "reason": "uninformative_text",
            "text": text,
        }

    resolution = entity_resolver.resolve(text)
    dialogue_result = postprocess_vhf_dialogue(
        resolution.resolved_text,
        asr_sentences=result.sentences if result.sentences else None,
        sentence_resolver=(
            lambda sentence: entity_resolver.resolve(sentence).resolved_text
            if result.sentences
            else None
        ),
        map_speaker_roles=bool(result.sentences),
        entity_candidates=[candidate.to_dict() for candidate in resolution.candidates],
    )
    text_for_rules = dialogue_result.resolved_text
    with mic_lock:
        session = mic_sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="mic session not found")
        finalized_texts = list(session.get("texts", []))
        if is_final:
            finalized_texts.append(text)
            session["texts"] = finalized_texts
            session["chunk_count"] = int(session.get("chunk_count", 0)) + 1
        cumulative_text = "\n".join(finalized_texts + ([] if is_final else [text])).strip()

    decision_payloads: List[Dict[str, object]] = []
    if is_final:
        start_ms = max(0, int(session.get("pcm_total_ms", 0)) - duration_ms)
        segment = AudioSegment(
            id=f"{session_id}_{seq}",
            channel_id=channel_id,
            file_path=str(wav_path),
            clip_path=str(wav_path),
            start_ms=start_ms,
            end_ms=start_ms + duration_ms,
            duration_ms=duration_ms,
            text=text,
            confidence=result.confidence,
            keywords=_extract_keywords(text_for_rules),
            engine=result.engine,
            resolved_text=text_for_rules,
            entities=[candidate.to_dict() for candidate in resolution.candidates],
            asr_sentences=result.sentences,
            asr_emotion_tags=list(result.emotion_tags or []),
            asr_event_tags=list(result.event_tags or []),
        )
        events = mic_risk_engine.evaluate(segment)
        event_payloads = _enrich_event_payloads([event.to_dict() for event in events], [segment])
        decision_payloads = _persist_decisions(
            source_type="mic_stream",
            audio_path=str(wav_path),
            segments=[segment],
            events=event_payloads,
        )
        with mic_lock:
            session = mic_sessions.get(session_id)
            if session is not None and decision_payloads:
                session_events = session.get("events", [])
                session_events.extend(decision_payloads)
                session["events"] = session_events

    return {
        "session_id": session_id,
        "seq": seq,
        "status": "final" if is_final else "partial",
        "text": text,
        "resolved_text": text_for_rules,
        "cumulative_text": cumulative_text,
        "dialogue_review_text": dialogue_result.dialogue_review_text,
        "confidence": result.confidence,
        "engine": result.engine,
        "duration_ms": duration_ms,
        "events": decision_payloads,
    }


def _as_segment_payload(item: Any, index: int) -> Dict[str, object]:
    if hasattr(item, "to_dict"):
        return item.to_dict()
    return {
        "index": index,
        "text": getattr(item, "text", ""),
        "confidence": getattr(item, "confidence", 0.0),
        "engine": getattr(item, "engine", ""),
    }


@router.post("/mic/start")
async def start_mic_stream(
    channel_id: str = Form("vhf_demo_01"),
    denoise_mode: str = Form("off"),
) -> Dict[str, object]:
    session_id = f"mic_{uuid.uuid4().hex[:12]}"
    with mic_lock:
        mic_sessions[session_id] = {
            "channel_id": channel_id,
            "denoise_mode": denoise_mode.strip().lower(),
            "texts": [],
            "chunk_count": 0,
            "events": [],
            "pcm_buffer": bytearray(),
            "pcm_has_speech": False,
            "pcm_silence_ms": 0,
            "pcm_total_ms": 0,
            "pcm_last_preview_ms": 0,
            "pcm_idle_ms": 0,
            "pcm_had_final": False,
        }
    ws_manager.publish(
        channel_id,
        {
            "type": "stream_status",
            "stage": "mic_started",
            "channel_id": channel_id,
            "session_id": session_id,
        },
    )
    return {"session_id": session_id, "channel_id": channel_id, "status": "running"}


@router.post("/mic/pcm")
def push_mic_pcm(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    channel_id: str = Form("vhf_demo_01"),
    seq: int = Form(0),
    sample_rate: int = Form(16000),
    preview_window_ms: int = Form(3000),
    vad_silence_ms: int = Form(900),
    vad_rms_threshold: float = Form(350.0),
) -> Dict[str, object]:
    pcm_bytes = file.file.read()
    if len(pcm_bytes) < 320:
        return {"session_id": session_id, "seq": seq, "status": "skipped", "reason": "pcm_frame_too_small"}
    sample_rate = max(8000, min(48000, int(sample_rate)))
    frame_ms = max(1, round(len(pcm_bytes) / 2 / sample_rate * 1000))
    rms = pcm_rms(pcm_bytes)
    is_speech = rms >= max(1.0, vad_rms_threshold)

    with mic_lock:
        session = mic_sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="mic session not found")
        session["pcm_total_ms"] = int(session.get("pcm_total_ms", 0)) + frame_ms
        buffer = session.setdefault("pcm_buffer", bytearray())
        has_speech = bool(session.get("pcm_has_speech", False))
        if is_speech:
            buffer.extend(pcm_bytes)
            session["pcm_has_speech"] = True
            session["pcm_silence_ms"] = 0
            session["pcm_idle_ms"] = 0
            has_speech = True
        elif has_speech:
            buffer.extend(pcm_bytes)
            session["pcm_silence_ms"] = int(session.get("pcm_silence_ms", 0)) + frame_ms
        elif bool(session.get("pcm_had_final", False)):
            session["pcm_idle_ms"] = int(session.get("pcm_idle_ms", 0)) + frame_ms
            if int(session["pcm_idle_ms"]) >= 5000:
                session["pcm_idle_ms"] = 0
                session["pcm_had_final"] = False
                return {
                    "session_id": session_id,
                    "seq": seq,
                    "status": "event_end",
                    "reason": "acoustic_silence_5s",
                }

        utterance_ms = round(len(buffer) / 2 / sample_rate * 1000)
        silence_ms = int(session.get("pcm_silence_ms", 0))
        last_preview_ms = int(session.get("pcm_last_preview_ms", 0))
        is_final = has_speech and silence_ms >= max(400, vad_silence_ms)
        preview_due = (
            has_speech
            and not is_final
            and utterance_ms >= max(1500, preview_window_ms)
            and utterance_ms - last_preview_ms >= max(1500, preview_window_ms)
        )
        if not is_final and not preview_due:
            return {
                "session_id": session_id,
                "seq": seq,
                "status": "buffering",
                "speech_detected": has_speech,
                "rms": round(rms, 1),
                "utterance_ms": utterance_ms,
                "silence_ms": silence_ms,
            }
        utterance_bytes = bytes(buffer)
        if is_final:
            session["pcm_buffer"] = bytearray()
            session["pcm_has_speech"] = False
            session["pcm_silence_ms"] = 0
            session["pcm_last_preview_ms"] = 0
            session["pcm_had_final"] = True
            session["pcm_idle_ms"] = 0
        else:
            session["pcm_last_preview_ms"] = utterance_ms

    return _recognize_mic_utterance(
        session_id=session_id,
        channel_id=channel_id,
        seq=seq,
        pcm_bytes=utterance_bytes,
        sample_rate=sample_rate,
        is_final=is_final,
    )


@router.post("/mic/chunk")
def push_mic_chunk(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    channel_id: str = Form("vhf_demo_01"),
    seq: int = Form(0),
    cumulative: bool = Form(False),
) -> Dict[str, object]:
    with mic_lock:
        session = mic_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="mic session not found")

    save_name = file.filename or f"{session_id}_{seq}.webm"
    saved_path = storage.save_upload(file.file, save_name)
    file_size = saved_path.stat().st_size if saved_path.exists() else 0
    if file_size < 2048:
        with mic_lock:
            session = mic_sessions.get(session_id)
            if session is not None:
                session["skipped_count"] = int(session.get("skipped_count", 0)) + 1
        return {
            "session_id": session_id,
            "seq": seq,
            "status": "skipped",
            "reason": "audio chunk too small",
            "size": file_size,
        }
    denoise_enabled = str(session.get("denoise_mode", "off")) == "on"
    if settings.mic_asr_provider == "qwen_api":
        # Qwen API accepts compressed audio directly; skip ffmpeg to reduce latency and avoid chunk decode failures.
        processed_path = saved_path
    else:
        prepared = preprocessor.prepare(
            file_path=saved_path,
            enable_denoise=denoise_enabled,
        )
        processed_path = Path(prepared.processed_path) if prepared.processed_path else saved_path
    try:
        result = shared_mic_asr.transcribe(file_path=processed_path)
        result = shared_asr_refiner.refine(
            processed_path,
            result,
            duration_ms=1200,
        )
    except RuntimeError as exc:
        message = str(exc)
        if "audio is empty" in message or "InvalidParameter" in message:
            with mic_lock:
                session = mic_sessions.get(session_id)
                if session is not None:
                    session["skipped_count"] = int(session.get("skipped_count", 0)) + 1
            ws_manager.publish(
                channel_id,
                {
                    "type": "stream_status",
                    "stage": "mic_chunk_skipped",
                    "mode": "mic_live_demo",
                    "channel_id": channel_id,
                    "index": seq,
                    "reason": "empty_audio",
                },
            )
            return {
                "session_id": session_id,
                "seq": seq,
                "status": "skipped",
                "reason": "empty_audio",
            }
        raise
    text = result.text
    if not _is_informative_text(text):
        with mic_lock:
            session = mic_sessions.get(session_id)
            if session is not None:
                session["skipped_count"] = int(session.get("skipped_count", 0)) + 1
        ws_manager.publish(
            channel_id,
            {
                "type": "stream_status",
                "stage": "mic_chunk_skipped",
                "mode": "mic_live_demo",
                "channel_id": channel_id,
                "index": seq,
                "reason": "uninformative_text",
                "text": text,
            },
        )
        return {
            "session_id": session_id,
            "seq": seq,
            "status": "skipped",
            "reason": "uninformative_text",
            "text": text,
        }
    resolution = entity_resolver.resolve(text)
    dialogue_result = postprocess_vhf_dialogue(
        resolution.resolved_text,
        asr_sentences=result.sentences if result.sentences else None,
        sentence_resolver=(
            lambda sentence: entity_resolver.resolve(sentence).resolved_text
            if result.sentences
            else None
        ),
        map_speaker_roles=bool(result.sentences),
        entity_candidates=[candidate.to_dict() for candidate in resolution.candidates],
    )
    text_for_rules = dialogue_result.resolved_text

    with mic_lock:
        session = mic_sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="mic session not found")
        if cumulative:
            session["texts"] = [text]
        elif text:
            session["texts"].append(text)
        session["chunk_count"] = int(session.get("chunk_count", 0)) + 1
        cumulative_text = "\n".join(session["texts"]).strip()

    segment = AudioSegment(
        id=f"{session_id}_{seq}",
        channel_id=channel_id,
        file_path=str(processed_path),
        clip_path=str(processed_path),
        start_ms=max(0, seq * 1200),
        end_ms=max(0, seq * 1200 + 1200),
        duration_ms=1200,
        text=text,
        confidence=result.confidence,
        keywords=_extract_keywords(text_for_rules),
        engine=result.engine,
        resolved_text=text_for_rules,
        entities=[candidate.to_dict() for candidate in resolution.candidates],
        asr_sentences=result.sentences,
        asr_emotion_tags=list(result.emotion_tags or []),
        asr_event_tags=list(result.event_tags or []),
    )
    ws_manager.publish(
        channel_id,
        {
            "type": "stream_chunk_result",
            "mode": "mic_live_demo",
            "channel_id": channel_id,
            "index": seq,
            "text": text,
            "resolved_text": text_for_rules,
            "dialogue_review_text": dialogue_result.dialogue_review_text,
            "entities": [candidate.to_dict() for candidate in resolution.candidates],
            "cumulative_text": cumulative_text,
            "confidence": result.confidence,
            "engine": result.engine,
        },
    )

    events = mic_risk_engine.evaluate(segment)
    event_payloads = _enrich_event_payloads([event.to_dict() for event in events], [segment])
    decision_payloads = _persist_decisions(
        source_type="mic_stream",
        audio_path=str(processed_path),
        segments=[segment],
        events=event_payloads,
    )
    for index, event in enumerate(events):
        payload = event_payloads[index] if index < len(event_payloads) else event.to_dict()
        ws_manager.publish(
            channel_id,
            {
                "type": "risk_event",
                "mode": "mic_live_demo",
                "channel_id": channel_id,
                "event": payload,
            },
        )
    with mic_lock:
        session = mic_sessions.get(session_id)
        if session is not None and decision_payloads:
            session_events = session.get("events", [])
            session_events.extend(decision_payloads)
            session["events"] = session_events

    return {
        "session_id": session_id,
        "seq": seq,
        "text": text,
        "resolved_text": text_for_rules,
        "cumulative_text": cumulative_text,
        "dialogue_review_text": dialogue_result.dialogue_review_text,
        "events": decision_payloads,
    }


@router.post("/mic/stop")
def stop_mic_stream(
    session_id: str = Form(...),
) -> Dict[str, object]:
    with mic_lock:
        session = mic_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="mic session not found")
    channel_id = str(session.get("channel_id", "vhf_demo_01"))
    pending_pcm = bytes(session.get("pcm_buffer", b""))
    if bool(session.get("pcm_has_speech")) and len(pending_pcm) >= 16000:
        try:
            _recognize_mic_utterance(
                session_id=session_id,
                channel_id=channel_id,
                seq=int(session.get("chunk_count", 0)) + 1,
                pcm_bytes=pending_pcm,
                sample_rate=16000,
                is_final=True,
            )
        except Exception as exc:
            session["stop_finalize_error"] = str(exc)
    with mic_lock:
        session = mic_sessions.pop(session_id, session)
    summary_text = "\n".join(session.get("texts", [])).strip()
    events = session.get("events", [])
    ws_manager.publish(
        channel_id,
        {
            "type": "stream_status",
            "stage": "completed",
            "mode": "mic_live_demo",
            "channel_id": channel_id,
            "session_id": session_id,
            "chunk_count": int(session.get("chunk_count", 0)),
            "skipped_count": int(session.get("skipped_count", 0)),
            "events": len(events),
        },
    )
    return {
        "session_id": session_id,
        "channel_id": channel_id,
        "status": "completed",
        "chunk_count": int(session.get("chunk_count", 0)),
        "skipped_count": int(session.get("skipped_count", 0)),
        "text": summary_text,
        "events": events,
        "finalize_error": session.get("stop_finalize_error", ""),
    }


@router.get("/tasks/{task_id}")
async def get_task(task_id: str) -> Dict[str, object]:
    task = task_manager.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return task.to_dict()


@router.post("/events")
async def create_event(payload: Dict[str, Any] = Body(...)) -> Dict[str, object]:
    event = dict(payload)
    event_id = str(event.get("event_id") or event.get("id") or f"evt_{uuid.uuid4().hex[:12]}")
    event["event_id"] = event_id
    event["id"] = event_id
    event.setdefault("source_type", "stream_replay")
    event.setdefault("risk_level", "INFO")
    event.setdefault("business_type", _decision_business_type(event))
    event.setdefault("action_type", "manual_review")
    event.setdefault("review_status", "archived")
    event = _attach_high_risk_inspection(event)
    event_store.append(event)
    return event_store.get(event_id) or event


@router.get("/events")
async def list_events() -> Dict[str, List[Dict[str, object]]]:
    return {"items": event_store.list()}


@router.get("/analytics/summary")
async def analytics_summary() -> Dict[str, object]:
    events = event_store.list()
    ships = inspection_simulator.list_mock_ships()
    by_risk: Dict[str, int] = {}
    by_business: Dict[str, int] = {}
    by_type: Dict[str, int] = {}
    by_area: Dict[str, int] = {}
    auto_count = 0
    manual_count = 0
    corrected_count = 0
    closed_count = 0
    for event in events:
        risk = str(event.get("risk_level") or "unknown")
        by_risk[risk] = by_risk.get(risk, 0) + 1
        if event.get("is_auto_reply") or event.get("action_type") == "auto_reply":
            auto_count += 1
        if event.get("requires_human_review", True):
            manual_count += 1
        if event.get("review_status") in {"confirmed", "broadcasted", "archived"}:
            closed_count += 1
        if event.get("asr_text") and event.get("resolved_text") and event.get("asr_text") != event.get("resolved_text"):
            corrected_count += 1
        ais = event.get("ais_context") if isinstance(event.get("ais_context"), dict) else {}
        ship_type = str(ais.get("ship_type") or "未关联")
        area = str(ais.get("position_label") or "未关联")
        by_type[ship_type] = by_type.get(ship_type, 0) + 1
        by_area[area] = by_area.get(area, 0) + 1
        business_type = str(event.get("business_type") or "other_business")
        by_business[business_type] = by_business.get(business_type, 0) + 1
    total = len(events)
    return {
        "event_count": total,
        "ais_ship_count": len(ships),
        "auto_count": auto_count,
        "manual_count": manual_count,
        "closed_count": closed_count,
        "auto_rate": round(auto_count / total, 4) if total else 0.0,
        "manual_rate": round(manual_count / total, 4) if total else 0.0,
        "closure_rate": round(closed_count / total, 4) if total else 0.0,
        "asr_correction_count": corrected_count,
        "by_risk_level": by_risk,
        "by_business_type": by_business,
        "by_ship_type": by_type,
        "by_area": by_area,
        "recent_events": events[:12],
        "ais_samples": ships[:8],
    }


@router.get("/events/{event_id}")
async def get_event(event_id: str) -> Dict[str, object]:
    event = event_store.get(event_id)
    if event:
        return event
    raise HTTPException(status_code=404, detail="event not found")


@router.get("/feedback")
async def list_feedback(limit: int = 200) -> Dict[str, List[Dict[str, object]]]:
    return {"items": event_store.list_feedback(limit=max(1, min(limit, 2000)))}


@router.get("/feedback.csv")
async def export_feedback_csv(limit: int = 2000) -> Response:
    rows = event_store.list_feedback(limit=max(1, min(limit, 10000)))
    fieldnames = [
        "feedback_id",
        "event_id",
        "created_at",
        "source_type",
        "original_asr_text",
        "previous_resolved_text",
        "corrected_asr_text",
        "corrected_intent",
        "corrected_ship_name",
        "corrected_ais_ship_id",
        "corrected_broadcast_text",
        "corrected_dialogue_text",
        "reviewer_notes",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in fieldnames})
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="vhf_review_feedback.csv"'},
    )


@router.post("/events/{event_id}/feedback")
async def save_event_feedback(
    event_id: str,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, object]:
    event = event_store.get(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="event not found")

    corrected_asr_text = str(payload.get("corrected_asr_text") or event.get("resolved_text") or event.get("asr_text") or "").strip()
    corrected_intent = str(payload.get("corrected_intent") or event.get("business_type") or "other_business").strip()
    corrected_ship_name = str(payload.get("corrected_ship_name") or "").strip()
    corrected_ais_ship_id = str(payload.get("corrected_ais_ship_id") or "").strip()
    corrected_broadcast_text = str(payload.get("corrected_broadcast_text") or event.get("broadcast_text") or "").strip()
    corrected_dialogue_text = str(payload.get("corrected_dialogue_text") or "").strip()

    ais_context: Dict[str, object] = {}
    if corrected_ais_ship_id:
        ais_context = next(
            (
                ship
                for ship in inspection_simulator.list_mock_ships()
                if str(ship.get("ship_id") or "") == corrected_ais_ship_id
            ),
            {},
        )
    if not ais_context and isinstance(event.get("ais_context"), dict):
        ais_context = dict(event["ais_context"])

    feedback = event_store.save_feedback(
        event_id,
        {
            "source_type": event.get("source_type", "unknown"),
            "original_asr_text": event.get("asr_text", ""),
            "previous_resolved_text": event.get("resolved_text", ""),
            "corrected_asr_text": corrected_asr_text,
            "corrected_intent": corrected_intent,
            "corrected_ship_name": corrected_ship_name,
            "corrected_ais_ship_id": corrected_ais_ship_id,
            "corrected_broadcast_text": corrected_broadcast_text,
            "corrected_dialogue_text": corrected_dialogue_text,
            "reviewer_notes": str(payload.get("reviewer_notes") or "").strip(),
        },
    )

    event["resolved_text"] = corrected_asr_text
    event["business_type"] = corrected_intent
    event["corrected_ship_name"] = corrected_ship_name
    event["ais_context"] = ais_context
    event["broadcast_text"] = corrected_broadcast_text
    event["dialogue_review_text"] = corrected_dialogue_text or _build_dialogue_review_template(corrected_asr_text)
    event["review_status"] = "confirmed"
    event_store.append(event)
    return {"event": event, "feedback": feedback}


@router.delete("/events/{event_id}")
async def delete_event(event_id: str) -> Dict[str, object]:
    if not event_store.delete(event_id):
        raise HTTPException(status_code=404, detail="event not found")
    return {"ok": True, "event_id": event_id}


@router.patch("/events/{event_id}/review-status")
async def update_event_review_status(
    event_id: str,
    payload: Dict[str, str] = Body(...),
) -> Dict[str, object]:
    review_status = str(payload.get("review_status") or "").strip()
    if review_status not in {"pending", "confirmed", "broadcasted", "archived"}:
        raise HTTPException(status_code=400, detail="review_status 非法。")
    event = event_store.update_review_status(event_id, review_status)
    if not event:
        raise HTTPException(status_code=404, detail="event not found")
    return event


@router.websocket("/ws/monitor/{channel_id}")
async def monitor_channel(websocket: WebSocket, channel_id: str) -> None:
    await ws_manager.connect(channel_id, websocket)
    ws_manager.publish(
        channel_id,
        {
            "type": "stream_status",
            "stage": "connected",
            "channel_id": channel_id,
        },
    )
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(channel_id, websocket)
