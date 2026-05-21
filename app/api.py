from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect

from app.main import (
    event_store,
    inspection_simulator,
    pipeline,
    realtime_stream_processor,
    scenario_simulator,
    storage,
    stream_processor,
    task_manager,
    ws_manager,
)
from app.services.asr_compare import list_asr_compare_options

router = APIRouter(prefix="/api")


@router.get("/demo/scenarios")
async def list_demo_scenarios() -> Dict[str, List[Dict[str, object]]]:
    return {"items": scenario_simulator.list_scenarios()}


@router.get("/demo/inspection/ships")
async def list_demo_inspection_ships() -> Dict[str, List[Dict[str, object]]]:
    return {"items": inspection_simulator.list_mock_ships()}


@router.get("/inspection/ships")
async def list_inspection_ships() -> Dict[str, List[Dict[str, object]]]:
    return {"items": inspection_simulator.list_mock_ships()}


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
    notice_template: str = Form("{船名}，请注意，您已进入{区域}，请按规定守听并回复。"),
    area_geometry: str = Form(""),
    ship_types: str = Form(""),
) -> Dict[str, str]:
    task = task_manager.create(filename=f"inspection:{area_name}", channel_id=channel_id)
    allowed_ship_types = [item.strip() for item in ship_types.split(",") if item.strip()]

    def runner() -> None:
        meta = inspection_simulator.run(
            channel_id=channel_id,
            area_name=area_name,
            min_draft_m=min_draft_m,
            min_tonnage_t=min_tonnage_t,
            notice_template=notice_template,
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
    notice_template: str = Form("{船名}，请注意，您已进入{区域}，请按规定守听并回复。"),
    area_geometry: str = Form(""),
    ship_types: str = Form(""),
) -> Dict[str, str]:
    return await run_demo_inspection_task(
        channel_id=channel_id,
        area_name=area_name,
        min_draft_m=min_draft_m,
        min_tonnage_t=min_tonnage_t,
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
    notice_template: str = Form("{船名}，请注意，您已进入{区域}，请按规定守听并回复。"),
    area_geometry: str = Form(""),
    ship_types: str = Form(""),
) -> Dict[str, str]:
    return await run_demo_inspection_task(
        channel_id=channel_id,
        area_name=area_name,
        min_draft_m=min_draft_m,
        min_tonnage_t=min_tonnage_t,
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
        chunk_results, events = realtime_stream_processor.process_file_stream(
            file_path=saved_path,
            channel_id=channel_id,
            enable_denoise=denoise_mode.strip().lower() == "on",
        )
        task_manager.update(
            task.id,
            status="completed",
            segments=[
                {
                    "index": index,
                    "text": item.text,
                    "confidence": item.confidence,
                    "engine": item.engine,
                }
                for index, item in enumerate(chunk_results)
            ],
            events=[event.to_dict() for event in events],
            meta={"denoise_mode": denoise_mode.strip().lower()},
        )
        event_store.extend([event.to_dict() for event in events])

    task_manager.run_async(task.id, runner)
    return {
        "task_id": task.id,
        "status": "queued",
        "channel_id": channel_id,
        "mode": "paraformer_streaming",
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
