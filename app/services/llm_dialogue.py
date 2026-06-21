from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


DEFAULT_DIALOGUE_PROMPT = """你是海事VHF通话校对与对话重建助手。

请根据ASR原文、轻量初修文本、领域热词、已知船名/地名候选、ASR句子，完成：
1. 修正明显错误的船名、地名、泊位名、动作词和VHF数字读法。
2. 重建说话人轮次，尽量区分宁波交管、船方A、船方B；船名明确时用船名。
3. 不要凭空新增没有依据的船名、地点或业务事实。
4. 如果无法确认船名，使用“疑似船方A/疑似船方B/待确认说话人”。
5. 如果候选实体与ASR读音接近，优先使用候选实体。
6. “请讲、收到、注意安全、再会、好下一个”等短句一般是交管/岸台话术；除非上下文明确是船船对话，否则 speaker 标为“宁波交管”，role 标为“vts”。
7. 同一通信事件中，若相近船名在完整业务报告里重复出现，而另一个只在短呼叫中出现一次，优先采用重复且上下文完整的船名，并保持该船说话人名称一致。
8. 领域热词是纠错参考，不是必须全部使用；只有当ASR发音、上下文或候选实体支持时才替换。
9. 热词按类别提供：vessels 是船名，locations_and_waters 是地名/水域，berths_and_facilities 是泊位/码头设施，vhf_phrases 是VHF常用话术，navigation_actions 是业务动作，risk_terms 是风险词。请优先在对应类别中查找。

只输出JSON，不要输出解释文本。JSON格式：
{
  "corrected_text": "修正后的连续文本",
  "turns": [
    {
      "speaker": "宁波交管 | 船名 | 疑似船方A | 疑似船方B | 待确认说话人",
      "role": "vts | ship | unknown",
      "text": "该轮话语"
    }
  ],
  "ships": [],
  "locations": [],
  "uncertain_fields": [],
  "confidence": 0.0
}"""


@dataclass(frozen=True)
class LLMDialogueRefinement:
    corrected_text: str
    dialogue_review_text: str
    payload: Dict[str, Any]


