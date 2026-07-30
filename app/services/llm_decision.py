from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any, Dict, List, Optional

from app.domain.models import AudioSegment, RiskEvent


DEFAULT_DECISION_PROMPT = """你是“海事VHF数字值班员”的事件理解模块。请根据VHF转写文本、说话人轮次、实体、AIS/模拟AIS信息和声学线索，输出结构化事件理解结果。

核心目标：
1. 不把每句话都当成独立事件，要优先判断是否更新当前通信事件。
2. 风险研判与业务研判并行：高危险情可抢占业务流程。
3. 不得声称已经执行广播、人工接管或归档，只能给出处置建议。
4. 船名、地点、AIS关联不确定时必须标记 uncertain，不允许虚假确认。
5. “请讲”通常是交管；“谢谢老师/谢谢交管/好的谢谢”通常是船方。

请输出严格JSON，不要输出解释文本。必须同时返回兼容字段和 event_understanding 字段。

兼容字段：
{
  "business_type": "routine_report | departure_request | emergency_risk | other_business | invalid_or_noise",
  "risk_level": "INFO | AUTO | MANUAL | L1 | L2 | L3",
  "ship_names": [],
  "locations": [],
  "evidence": [],
  "decision": "auto_reply | manual_review | emergency_takeover | keep_listening",
  "suggested_reply": "",
  "need_human_review": true,
  "reason": ""
}

event_understanding 字段格式：
{
  "shouldCreateOrUpdateEvent": true,
  "normalizedTranscript": "",
  "closingPhrase": "",
  "eventSummary": "",
  "coreEventLabel": "",
  "participants": [
    {"role": "vessel | vts | unknown", "name": "", "confidence": 0.0}
  ],
  "entities": {
    "shipNames": [],
    "locations": [],
    "mmsi": [],
    "operationTerms": []
  },
  "corrections": [
    {"from": "", "to": "", "reason": "hotword | homophone | domain_term | manual_context"}
  ],
  "riskAssessment": {
    "signalSources": ["vhf_semantic"],
    "emergencyTypes": [],
    "vesselAbnormalities": [],
    "unsafeBehaviors": [],
    "acousticAnomalies": [],
    "communicationAnomalies": [],
    "navigationSituation": "normal | potential_conflict | close_quarters | immediate_danger | accident_occurred",
    "riskLevel": "NONE | L4 | L3 | L2 | L1",
    "riskScore": 0.0,
    "confidence": 0.0,
    "evidence": []
  },
  "businessAssessment": {
    "communicationRelation": "vessel_to_vts | vts_to_vessel | vessel_to_vessel | unknown",
    "businessIntent": "dynamic_report | operation_application | distress_report | vessel_coordination | command_acknowledgement | information_query | other | unknown",
    "operationType": "",
    "speechAct": "report | request | command | acknowledgement | coordination | unknown",
    "confidence": 0.0,
    "evidence": []
  },
  "informationCompleteness": {
    "score": 0.0,
    "requiredSlotsComplete": false,
    "missingRequiredFields": [],
    "uncertainFields": []
  },
  "executionRecommendation": {
    "mode": "auto_reply | human_confirm | manual_takeover | monitor_only",
    "reason": "",
    "safetyGatePassed": false,
    "blockedBy": []
  },
  "replyDraft": {
    "text": "",
    "templateMatched": false,
    "matchedRuleId": ""
  }
}

业务判定要点：
- “已经靠妥/抛妥/到达/报告完毕/向交管报告”是航行动态报告，风险为NONE且信息完整时才可 auto_reply。
- “申请离泊/准备开航/起锚/解缆/穿越/掉头申请”是作业或航行申请，必须 human_confirm。
- “火灾/冒烟/失控/进水/碰撞/搁浅/人员落水/Mayday/求救/请求紧急救援”是 distress_report，必须 manual_takeover，risk_level=L1。
- 船舶之间协调、重复呼叫无应答、避让、加车、会遇等默认 monitor_only；若伴随抢越船首、无应答、航速航向异常，应提高风险并建议人工关注。
- 噪声、压盖、过短无业务内容输出 invalid_or_noise 和 keep_listening。
"""


