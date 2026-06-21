import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.asr import QwenASRAdapter, create_asr_adapter, format_diarized_text, load_hotword_lines
from app.services.vhf_dialogue import build_vhf_dialogue_review


class DashScopeASRAdapterTests(unittest.TestCase):
    def test_format_diarized_text(self) -> None:
        text = format_diarized_text(
            [
                {"speaker_id": 0, "text": "宁波交管，请讲"},
                {"speaker_id": 1, "text": "锦华662报告"},
            ]
        )
        self.assertIn("说话人0", text)
        self.assertIn("说话人1", text)

    def test_build_dialogue_review_prefers_asr_sentences(self) -> None:
        review = build_vhf_dialogue_review(
            "fallback text",
            asr_sentences=[
                {"speaker_id": 0, "text": "交管收到"},
                {"speaker_id": 1, "text": "申请离泊"},
            ],
        )
        self.assertIn("说话人0：交管收到。", review)
        self.assertIn("说话人1：申请离泊。", review)

    def test_postprocess_applies_sentence_resolver_for_diarization(self) -> None:
        from app.services.entity_resolver import EntityResolver
        from app.services.vhf_dialogue import postprocess_vhf_dialogue

        class FakeResolver:
            def resolve(self, text: str):
                class Result:
                    resolved_text = text.replace("警花662", "锦华662")

                return Result()

        result = postprocess_vhf_dialogue(
            "fallback",
            asr_sentences=[{"speaker_id": 1, "text": "警花662报告"}],
            sentence_resolver=lambda text: FakeResolver().resolve(text).resolved_text,
        )
        self.assertIn("说话人1：锦华662报告。", result.dialogue_review_text)

    def test_postprocess_preserves_realtime_text_as_refinement_evidence(self) -> None:
        from app.services.vhf_dialogue import postprocess_vhf_dialogue

        class DisabledRefiner:
            def refine(self, **kwargs):
                return None

        result = postprocess_vhf_dialogue(
            "整段精修候选：锦龙008",
            original_text="实时话轮：锦龙228接码头通知",
            dialogue_refiner=DisabledRefiner(),
        )

        self.assertEqual("实时话轮：锦龙228接码头通知", result.original_text)

    def test_postprocess_prefers_ship_name_from_substantive_business_turn(self) -> None:
        from app.services.vhf_dialogue import reconcile_event_ship_name

        corrected, dialogue = reconcile_event_ship_name(
            "宁波交管，锦龙008。\n锦龙228接码头通知，金塘南不抛锚了，直接进去。",
            "宁波交管锦龙008。锦龙008接码头通知，金塘南不抛锚了，直接进去。",
            "锦龙008：宁波交管，锦龙008。\n锦龙008：接码头通知，直接进去。",
        )

        self.assertNotIn("锦龙008", corrected)
        self.assertNotIn("锦龙008", dialogue)
        self.assertIn("锦龙228", corrected)

    def test_load_hotword_lines(self) -> None:
        path = Path("data/hotwords/nbzh_hotwords.txt")
        words = load_hotword_lines(path, limit=5)
        self.assertGreaterEqual(len(words), 1)

    def test_qwen_adapter_receives_domain_hotwords_path(self) -> None:
        hotwords_path = Path("data/hotwords/nbzh_hotwords.txt")
        adapter = create_asr_adapter(
            SimpleNamespace(
                asr_provider="qwen_api",
                asr_model="qwen3-asr-flash",
                qwen_asr_api_key_env="DASHSCOPE_API_KEY",
                qwen_asr_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                qwen_asr_timeout_s=120,
                qwen_asr_prompt="VHF test",
                asr_hotwords_path=hotwords_path,
            )
        )

        self.assertIsInstance(adapter, QwenASRAdapter)
        self.assertEqual(hotwords_path, adapter.hotwords_path)

    def test_qwen_adapter_uses_neutral_confidence_when_api_has_no_score(self) -> None:
        adapter = QwenASRAdapter(prompt="")
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="宁波交管，锦龙228。"))]
        )
        client = MagicMock()
        client.chat.completions.create.return_value = response
        adapter._client = client

        with tempfile.TemporaryDirectory() as tmp_dir:
            audio_path = Path(tmp_dir) / "sample.wav"
            audio_path.write_bytes(b"RIFF-test")
            result = adapter.transcribe(audio_path)

        self.assertEqual("宁波交管，锦龙228。", result.text)
        self.assertEqual(0.85, result.confidence)


if __name__ == "__main__":
    unittest.main()
