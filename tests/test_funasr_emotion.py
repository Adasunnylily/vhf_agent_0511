import unittest

from app.domain.models import AudioSegment
from app.services.funasr_emotion import extract_funasr_emotion_tags, extract_funasr_event_tags, format_funasr_emotion_evidence
from app.services.risk_engine import KeywordRiskEngine


class FunASREmotionTests(unittest.TestCase):
    def test_extract_emotion_tags_from_raw_rich_text(self) -> None:
        raw = "<|zh|><|FEARFUL|><|Speech|>Mayday，船舶进水<|withitn|>"
        tags = extract_funasr_emotion_tags(raw)
        self.assertEqual(tags, ["恐惧/焦虑(FEARFUL)"])

    def test_extract_ignores_neutral_and_meta_tokens(self) -> None:
        raw = "<|zh|><|NEUTRAL|><|Speech|>收到，请讲<|withitn|>"
        self.assertEqual(extract_funasr_emotion_tags(raw), [])

    def test_extract_event_tags(self) -> None:
        raw = "<|zh|><|Speech|><|Laughter|>收到<|withitn|>"
        self.assertEqual(extract_funasr_event_tags(raw), ["笑声(Laughter)"])

    def test_format_funasr_emotion_evidence(self) -> None:
        evidence = format_funasr_emotion_evidence(
            ["恐惧/焦虑(FEARFUL)"],
            ["哭泣(Cry)"],
        )
        self.assertEqual(
            evidence,
            [
                "FunASR情感标签: 恐惧/焦虑(FEARFUL)",
                "FunASR事件标签: 哭泣(Cry)",
            ],
        )


class KeywordRiskEngineEmotionEvidenceTests(unittest.TestCase):
    def test_emotion_tags_are_appended_to_risk_event_evidence(self) -> None:
        engine = KeywordRiskEngine()
        segment = AudioSegment(
            id="seg_emotion",
            channel_id="vhf_01",
            file_path="demo.wav",
            clip_path=None,
            start_ms=0,
            end_ms=3000,
            duration_ms=3000,
            text="Mayday，船舶进水，请求救助",
            confidence=0.9,
            asr_emotion_tags=["恐惧/焦虑(FEARFUL)", "愤怒(ANGRY)"],
            asr_event_tags=["哭泣(Cry)"],
        )

        events = engine.evaluate(segment)

        self.assertEqual(len(events), 1)
        self.assertIn("FunASR情感标签: 恐惧/焦虑(FEARFUL), 愤怒(ANGRY)", events[0].evidence)
        self.assertIn("FunASR事件标签: 哭泣(Cry)", events[0].evidence)


if __name__ == "__main__":
    unittest.main()