class LLMDecisionClassifier:
    def __init__(
        self,
        *,
        mode: Optional[str] = None,
        model: Optional[str] = None,
        api_key_env: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout_s: Optional[int] = None,
        prompt: Optional[str] = None,
    ) -> None:
        self.mode = (mode or os.getenv("VHF_DECISION_MODE", "rules")).strip().lower()
        self.model = model or os.getenv("VHF_DECISION_MODEL", "qwen-max")
        self.api_key_env = api_key_env or os.getenv("VHF_DECISION_API_KEY_ENV", "DASHSCOPE_API_KEY")
        self.base_url = base_url or os.getenv(
            "VHF_DECISION_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        self.timeout_s = timeout_s or int(os.getenv("VHF_DECISION_TIMEOUT_S", "30"))
        self.prompt = prompt or os.getenv("VHF_DECISION_PROMPT", DEFAULT_DECISION_PROMPT)
        self._client: Any = None

    def is_enabled(self) -> bool:
        return self.mode in {"llm", "hybrid", "llm_first"}

    def evaluate(self, segment: AudioSegment) -> Optional[RiskEvent]:
        if not self.is_enabled():
            return None
        if not os.getenv(self.api_key_env):
            return None

        payload = self._call_llm(segment)
        if not payload:
            return None
        return self._event_from_payload(segment, payload)

    def _call_llm(self, segment: AudioSegment) -> Dict[str, Any]:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("缺少 openai SDK，请安装: pip install openai") from exc

        if self._client is None:
            self._client = OpenAI(
                api_key=os.getenv(self.api_key_env),
                base_url=self.base_url,
                timeout=self.timeout_s,
            )

        user_payload = {
            "asr_text": segment.text,
            "resolved_text": segment.resolved_text or segment.text,
            "confidence": segment.confidence,
            "keywords": segment.keywords,
            "entities": segment.entities,
            "asr_sentences": segment.asr_sentences,
            "emotion_tags": segment.asr_emotion_tags,
            "event_tags": segment.asr_event_tags,
        }
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.prompt},
                {
                    "role": "user",
                    "content": "请对以下VHF通话做业务分类和处置判断：\n"
                    + json.dumps(user_payload, ensure_ascii=False),
                },
            ],
            temperature=0,
            stream=False,
        )
        content = ""
        if getattr(response, "choices", None):
            content = response.choices[0].message.content or ""
        return self._parse_json(content)

    def _parse_json(self, content: str) -> Dict[str, Any]:
        text = (content or "").strip()
        if not text:
            return {}
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
        if "{" in text and "}" in text:
            text = text[text.find("{") : text.rfind("}") + 1]
        data = json.loads(text)
        return data if isinstance(data, dict) else {}

    def _event_from_payload(self, segment: AudioSegment, payload: Dict[str, Any]) -> RiskEvent:
        payload = self._normalize_payload(payload)
        business_type = self._safe_choice(
            str(payload.get("business_type") or "other_business"),
            {"routine_report", "departure_request", "emergency_risk", "other_business", "invalid_or_noise"},
            "other_business",
        )
        decision = self._safe_choice(
            str(payload.get("decision") or ""),
            {"auto_reply", "manual_review", "emergency_takeover", "keep_listening"},
            self._default_decision(business_type),
        )
        risk_level = self._safe_choice(
            str(payload.get("risk_level") or ""),
            {"INFO", "AUTO", "MANUAL", "L1", "L2", "L3"},
            self._default_risk_level(business_type, decision),
        )
        need_human_review = bool(payload.get("need_human_review", decision != "auto_reply"))
        action_type = self._action_type(decision, business_type)
        is_auto_reply = action_type == "auto_reply" and not need_human_review
        evidence = self._string_list(payload.get("evidence"))
        evidence.insert(0, f"LLM业务类型: {business_type}")
        evidence.append(f"LLM模型: {self.model}")
        reason = str(payload.get("reason") or "").strip()
        if reason:
            evidence.append(f"LLM理由: {reason}")

        return RiskEvent(
            id=f"evt_{uuid.uuid4().hex[:12]}",
            segment_id=segment.id,
            channel_id=segment.channel_id,
            event_type=self._event_type(business_type),
            risk_level=risk_level,
            summary=reason or f"LLM判定为{self._event_type(business_type)}。",
            evidence=evidence,
            suggestion=self._suggestion(payload, business_type, decision),
            broadcast_text=str(payload.get("suggested_reply") or "").strip(),
            action_type=action_type,
            requires_human_review=need_human_review,
            is_auto_reply=is_auto_reply,
        )

    def _normalize_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Accept the new digital-duty schema while preserving the legacy API contract."""
        if not isinstance(payload, dict):
            return {}
        normalized = dict(payload)
        understanding = payload.get("event_understanding")
        if not isinstance(understanding, dict):
            return normalized

        business = understanding.get("businessAssessment") or {}
        risk = understanding.get("riskAssessment") or {}
        execution = understanding.get("executionRecommendation") or {}
        reply = understanding.get("replyDraft") or {}
        entities = understanding.get("entities") or {}

        intent = str(business.get("businessIntent") or "").strip()
        mode = str(execution.get("mode") or "").strip()
        risk_level = str(risk.get("riskLevel") or "").strip().upper()

        if not normalized.get("business_type"):
            normalized["business_type"] = {
                "dynamic_report": "routine_report",
                "operation_application": "departure_request",
                "distress_report": "emergency_risk",
                "vessel_coordination": "other_business",
                "command_acknowledgement": "other_business",
                "information_query": "other_business",
                "other": "other_business",
                "unknown": "other_business",
            }.get(intent, "other_business")
        if not normalized.get("decision"):
            normalized["decision"] = {
                "auto_reply": "auto_reply",
                "human_confirm": "manual_review",
                "manual_takeover": "emergency_takeover",
                "monitor_only": "keep_listening",
            }.get(mode, "")
        if not normalized.get("risk_level"):
            normalized["risk_level"] = {
                "NONE": "INFO",
                "L4": "INFO",
                "L3": "L3",
                "L2": "L2",
                "L1": "L1",
            }.get(risk_level, "INFO")
        if not normalized.get("suggested_reply"):
            normalized["suggested_reply"] = str(reply.get("text") or "").strip()
        if not normalized.get("reason"):
            normalized["reason"] = str(execution.get("reason") or understanding.get("eventSummary") or "").strip()
        if not normalized.get("ship_names"):
            normalized["ship_names"] = entities.get("shipNames") or []
        if not normalized.get("locations"):
            normalized["locations"] = entities.get("locations") or []
        evidence = self._string_list(normalized.get("evidence"))
        evidence.extend(self._string_list(risk.get("evidence")))
        evidence.extend(self._string_list(business.get("evidence")))
        if reply.get("matchedRuleId"):
            evidence.append(f"知识规则: {reply.get('matchedRuleId')}")
        normalized["evidence"] = evidence
        if "need_human_review" not in normalized:
            normalized["need_human_review"] = mode != "auto_reply"
        return normalized

    def _suggestion(self, payload: Dict[str, Any], business_type: str, decision: str) -> str:
        reply = str(payload.get("suggested_reply") or "").strip()
        if decision == "auto_reply" and reply:
            return f"建议自动回复：{reply}"
        if business_type == "emergency_risk":
            return "建议立即人工接管，核实船位、险情、人员情况和周边AIS态势。"
        if business_type == "departure_request":
            return "该请求涉及由静到动或关键航行操作，建议值班员人工审核后回复。"
        if business_type == "routine_report":
            return "识别为常规报告，可由值班员复核后发送标准回复。"
        return "建议记录并继续守听，必要时人工复核。"

    @staticmethod
    def _safe_choice(value: str, allowed: set[str], fallback: str) -> str:
        return value if value in allowed else fallback

    @staticmethod
    def _string_list(value: Any) -> List[str]:
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        if value:
            return [str(value)]
        return []

    @staticmethod
    def _default_decision(business_type: str) -> str:
        return {
            "routine_report": "auto_reply",
            "departure_request": "manual_review",
            "emergency_risk": "emergency_takeover",
            "invalid_or_noise": "keep_listening",
        }.get(business_type, "keep_listening")

    @staticmethod
    def _default_risk_level(business_type: str, decision: str) -> str:
        if business_type == "emergency_risk":
            return "L1"
        if business_type == "routine_report" and decision == "auto_reply":
            return "AUTO"
        if business_type == "departure_request":
            return "MANUAL"
        return "INFO"

    @staticmethod
    def _action_type(decision: str, business_type: str) -> str:
        if decision == "auto_reply":
            return "auto_reply"
        if decision == "emergency_takeover":
            return "emergency_manual"
        if business_type == "departure_request":
            return "manual_business"
        if decision == "keep_listening":
            return "keep_listening"
        return "manual_review"

    @staticmethod
    def _event_type(business_type: str) -> str:
        return {
            "routine_report": "LLM常规报告",
            "departure_request": "LLM离泊/关键申请",
            "emergency_risk": "LLM紧急险情",
            "invalid_or_noise": "LLM无效或噪声",
        }.get(business_type, "LLM一般业务")
