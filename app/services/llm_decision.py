from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any, Dict, List, Optional

from app.domain.models import AudioSegment, RiskEvent


DEFAULT_DECISION_PROMPT = """你是海事交管智能值班员。请根据VHF转写文本、说话人轮次、实体、AIS信息和声学线索，判断当前通话应如何处置。

业务标签只能从以下选择：
- routine_report：常规报告，通常为靠妥、抛妥、抵港、动态转静态，可考虑自动回复
- departure_request：离泊、起锚、开航、穿越、解缆、备车等由静到动或需要许可的申请，必须人工审核
- emergency_risk：冒烟、着火、碰撞、搁浅、失控、进水、人员落水、机械故障、危险品、求救等高危情况
- other_business：一般业务、船船沟通、航速航向协调、普通提醒，默认记录并继续监听
- invalid_or_noise：噪声、压盖、听不清、无有效业务

判断规则：
1. 高危词、明显紧急语气或声学异常优先判为 emergency_risk。
2. “申请离泊、准备开航、锚离底、起锚、解缆、穿越警戒区”等判为 departure_request。
3. “靠妥、抛妥、抵达、向您报告、不抛锚直接进去”等常规报告可判为 routine_report。
4. 船船之间关于加车、避让、前后船、绿灯红灯的沟通，若无明显危险，判为 other_business；若涉及速度、航向、船位异常，建议人工关注。
5. 如果ASR置信度低、船名/地点不确定，必须要求人工复核。

只输出JSON，不要输出解释文本。JSON格式：
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
}"""


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
