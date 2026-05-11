from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass
from typing import Dict, List, Tuple

from app.domain.models import AudioSegment, RiskEvent
from app.services.risk_engine import KeywordRiskEngine
from app.services.ws_manager import ChannelWebSocketManager


@dataclass(frozen=True)
class ScenarioUtterance:
    speaker: str
    text: str
    duration_ms: int


@dataclass(frozen=True)
class ScenarioDefinition:
    scenario_id: str
    title: str
    summary: str
    utterances: List[ScenarioUtterance]

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


SCENARIOS: Dict[str, ScenarioDefinition] = {
    "static_report": ScenarioDefinition(
        scenario_id="static_report",
        title="由动转静报告自动回复",
        summary="演示靠泊、抛锚、过报告线等高频标准化报告由系统识别并生成规则回复。",
        utterances=[
            ScenarioUtterance("宁远8", "VTS，宁远8报告，已靠泊3号码头，靠港完毕。", 2800),
            ScenarioUtterance("海丰32", "VTS，海丰32报告，已在锚地抛好锚。", 2600),
            ScenarioUtterance("系统", "自动识别为由动转静常规报告，记录信息并生成标准回复。", 1800),
            ScenarioUtterance("VTS自动回复", "宁远8，VTS收到，请保持守听，按计划靠泊或锚泊作业。", 2600),
        ],
    ),
    "manual_business": ScenarioDefinition(
        scenario_id="manual_business",
        title="非自动化业务人工处理",
        summary="演示离泊、出港、航行计划等多因素业务暂不自动回复，系统转人工复核。",
        utterances=[
            ScenarioUtterance("海丰32", "VTS，海丰32申请离泊，请求出港，目的地北槽。", 3200),
            ScenarioUtterance("系统", "识别为非自动化业务，涉及航行计划和通航态势，转值班员人工处理。", 2600),
            ScenarioUtterance("值班员建议回复", "海丰32，VTS收到，请保持守听，等待值班员进一步指令。", 2600),
        ],
    ),
    "smoke_fire": ScenarioDefinition(
        scenario_id="smoke_fire",
        title="冒烟/着火秒级干预",
        summary="演示冒烟、着火、求救等高危内容被秒级抓取，并生成干预播报建议。",
        utterances=[
            ScenarioUtterance("货轮876", "Mayday Mayday，这里是货轮876，机舱冒烟并且已经着火，请求紧急救助。", 4400),
            ScenarioUtterance("系统", "命中冒烟、着火、Mayday高危关键词，触发一级紧急险情。", 2200),
            ScenarioUtterance("值班员建议播报", "相关船舶立即加强瞭望并保持守听，附近应急力量立即做好协助准备。", 3200),
        ],
    ),
}


class ScenarioSimulator:
    def __init__(
        self,
        risk_engine: KeywordRiskEngine,
        ws_manager: ChannelWebSocketManager,
        playback_speed: float = 6.0,
    ) -> None:
        self.risk_engine = risk_engine
        self.ws_manager = ws_manager
        self.playback_speed = playback_speed

    def list_scenarios(self) -> List[Dict[str, object]]:
        return [scenario.to_dict() for scenario in SCENARIOS.values()]

    def run(self, scenario_id: str, channel_id: str) -> Tuple[List[AudioSegment], List[RiskEvent], Dict[str, object]]:
        if scenario_id not in SCENARIOS:
            raise RuntimeError(f"未知场景: {scenario_id}")

        scenario = SCENARIOS[scenario_id]
        self.ws_manager.publish(
            channel_id,
            {
                "type": "scenario_status",
                "stage": "started",
                "channel_id": channel_id,
                "scenario": scenario.to_dict(),
            },
        )

        segments: List[AudioSegment] = []
        events: List[RiskEvent] = []
        current_start_ms = 0

        for index, utterance in enumerate(scenario.utterances):
            segment = AudioSegment(
                id=f"seg_{uuid.uuid4().hex[:12]}",
                channel_id=channel_id,
                file_path=f"scenario://{scenario.scenario_id}",
                clip_path=None,
                start_ms=current_start_ms,
                end_ms=current_start_ms + utterance.duration_ms,
                duration_ms=utterance.duration_ms,
                text=utterance.text,
                confidence=0.99,
                keywords=self._extract_keywords(utterance.text),
                engine="scenario-script",
            )
            segments.append(segment)
            self.ws_manager.publish(
                channel_id,
                {
                    "type": "segment_result",
                    "channel_id": channel_id,
                    "mode": "scenario",
                    "index": index,
                    "speaker": utterance.speaker,
                    "segment": segment.to_dict(),
                },
            )

            segment_events = self.risk_engine.evaluate(segment)
            for event in segment_events:
                events.append(event)
                self.ws_manager.publish(
                    channel_id,
                    {
                        "type": "risk_event",
                        "channel_id": channel_id,
                        "mode": "scenario",
                        "event": event.to_dict(),
                    },
                )
                self.ws_manager.publish(
                    channel_id,
                    {
                        "type": "broadcast_recommendation",
                        "channel_id": channel_id,
                        "mode": "scenario",
                        "event_id": event.id,
                        "broadcast_text": event.broadcast_text,
                        "suggestion": event.suggestion,
                    },
                )

            self._delay(utterance.duration_ms)
            current_start_ms += utterance.duration_ms

        meta = {
            "scenario_id": scenario.scenario_id,
            "scenario_title": scenario.title,
            "scenario_summary": scenario.summary,
            "segment_count": len(segments),
            "event_count": len(events),
        }
        self.ws_manager.publish(
            channel_id,
            {
                "type": "scenario_status",
                "stage": "completed",
                "channel_id": channel_id,
                "meta": meta,
            },
        )
        return segments, events, meta

    def _delay(self, duration_ms: int) -> None:
        if self.playback_speed <= 0:
            return
        time.sleep(min(duration_ms / 1000.0 / self.playback_speed, 1.5))

    def _extract_keywords(self, text: str) -> List[str]:
        lowered = text.lower()
        known_keywords = [
            "mayday",
            "求救",
            "进水",
            "起火",
            "失火",
            "着火",
            "冒烟",
            "救生筏",
            "左倾",
            "人员落水",
            "碰撞",
            "快要碰撞",
            "失去动力",
            "故障",
            "团雾",
            "让清航道",
            "避让",
            "靠港",
            "靠泊",
            "抛锚",
            "报告线",
            "离泊",
            "出港",
        ]
        return [keyword for keyword in known_keywords if keyword.lower() in lowered]
