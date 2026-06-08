from __future__ import annotations

from typing import Dict, List


def _number(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _angle_delta(a: float, b: float) -> float:
    delta = abs((a - b + 180.0) % 360.0 - 180.0)
    return min(delta, 360.0 - delta)


class AISRiskAnalyzer:
    """Add AIS context and simple navigation anomaly signals to decision events."""

    def __init__(
        self,
        high_speed_kn: float = 12.0,
        low_speed_kn: float = 1.0,
        heading_cog_delta_deg: float = 45.0,
    ) -> None:
        self.high_speed_kn = high_speed_kn
        self.low_speed_kn = low_speed_kn
        self.heading_cog_delta_deg = heading_cog_delta_deg

    def analyze(self, text: str, ais_context: Dict[str, object]) -> Dict[str, object]:
        if not ais_context:
            return {"evidence": [], "requires_human_review": False, "risk_level": ""}

        evidence: List[str] = []
        text = text or ""
        speed = _number(ais_context.get("sog_kn"))
        heading = _number(ais_context.get("heading_deg"))
        cog = _number(ais_context.get("cog_deg"))
        position = str(ais_context.get("position_label") or "")
        nav_status = str(ais_context.get("nav_status") or "")

        evidence.append(
            f"AIS关联: {ais_context.get('ship_name') or '未知船舶'} "
            f"MMSI {ais_context.get('mmsi') or '-'} "
            f"航速 {speed:g}kn 航向 {heading:g}° 航迹 {cog:g}°"
        )

        manual = False
        if any(keyword in text for keyword in ["航速", "船速", "加车", "减速", "加点速", "点车", "加点车"]):
            manual = True
            evidence.append("语音涉及航速调整，需结合AIS速度人工复核。")
        if any(keyword in text for keyword in ["航向", "转向", "右转", "左转", "向右", "向左"]):
            manual = True
            evidence.append("语音涉及航向/转向，需结合AIS航迹人工复核。")
        if any(keyword in text for keyword in ["船位", "哪里", "到哪里", "位置"]):
            manual = True
            evidence.append("语音涉及船位或去向，需结合AIS位置人工复核。")

        if speed >= self.high_speed_kn:
            manual = True
            evidence.append(f"AIS航速 {speed:g}kn 高于重点水域关注阈值 {self.high_speed_kn:g}kn。")
        if 0 < speed <= self.low_speed_kn and any(word in nav_status for word in ["航行", "进港", "出港"]):
            manual = True
            evidence.append(f"AIS显示航行状态但航速仅 {speed:g}kn，可能存在停车、拥堵或态势异常。")
        if heading and cog and _angle_delta(heading, cog) >= self.heading_cog_delta_deg:
            manual = True
            evidence.append(
                f"AIS航首向与对地航迹偏差 { _angle_delta(heading, cog):.0f}°，建议核实转向或漂移情况。"
            )
        if any(keyword in position for keyword in ["警戒区", "航道", "桥", "口门", "锚地"]):
            evidence.append(f"AIS位置位于重点水域: {position}。")

        return {
            "evidence": evidence,
            "requires_human_review": manual,
            "risk_level": "MANUAL" if manual else "",
        }

    def enrich_event(self, event: Dict[str, object]) -> Dict[str, object]:
        payload = dict(event)
        ais_context = payload.get("ais_context")
        if not isinstance(ais_context, dict) or not ais_context:
            return payload

        result = self.analyze(str(payload.get("resolved_text") or payload.get("asr_text") or ""), ais_context)
        evidence = list(payload.get("evidence") or [])
        evidence.extend(item for item in result["evidence"] if item not in evidence)
        payload["evidence"] = evidence
        payload["ais_anomaly"] = bool(result["requires_human_review"])
        if result["requires_human_review"] and payload.get("risk_level") in {"INFO", "AUTO", "", None}:
            payload["risk_level"] = "MANUAL"
            payload["event_type"] = "AIS态势需人工复核"
            payload["summary"] = "语音内容已关联AIS目标，存在航速、航向或位置相关人工复核信号。"
            payload["suggestion"] = "建议值班员结合AIS态势核实该船航速、航向和周边船舶关系，必要时点名提醒。"
            payload["broadcast_text"] = payload.get("broadcast_text") or "VTS收到，请保持守听，等待值班员进一步指令。"
            payload["action_type"] = "manual_business"
            payload["requires_human_review"] = True
            payload["is_auto_reply"] = False
        return payload
