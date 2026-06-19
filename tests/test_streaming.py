import struct
import tempfile
import unittest
import wave
from pathlib import Path

from app.config import Settings
from app.services.asr import ASRResult, BaseASRAdapter
from app.services.preprocess import AudioPreprocessor
from app.services.storage import LocalStorage
from app.services.streaming import StreamingAudioProcessor
from app.services.vad import WavEnergyVAD


class DummyASR(BaseASRAdapter):
    def transcribe(self, file_path: Path, transcript_override=None) -> ASRResult:
        return ASRResult(text=transcript_override or "收到，请保持守听", confidence=0.9, engine="fake")


class DummyRiskEngine:
    def evaluate(self, segment):
        return []


class DummyWSManager:
    def publish(self, channel_id, payload) -> None:
        return None


def write_two_utterance_wav(path: Path) -> None:
    sample_rate = 16000
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        frames = bytearray()
        for amplitude, seconds in [(1200, 1.0), (0, 0.6), (1200, 1.0)]:
            for _ in range(int(sample_rate * seconds)):
                frames.extend(struct.pack("<h", amplitude))
        wav_file.writeframes(frames)


class StreamingAudioProcessorTests(unittest.TestCase):
    def test_segment_callback_reports_incremental_progress(self) -> None:
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
            processor = StreamingAudioProcessor(
                preprocessor=AudioPreprocessor(storage),
                vad=WavEnergyVAD(
                    silence_ms=300,
                    min_speech_ms=300,
                    energy_threshold=200,
                    threshold_mode="fixed",
                ),
                asr=DummyASR(),
                risk_engine=DummyRiskEngine(),  # type: ignore[arg-type]
                storage=storage,
                ws_manager=DummyWSManager(),  # type: ignore[arg-type]
                simulation_speed=0,
            )
            source = base / "stream.wav"
            write_two_utterance_wav(source)
            progress = []

            segments, _ = processor.process_file_stream(
                source,
                "vhf_demo_01",
                on_segment=lambda segment, events, index, total: progress.append(
                    (segment.id, index, total)
                ),
            )

            self.assertEqual(2, len(segments))
            self.assertEqual(2, len(progress))
            self.assertEqual([0, 1], [item[1] for item in progress])
            self.assertTrue(all(item[2] == 2 for item in progress))


if __name__ == "__main__":
    unittest.main()