class LLMDialogueRefiner:
    def __init__(
        self,
        *,
        mode: Optional[str] = None,
        model: Optional[str] = None,
        api_key_env: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout_s: Optional[int] = None,
        prompt: Optional[str] = None,
        hotwords_path: Optional[str] = None,
        hotwords_limit: Optional[int] = None,
    ) -> None:
        self.mode = (mode or os.getenv("VHF_DIALOGUE_MODE", "rules")).strip().lower()
        self.model = model or os.getenv("VHF_DIALOGUE_MODEL", os.getenv("VHF_DECISION_MODEL", "qwen-max"))
        self.api_key_env = api_key_env or os.getenv(
            "VHF_DIALOGUE_API_KEY_ENV",
            os.getenv("VHF_DECISION_API_KEY_ENV", "DASHSCOPE_API_KEY"),
        )
        self.base_url = base_url or os.getenv(
            "VHF_DIALOGUE_BASE_URL",
            os.getenv("VHF_DECISION_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        )
        self.timeout_s = timeout_s or int(os.getenv("VHF_DIALOGUE_TIMEOUT_S", "30"))
        self.prompt = prompt or os.getenv("VHF_DIALOGUE_PROMPT", DEFAULT_DIALOGUE_PROMPT)
        self.hotwords_path = hotwords_path or os.getenv(
            "VHF_DIALOGUE_HOTWORDS_PATH",
            os.getenv("VHF_ASR_HOTWORDS_PATH", "data/hotwords/nbzh_hotwords.txt"),
        )
        self.hotwords_limit = hotwords_limit or int(os.getenv("VHF_DIALOGUE_HOTWORDS_LIMIT", "80"))
        self.fail_fast = os.getenv("VHF_DIALOGUE_FAIL_FAST", "0") == "1"
        self._client: Any = None

    def is_enabled(self) -> bool:
        return self.mode in {"llm", "hybrid", "llm_first"}

    def refine(
        self,
        *,
        original_text: str,
        rule_resolved_text: str,
        rule_dialogue_review_text: str,
        entity_candidates: Optional[List[Dict[str, Any]]] = None,
        asr_sentences: Optional[List[dict]] = None,
        domain_hotwords: Optional[Any] = None,
    ) -> Optional[LLMDialogueRefinement]:
        if not self.is_enabled():
            return None
        if not os.getenv(self.api_key_env):
            return None
        try:
            payload = self._call_llm(
                original_text=original_text,
                rule_resolved_text=rule_resolved_text,
                rule_dialogue_review_text=rule_dialogue_review_text,
                entity_candidates=entity_candidates or [],
                asr_sentences=asr_sentences or [],
                domain_hotwords=domain_hotwords or self._load_domain_hotwords(),
            )
            corrected = str(payload.get("corrected_text") or "").strip()
            turns = payload.get("turns")
            dialogue = self._format_turns(turns)
            if not corrected or not dialogue:
                return None
            return LLMDialogueRefinement(corrected, dialogue, payload)
        except Exception:
            if self.fail_fast:
                raise
            return None

    def _call_llm(
        self,
        *,
        original_text: str,
        rule_resolved_text: str,
        rule_dialogue_review_text: str,
        entity_candidates: List[Dict[str, Any]],
        asr_sentences: List[dict],
        domain_hotwords: Any,
    ) -> Dict[str, Any]:
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
            "asr_text": original_text,
            "rule_resolved_text": rule_resolved_text,
            "rule_dialogue_review_text": rule_dialogue_review_text,
            "domain_hotwords": self._compact_hotwords(domain_hotwords),
            "entity_candidates": self._compact_candidates(entity_candidates),
            "asr_sentences": asr_sentences,
        }
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.prompt},
                {
                    "role": "user",
                    "content": "请修正以下VHF ASR文本并重建对话轮次：\n"
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

    def _format_turns(self, turns: Any) -> str:
        if not isinstance(turns, list):
            return ""
        rows: List[str] = []
        for item in turns:
            if not isinstance(item, dict):
                continue
            speaker = str(item.get("speaker") or "待确认说话人").strip() or "待确认说话人"
            text = str(item.get("text") or "").strip(" ，,。")
            if text:
                rows.append(f"{speaker}：{text}。")
        return "\n".join(rows)

    def _compact_candidates(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        compact: List[Dict[str, Any]] = []
        for item in candidates[:12]:
            compact.append(
                {
                    "entity_type": item.get("entity_type"),
                    "canonical": item.get("canonical"),
                    "matched_text": item.get("matched_text"),
                    "score": item.get("score"),
                    "source": item.get("source"),
                }
            )
        return compact

    def _load_domain_hotwords(self) -> Any:
        path = (self.hotwords_path or "").strip()
        if not path:
            return {}
        try:
            if path.endswith(".json"):
                with open(path, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                if isinstance(payload, dict):
                    return {
                        str(key): [str(item).strip() for item in value if str(item).strip()][: self.hotwords_limit]
                        for key, value in payload.items()
                        if isinstance(value, list)
                    }
            with open(path, "r", encoding="utf-8") as handle:
                words = []
                seen = set()
                for line in handle:
                    word = line.strip()
                    if not word or word.startswith("#") or word in seen:
                        continue
                    seen.add(word)
                    words.append(word)
                    if len(words) >= self.hotwords_limit:
                        break
                return {"general": words}
        except (OSError, json.JSONDecodeError):
            return {}

    def _compact_hotwords(self, hotwords: Any) -> Any:
        if isinstance(hotwords, dict):
            return {
                str(key): [str(item).strip() for item in value if str(item).strip()][: self.hotwords_limit]
                for key, value in hotwords.items()
                if isinstance(value, list)
            }
        if isinstance(hotwords, list):
            return {"general": [str(item).strip() for item in hotwords if str(item).strip()][: self.hotwords_limit]}
        return {}
