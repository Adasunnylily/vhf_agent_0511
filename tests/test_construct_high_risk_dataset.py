import unittest
import tempfile
import wave
from pathlib import Path

from scripts.construct_high_risk_dataset import (
    build_raw_manifest,
    choose_final_analysis,
    classify_role,
    is_standard_pcm_wav,
    load_model_analysis,
    priority_score,
    weak_label_risk,
)


class ConstructHighRiskDatasetTests(unittest.TestCase):
    def test_classify_ship_call(self) -> None:
        result = classify_role("VTS，宁远8报告，已靠泊3号码头")

        self.assertEqual(result.role, "ship")
        self.assertIn("报告", result.evidence)

    def test_classify_operator_reply(self) -> None:
        result = classify_role("宁远8，VTS收到，请保持守听")

        self.assertEqual(result.role, "operator")

    def test_high_risk_weak_label(self) -> None:
        result = weak_label_risk("我船机舱冒烟，请求救助", "ship")

        self.assertEqual(result.risk_label, "high")
        self.assertEqual(result.risk_type, "fire_or_explosion")
        self.assertEqual(result.automation_label, "manual_immediate")

    def test_normal_weak_label(self) -> None:
        result = weak_label_risk("VTS，海丰32报告，已抛好锚", "ship")

        self.assertEqual(result.risk_label, "normal")
        self.assertEqual(result.automation_label, "auto_reply")

    def test_manual_advice_for_weather_query(self) -> None:
        result = weak_label_risk("VTS，请问前方能见度和气象情况", "ship")

        self.assertEqual(result.risk_category, "non_high_risk")
        self.assertEqual(result.automation_label, "llm_advice")

    def test_high_risk_anchor_dragging(self) -> None:
        result = weak_label_risk("我船走锚，需要援助", "ship")

        self.assertEqual(result.risk_label, "high")
        self.assertEqual(result.risk_type, "anchor_dragging")

    def test_operator_keywords_extracted_for_instruction(self) -> None:
        result = weak_label_risk("请立即报告位置和人员数量", "operator")

        self.assertIn("立即", result.matched_operator_keywords)
        self.assertEqual(result.risk_label, "not_target")

    def test_non_ship_is_not_target(self) -> None:
        result = weak_label_risk("VTS收到，请保持守听", "operator")

        self.assertEqual(result.risk_label, "not_target")

    def test_review_priority_orders_high_risk(self) -> None:
        score = priority_score(
            {
                "risk_label_pred": "high",
                "role_pred": "ship",
                "weak_confidence": "0.88",
                "asr_text": "机舱冒烟请求救助",
            }
        )

        self.assertGreaterEqual(score, 100)

    def test_llm_analysis_overrides_rule_fallback(self) -> None:
        final = choose_final_analysis(
            segment_id="seg_1",
            asr_text="收到，请保持守听",
            llm_map={
                "seg_1": load_model_analysis_row(
                    role_label="ship",
                    crisis_label="non_crisis",
                    automation_label="auto_reply",
                    scenario="anchor_completed",
                )
            },
            audio_map={},
        )

        self.assertEqual(final.source, "llm_analysis")
        self.assertEqual(final.role_label, "ship")
        self.assertEqual(final.automation_label, "auto_reply")

    def test_standard_pcm_wav_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.wav"
            with wave.open(str(path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(16000)
                wav_file.writeframes(b"\x00\x00" * 160)

            self.assertTrue(is_standard_pcm_wav(path))

    def test_raw_manifest_excludes_generated_pipeline_audio(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            raw_dir = base / "raw_audio"
            generated_dir = base / "data_pipeline" / "clips" / "vad_segments"
            raw_dir.mkdir(parents=True)
            generated_dir.mkdir(parents=True)
            write_silent_wav(raw_dir / "source.wav")
            write_silent_wav(generated_dir / "old_seg.wav")
            output = base / "manifest.csv"

            build_raw_manifest(base, output, "test_channel")

            text = output.read_text(encoding="utf-8-sig")
            self.assertIn("source.wav", text)
            self.assertNotIn("old_seg.wav", text)


def load_model_analysis_row(role_label: str, crisis_label: str, automation_label: str, scenario: str):
    from scripts.construct_high_risk_dataset import ModelAnalysis

    return ModelAnalysis(
        source="llm",
        role_label=role_label,
        role_confidence=0.9,
        crisis_label=crisis_label,
        crisis_confidence=0.8,
        automation_label=automation_label,
        scenario=scenario,
        evidence=["test"],
        rationale="unit test",
    )


def write_silent_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * 160)


if __name__ == "__main__":
    unittest.main()
