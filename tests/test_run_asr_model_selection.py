import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts.run_asr_model_selection import (
    build_wide_rows,
    load_model_specs,
    make_result_row,
    read_external_results,
)
from app.services.asr import ASRResult


class RunAsrModelSelectionTests(unittest.TestCase):
    def test_load_model_specs_accepts_api_and_external_providers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Path(tmpdir) / "models.json"
            config.write_text(
                json.dumps(
                    {
                        "models": [
                            {
                                "name": "openai_whisper_1",
                                "provider": "openai_audio",
                                "model": "whisper-1",
                            },
                            {
                                "name": "doubao_external",
                                "provider": "external_csv",
                                "model": "Doubao-ASR-2.0",
                                "result_path": "doubao.csv",
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            specs = load_model_specs(config, ["openai_whisper_1", "doubao_external"])

            self.assertEqual([item["provider"] for item in specs], ["openai_audio", "external_csv"])

    def test_external_csv_results_merge_by_segment_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result_path = Path(tmpdir) / "qwen.csv"
            with result_path.open("w", encoding="utf-8-sig", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=["segment_id", "asr_text", "asr_confidence"])
                writer.writeheader()
                writer.writerow(
                    {
                        "segment_id": "seg_000001",
                        "asr_text": "VTS宁远8报告已靠泊三号码头",
                        "asr_confidence": "0.93",
                    }
                )

            rows = [
                {
                    "segment_id": "seg_000001",
                    "clip_path": "/tmp/seg_000001.wav",
                    "start_ms": "0",
                    "end_ms": "3000",
                }
            ]
            spec = {
                "name": "qwen3_asr_external",
                "provider": "external_csv",
                "model": "Qwen3-ASR-1.7B",
                "result_path": str(result_path),
            }

            long_rows = read_external_results(spec, rows)
            wide_rows = build_wide_rows(rows, long_rows)

            self.assertEqual(long_rows[0]["asr_text"], "VTS宁远8报告已靠泊三号码头")
            self.assertEqual(wide_rows[0]["asr_text__qwen3_asr_external"], "VTS宁远8报告已靠泊三号码头")
            self.assertEqual(wide_rows[0]["asr_error__qwen3_asr_external"], "")

    def test_language_guard_flags_japanese_and_korean_scripts(self) -> None:
        row = {"segment_id": "seg_1", "clip_path": "/tmp/seg_1.wav"}
        spec = {"name": "model_a"}

        result_row = make_result_row(
            row=row,
            spec=spec,
            provider="test",
            result=ASRResult(text="こちらVTS 안녕하세요", confidence=0.0, engine="test"),
        )

        self.assertEqual(result_row["language_guard_flag"], "1")
        self.assertIn("japanese_kana", result_row["language_guard_notes"])
        self.assertIn("korean_hangul", result_row["language_guard_notes"])


if __name__ == "__main__":
    unittest.main()
