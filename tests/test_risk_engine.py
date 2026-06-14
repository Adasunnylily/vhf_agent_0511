import unittest

from app.domain.models import AudioSegment, RiskEvent
from app.services.risk_engine import KeywordRiskEngine


class KeywordRiskEngineTests(unittest.TestCase):
    def test_llm_decision_takes_precedence_when_available(self) -> None:
        class FakeDecisionClassifier:
            def evaluate(self, segment: AudioSegment) -> RiskEvent:
                return RiskEvent(
                    id="evt_llm",
                    segment_id=segment.id,
                    channel_id=segment.channel_id,
                    event_type="LLM紧急险情",
                    risk_level="L1",
                    summary="LLM判定存在高危。",
                    evidence=["LLM业务类型: emergency_risk"],
                    suggestion="立即人工接管。",
                    broadcast_text="",
                    action_type="emergency_manual",
                    requires_human_review=True,
                    is_auto_reply=False,
                )

        engine = KeywordRiskEngine(decision_classifier=FakeDecisionClassifier())  # type: ignore[arg-type]
        segment = AudioSegment(
            id="seg_llm",
            channel_id="vhf_01",
            file_path="demo.wav",
            clip_path=None,
            start_ms=0,
            end_ms=2000,
            duration_ms=2000,
            text="VTS，海丰32申请离泊",
            confidence=0.91,
        )

        events = engine.evaluate(segment)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "LLM紧急险情")
        self.assertEqual(events[0].risk_level, "L1")

    def test_l1_keyword_creates_emergency_event(self) -> None:
        engine = KeywordRiskEngine()
        segment = AudioSegment(
            id="seg_1",
            channel_id="vhf_01",
            file_path="demo.wav",
            clip_path=None,
            start_ms=0,
            end_ms=3000,
            duration_ms=3000,
            text="Mayday，船舶进水，请求救助",
            confidence=0.9,
        )

        events = engine.evaluate(segment)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].risk_level, "L1")
        self.assertEqual(events[0].event_type, "紧急险情")

    def test_text_without_keywords_creates_no_event(self) -> None:
        engine = KeywordRiskEngine()
        segment = AudioSegment(
            id="seg_2",
            channel_id="vhf_01",
            file_path="demo.wav",
            clip_path=None,
            start_ms=0,
            end_ms=2000,
            duration_ms=2000,
            text="收到，请继续守听",
            confidence=0.8,
        )

        events = engine.evaluate(segment)

        self.assertEqual(events, [])

    def test_static_report_can_auto_reply_above_threshold(self) -> None:
        engine = KeywordRiskEngine()
        segment = AudioSegment(
            id="seg_3",
            channel_id="vhf_01",
            file_path="demo.wav",
            clip_path=None,
            start_ms=0,
            end_ms=2000,
            duration_ms=2000,
            text="VTS，宁远8已靠泊码头，报告完毕",
            confidence=0.92,
        )

        events = engine.evaluate(segment)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].risk_level, "AUTO")
        self.assertTrue(events[0].is_auto_reply)
        self.assertFalse(events[0].requires_human_review)

    def test_static_report_low_confidence_requires_recheck(self) -> None:
        engine = KeywordRiskEngine()
        segment = AudioSegment(
            id="seg_4",
            channel_id="vhf_01",
            file_path="demo.wav",
            clip_path=None,
            start_ms=0,
            end_ms=2000,
            duration_ms=2000,
            text="VTS，海丰32已抛好锚",
            confidence=0.72,
        )

        events = engine.evaluate(segment)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].action_type, "auto_reply_recheck")
        self.assertFalse(events[0].is_auto_reply)
        self.assertTrue(events[0].requires_human_review)

    def test_departure_request_routes_to_manual_business(self) -> None:
        engine = KeywordRiskEngine()
        segment = AudioSegment(
            id="seg_5",
            channel_id="vhf_01",
            file_path="demo.wav",
            clip_path=None,
            start_ms=0,
            end_ms=2000,
            duration_ms=2000,
            text="VTS，海丰32申请离泊，请求出港，目的地北槽",
            confidence=0.91,
        )

        events = engine.evaluate(segment)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].risk_level, "MANUAL")
        self.assertEqual(events[0].action_type, "manual_business")
        self.assertTrue(events[0].requires_human_review)


if __name__ == "__main__":
    unittest.main()
