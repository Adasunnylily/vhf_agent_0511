import tempfile
import unittest
import wave
import struct
from pathlib import Path

from app.config import Settings
from app.services.asr import ASRResult, BaseASRAdapter
from app.services.pipeline import AudioPipeline
from app.services.preprocess import AudioPreprocessor
from app.services.risk_engine import KeywordRiskEngine
from app.services.storage import LocalStorage
from app.services.vad import WavEnergyVAD


def write_demo_wav(file_path: Path) -> None:
    with wave.open(str(file_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * 16000)


def write_long_demo_wav(file_path: Path, seconds: int = 20) -> None:
    with wave.open(str(file_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x10\x10" * 16000 * seconds)


def write_energy_pattern_wav(file_path: Path) -> None:
    sample_rate = 16000
    pattern = [
        (600, 0.5),
        (2500, 1.0),
        (600, 0.7),
        (2500, 1.0),
        (600, 0.5),
    ]
    with wave.open(str(file_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        frames = bytearray()
        for amplitude, seconds in pattern:
            for _ in range(int(sample_rate * seconds)):
                frames.extend(struct.pack("<h", amplitude))
        wav_file.writeframes(bytes(frames))


class FakeASRAdapter(BaseASRAdapter):
    def transcribe(self, file_path: Path, transcript_override=None) -> ASRResult:
        text = transcript_override or "前方船舶请让清航道，注意避让，存在碰撞风险"
        return ASRResult(text=text, confidence=0.93, engine="fake_asr")


class AudioPipelineTests(unittest.TestCase):
    def test_pipeline_creates_l2_event_from_override_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            settings = Settings(
                data_dir=base / "data",
                upload_dir=base / "data" / "uploads",
                normalized_dir=base / "data" / "normalized",
                clip_dir=base / "data" / "clips",
                event_dir=base / "data" / "events",
            )
            storage = LocalStorage(settings)
            pipeline = AudioPipeline(
                preprocessor=AudioPreprocessor(storage),
                vad=WavEnergyVAD(),
                asr=FakeASRAdapter(),
                risk_engine=KeywordRiskEngine(),
                storage=storage,
            )

            wav_path = base / "demo.wav"
            write_demo_wav(wav_path)

            result = pipeline.process(
                file_path=wav_path,
                channel_id="vhf_demo_01",
                transcript_override="前方船舶请让清航道，注意避让，存在碰撞风险",
            )
            segments = result.segments
            events = result.events

            self.assertEqual(len(segments), 1)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].risk_level, "L2")
            self.assertTrue((settings.event_dir / f"{events[0].id}.json").exists())
            self.assertIn("processed_path", pipeline.process(
                file_path=wav_path,
                channel_id="vhf_demo_01",
                transcript_override="前方船舶请让清航道，注意避让，存在碰撞风险",
            ).preprocess)

    def test_vad_forces_split_on_long_segment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = Path(tmpdir) / "long.wav"
            write_long_demo_wav(wav_path, seconds=20)
            vad = WavEnergyVAD(max_segment_ms=8000, energy_threshold=1)

            segments = vad.detect(wav_path)

            self.assertGreaterEqual(len(segments), 3)
            self.assertTrue(all(seg.end_ms - seg.start_ms <= 8040 for seg in segments))

    def test_vad_can_disable_fixed_length_split(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = Path(tmpdir) / "long.wav"
            write_long_demo_wav(wav_path, seconds=20)
            vad = WavEnergyVAD(max_segment_ms=0, energy_threshold=1)

            segments = vad.detect(wav_path)

            self.assertEqual(len(segments), 1)
            self.assertGreaterEqual(segments[0].end_ms - segments[0].start_ms, 19000)

    def test_adaptive_vad_splits_above_radio_noise_floor(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = Path(tmpdir) / "radio_noise.wav"
            write_energy_pattern_wav(wav_path)
            vad = WavEnergyVAD(
                threshold_mode="adaptive",
                energy_threshold=450,
                silence_ms=300,
                min_speech_ms=300,
                max_segment_ms=0,
            )

            segments = vad.detect(wav_path)

            self.assertEqual(len(segments), 2)
            self.assertGreater(vad.last_threshold, 600)


if __name__ == "__main__":
    unittest.main()
