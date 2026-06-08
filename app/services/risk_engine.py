from __future__ import annotations

import uuid
from typing import Dict, List, Optional, Tuple

from app.domain.models import AudioSegment, RiskEvent


KEYWORD_GROUPS: Dict[str, Dict[str, object]] = {
    "L1": {
        "event_type": "紧急险情",
        "keywords": [
            "mayday",
            "求救",
            "救命",
            "进水",
            "起火",
            "失火",
            "着火",
            "冒烟",
            "人员落水",
            "救生筏",
            "左倾",
            "倾斜严重",
            "严重倾斜",
            "快沉",
            "沉没",
        ],
        "suggestion": "建议值班员立即人工接管，核实船位、人员和周边态势，并启动最高优先级应急响应流程。",
        "broadcast_text": "相关船舶立即加强瞭望并保持守听，附近应急力量立即做好协助准备。",
        "action_type": "emergency_manual",
        "requires_human_review": True,
        "is_auto_reply": False,
    },
    "L2": {
        "event_type": "高危疑似场景",
        "keywords": ["碰撞", "搁浅", "失控", "失去动力", "故障", "发生问题", "团雾", "浓雾", "让清航道", "快要碰上", "避让"],
        "suggestion": "建议值班员复核语义和通航态势；若上下文确认存在险情，应升级为人工处置事件。",
        "broadcast_text": "请相关船舶注意当前通航风险，保持安全航速，加强瞭望，按规定避让。",
        "action_type": "risk_manual_review",
        "requires_human_review": True,
        "is_auto_reply": False,
    },
    "L3": {
        "event_type": "通信或监管异常",
        "keywords": ["未响应", "占频", "逆行", "禁止通行", "闯入", "超速", "未报告"],
        "suggestion": "建议值班员复核通话内容，并视情况进行点名提醒。",
        "broadcast_text": "请相关船舶遵守通航秩序和无线电通信要求，保持守听并及时报告。",
        "action_type": "manual_review",
        "requires_human_review": True,
        "is_auto_reply": False,
    },
    "AUTO": {
        "event_type": "由动转静常规报告",
        "keywords": ["靠港", "靠泊", "码头", "到泊", "已靠妥", "抛锚", "锚泊", "抛好锚", "过报告线", "报告线", "报告vts", "报告船位"],
        "suggestion": "识别为由动转静的高频标准化报告，可记录信息并按规则生成回复。",
        "broadcast_text": "VTS收到，请保持守听，按计划靠泊或锚泊作业。",
        "action_type": "auto_reply",
        "requires_human_review": False,
        "is_auto_reply": True,
    },
    "MANUAL": {
        "event_type": "非自动化业务",
        "keywords": [
            "离泊",
            "申请离泊",
            "请求离泊",
            "出港",
            "申请出港",
            "请求开航",
            "目的地",
            "航行计划",
            "天气",
            "航速",
            "航向",
            "船位",
            "加车",
            "减速",
            "加点速",
            "挡住",
            "穿越",
            "警戒区",
        ],
        "suggestion": "该类业务涉及航行计划、目的地、天气或态势等多因素判断，暂不进入自动回复，由值班员人工处理。",
        "broadcast_text": "VTS收到，请保持守听，等待值班员进一步指令。",
        "action_type": "manual_business",
        "requires_human_review": True,
        "is_auto_reply": False,
    }
}


class KeywordRiskEngine:
    def evaluate(self, segment: AudioSegment) -> List[RiskEvent]:
        text = (segment.resolved_text or segment.text).strip()
        if not text:
            return []

        lowered = text.lower()
        matched = self._match_group(lowered)
        if not matched:
            return []

        (
            matched_level,
            matched_keywords,
            matched_event_type,
            suggestion,
            broadcast_text,
            action_type,
            requires_human_review,
            is_auto_reply,
        ) = matched
        summary = f"识别到疑似{matched_event_type}，命中关键词：{', '.join(matched_keywords)}。"
        evidence = [f"命中关键词: {keyword}" for keyword in matched_keywords]
        if segment.confidence < 0.8:
            evidence.append(f"识别置信度低于自动化阈值: {segment.confidence:.2f}")
            requires_human_review = True
            is_auto_reply = False
            if action_type == "auto_reply":
                action_type = "auto_reply_recheck"
                suggestion = "识别置信度低于 0.80，建议先由值班员复核，再决定是否发送标准回复。"

        return [
            RiskEvent(
                id=f"evt_{uuid.uuid4().hex[:12]}",
                segment_id=segment.id,
                channel_id=segment.channel_id,
                event_type=matched_event_type,
                risk_level=matched_level,
                summary=summary,
                evidence=evidence,
                suggestion=suggestion,
                broadcast_text=broadcast_text,
                action_type=action_type,
                requires_human_review=requires_human_review,
                is_auto_reply=is_auto_reply,
            )
        ]

    def _match_group(self, lowered: str) -> Optional[Tuple[str, List[str], str, str, str, str, bool, bool]]:
        for risk_level in ("L1", "L2", "L3", "AUTO", "MANUAL"):
            group = KEYWORD_GROUPS[risk_level]
            hits = [
                keyword
                for keyword in group["keywords"]  # type: ignore[index]
                if keyword.lower() in lowered
            ]
            if hits:
                return (
                    risk_level,
                    hits,
                    str(group["event_type"]),
                    str(group["suggestion"]),
                    str(group["broadcast_text"]),
                    str(group["action_type"]),
                    bool(group["requires_human_review"]),
                    bool(group["is_auto_reply"]),
                )
        return None
