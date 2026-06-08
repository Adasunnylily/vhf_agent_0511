from __future__ import annotations

import threading
import uuid
import re
import csv
import io
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, File, Form, HTTPException, Response, UploadFile, WebSocket, WebSocketDisconnect

from app.domain.models import AudioSegment
from app.config import settings
from app.main import (
    event_store,
    entity_resolver,
    inspection_simulator,
    knowledge_repository,
    pipeline,
    preprocessor,
    realtime_stream_processor,
    scenario_simulator,
    shared_asr,
    storage,
    stream_processor,
    task_manager,
    ws_manager,
)
from app.services.asr_compare import list_asr_compare_options
from app.services.demo_inspection import InspectionShip
from app.services.risk_engine import KeywordRiskEngine

router = APIRouter(prefix="/api")
mic_risk_engine = KeywordRiskEngine()
mic_sessions: Dict[str, Dict[str, Any]] = {}
mic_lock = threading.Lock()


@router.get("/config/public")
async def public_config() -> Dict[str, object]:
    return {
        "default_channel_id": settings.default_channel_id,
        "amap_key": settings.amap_key,
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
            payload["ais_context"] = _best_ais_context_from_entities(segment.entities)
        enriched.append(payload)
    return enriched


def _decision_business_type(payload: Dict[str, Any]) -> str:
    risk_level = str(payload.get("risk_level") or "")
    action_type = str(payload.get("action_type") or "")
    if risk_level in {"L1", "L2", "L3"}:
        return "emergency_risk"
    if action_type == "auto_reply":
        return "routine_report"
    if action_type in {"manual_business", "manual_review"}:
        return "other_business"
    return "other_business"


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
            event_id = f"evt_{uuid.uuid4().hex[:12]}"
            payload = {
                "event_id": event_id,
                "id": event_id,
                "segment_id": segment.id,
                "channel_id": segment.channel_id,
                "event_type": "一般业务通话",
                "risk_level": "INFO",
                "summary": "未命中自动回复或高危规则，已归档供值班员复核。",
                "evidence": [],
                "suggestion": "建议值班员结合上下文确认是否需要进一步处置。",
                "broadcast_text": "",
                "action_type": "manual_review",
                "requires_human_review": True,
                "is_auto_reply": False,
                "review_status": "pending",
            }
        payload["source_type"] = source_type
        payload["audio_path"] = audio_path
        payload["asr_text"] = segment.text
        payload["resolved_text"] = segment.resolved_text or segment.text
        payload["entities"] = segment.entities
        payload["ais_context"] = _best_ais_context_from_entities(segment.entities) or {}
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
            payload["business_type"] = _decision_business_type(payload)
            decisions.append(payload)
    event_store.extend(decisions)
    return decisions


def _build_dialogue_review_template(text: str) -> str:
    parts = [
        item.strip(" ，。！？；;")
        for item in re.split(r"[。！？；;\n]+", text or "")
        if item.strip(" ，。！？；;")
    ]
    return "\n".join(f"待确认说话人：{item}。" for item in parts)


@router.get("/demo/scenarios")
async def list_demo_scenarios() -> Dict[str, List[Dict[str, object]]]:
    return {"items": scenario_simulator.list_scenarios()}


@router.get("/demo/inspection/ships")
async def list_demo_inspection_ships() -> Dict[str, List[Dict[str, object]]]:
    return {"items": inspection_simulator.list_mock_ships()}


@router.get("/inspection/ships")
async def list_inspection_ships() -> Dict[str, List[Dict[str, object]]]:
    return {"items": inspection_simulator.list_mock_ships()}


@router.get("/ais/ships")
async def list_ais_ships() -> Dict[str, List[Dict[str, object]]]:
    return {"items": inspection_simulator.list_mock_ships()}


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
) -> Dict[str, str]:
    task = task_manager.create(filename=file.filename or "unknown", channel_id=channel_id)
    saved_path = storage.save_upload(file.file, file.filename or "upload.bin")

    def runner() -> None:
        segments, events = stream_processor.process_file_stream(
            file_path=saved_path,
            channel_id=channel_id,
            transcript_override=transcript_override,
            enable_denoise=denoise_mode.strip().lower() == "on",
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
            meta={"denoise_mode": denoise_mode.strip().lower()},
        )

    task_manager.run_async(task.id, runner)
    return {
        "task_id": task.id,
        "status": "queued",
        "channel_id": channel_id,
        "denoise_mode": denoise_mode,
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
        if settings.asr_provider == "qwen_api":
            # Qwen ASR is an API-style file recognizer. For the demo "quasi realtime" path,
            # replay VAD chunks through the same API chain instead of downloading local
            # paraformer streaming weights at request time.
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
        "mode": "qwen_api_chunk_replay" if settings.asr_provider == "qwen_api" else "paraformer_streaming",
    }


def _extract_keywords(text: str) -> List[str]:
    lowered = text.lower()
    known_keywords = [
        "mayday",
        "求救",
        "进水",
        "起火",
        "失火",
        "人员落水",
        "碰撞",
        "搁浅",
        "失控",
        "失去动力",
        "让清航道",
        "避让",
        "未响应",
        "占频",
        "逆行",
        "禁止通行",
        "闯入",
        "超速",
        "未报告",
    ]
    return [keyword for keyword in known_keywords if keyword.lower() in lowered]


def _is_informative_text(text: str) -> bool:
    cleaned = re.sub(r"[\s，。！？,.!?；;：:、…]+", "", text or "")
    if not cleaned:
        return False
    if cleaned in {"嗯", "啊", "呃", "哦", "是", "好", "好的"}:
        return False
    return bool(re.search(r"[\u4e00-\u9fffA-Za-z0-9]", cleaned))


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


@router.post("/mic/chunk")
async def push_mic_chunk(
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
    if settings.asr_provider == "qwen_api":
        # Qwen API accepts compressed audio directly; skip ffmpeg to reduce latency and avoid chunk decode failures.
        processed_path = saved_path
    else:
        prepared = preprocessor.prepare(
            file_path=saved_path,
            enable_denoise=denoise_enabled,
        )
        processed_path = Path(prepared.processed_path) if prepared.processed_path else saved_path
    try:
        result = shared_asr.transcribe(file_path=processed_path)
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
    text_for_rules = resolution.resolved_text

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
        "cumulative_text": cumulative_text,
        "events": decision_payloads,
    }


@router.post("/mic/stop")
async def stop_mic_stream(
    session_id: str = Form(...),
) -> Dict[str, object]:
    with mic_lock:
        session = mic_sessions.pop(session_id, None)
    if not session:
        raise HTTPException(status_code=404, detail="mic session not found")
    channel_id = str(session.get("channel_id", "vhf_demo_01"))
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
    }


@router.get("/tasks/{task_id}")
async def get_task(task_id: str) -> Dict[str, object]:
    task = task_manager.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return task.to_dict()


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
