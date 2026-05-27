from __future__ import annotations

import threading
import uuid
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect

from app.domain.models import AudioSegment
from app.config import settings
from app.main import (
    event_store,
    entity_resolver,
    inspection_simulator,
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


@router.get("/demo/scenarios")
async def list_demo_scenarios() -> Dict[str, List[Dict[str, object]]]:
    return {"items": scenario_simulator.list_scenarios()}


@router.get("/demo/inspection/ships")
async def list_demo_inspection_ships() -> Dict[str, List[Dict[str, object]]]:
    return {"items": inspection_simulator.list_mock_ships()}


@router.get("/inspection/ships")
async def list_inspection_ships() -> Dict[str, List[Dict[str, object]]]:
    return {"items": inspection_simulator.list_mock_ships()}


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
    )
    item = inspection_simulator.add_ship(ship=ship)
    return {"item": item}


@router.post("/inspection/ships/delete")
async def delete_inspection_ship(
    ship_id: str = Form(...),
) -> Dict[str, object]:
    removed = inspection_simulator.remove_ship(ship_id=ship_id)
    if not removed:
        raise HTTPException(status_code=404, detail="未找到该船舶。")
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


@router.post("/inspection/filter")
async def filter_inspection_ships(
    area_name: str = Form("北仑主航道A3段"),
    min_draft_m: float = Form(10.0),
    min_tonnage_t: int = Form(5000),
    area_geometry: str = Form(""),
    ship_types: str = Form(""),
) -> Dict[str, object]:
    allowed_ship_types = [item.strip() for item in ship_types.split(",") if item.strip()]
    matched = inspection_simulator.filter_ships(
        area_name=area_name,
        min_draft_m=min_draft_m,
        min_tonnage_t=min_tonnage_t,
        area_geometry=area_geometry,
        allowed_ship_types=allowed_ship_types,
    )
    return {
        "area_name": area_name,
        "min_draft_m": min_draft_m,
        "min_tonnage_t": min_tonnage_t,
        "ship_types": allowed_ship_types,
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
) -> Dict[str, object]:
    allowed_ship_types = [item.strip() for item in ship_types.split(",") if item.strip()]
    matched = inspection_simulator.filter_ships(
        area_name=area_name,
        min_draft_m=min_draft_m,
        min_tonnage_t=min_tonnage_t,
        area_geometry=area_geometry,
        allowed_ship_types=allowed_ship_types,
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
        task_manager.update(
            task.id,
            status="completed",
            segments=[segment.to_dict() for segment in segments],
            events=[event.to_dict() for event in events],
            meta=meta,
        )
        event_store.extend([event.to_dict() for event in events])

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
) -> Dict[str, str]:
    task = task_manager.create(filename=f"inspection:{area_name}", channel_id=channel_id)
    allowed_ship_types = [item.strip() for item in ship_types.split(",") if item.strip()]

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
            combined_events = [
                *[event.to_dict() for event in base_run.events],
                *[event.to_dict() for event in denoise_run.events],
            ]
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
                events=combined_events,
                meta={
                    "denoise_mode": "compare",
                    "original_preprocess": base_run.preprocess,
                    "denoised_preprocess": denoise_run.preprocess,
                    "original_texts": [segment.text for segment in base_run.segments],
                    "denoised_texts": [segment.text for segment in denoise_run.segments],
                },
            )
            event_store.extend(combined_events)
            return

        run = pipeline.process(
            file_path=saved_path,
            channel_id=channel_id,
            transcript_override=transcript_override,
            force_full_file_transcribe=False,
            enable_denoise=(mode == "on"),
        )
        task_manager.update(
            task.id,
            status="completed",
            segments=[segment.to_dict() for segment in run.segments],
            events=[event.to_dict() for event in run.events],
            meta={
                "denoise_mode": mode,
                "preprocess": run.preprocess,
            },
        )
        event_store.extend([event.to_dict() for event in run.events])

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
        task_manager.update(
            task.id,
            status="completed",
            segments=[segment.to_dict() for segment in segments],
            events=[event.to_dict() for event in events],
            meta={"denoise_mode": denoise_mode.strip().lower()},
        )
        event_store.extend([event.to_dict() for event in events])

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
        task_manager.update(
            task.id,
            status="completed",
            segments=[_as_segment_payload(item, index) for index, item in enumerate(chunk_results)],
            events=[event.to_dict() for event in events],
            meta={"denoise_mode": denoise_mode.strip().lower(), "mode": mode},
        )
        event_store.extend([event.to_dict() for event in events])

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
        if text:
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
            "cumulative_text": cumulative_text,
            "confidence": result.confidence,
            "engine": result.engine,
        },
    )

    events = mic_risk_engine.evaluate(segment)
    for event in events:
        ws_manager.publish(
            channel_id,
            {
                "type": "risk_event",
                "mode": "mic_live_demo",
                "channel_id": channel_id,
                "event": event.to_dict(),
            },
        )
    with mic_lock:
        session = mic_sessions.get(session_id)
        if session is not None and events:
            session_events = session.get("events", [])
            session_events.extend([event.to_dict() for event in events])
            session["events"] = session_events

    return {
        "session_id": session_id,
        "seq": seq,
        "text": text,
        "cumulative_text": cumulative_text,
        "events": [event.to_dict() for event in events],
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
    return {"items": list(reversed(event_store))}


@router.get("/events/{event_id}")
async def get_event(event_id: str) -> Dict[str, object]:
    for event in event_store:
        if event["id"] == event_id:
            return event
    raise HTTPException(status_code=404, detail="event not found")


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
