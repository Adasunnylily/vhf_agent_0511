import unittest

from app.services.asr import format_diarized_text, load_hotword_lines
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

    def test_load_hotword_lines(self) -> None:
        from pathlib import Path

        path = Path("data/hotwords/nbzh_hotwords.txt")
        words = load_hotword_lines(path, limit=5)
        self.assertGreaterEqual(len(words), 1)


if __name__ == "__main__":
    unittest.main()
