import tempfile
import unittest
import wave
from array import array
from pathlib import Path

from app.services.audio_utils import pcm_rms, write_pcm_wav


class MicPcmTests(unittest.TestCase):
    def test_pcm_rms_distinguishes_speech_from_silence(self) -> None:
        silence = array("h", [0] * 1600).tobytes()
        speech = array("h", [1200, -1200] * 800).tobytes()

        self.assertEqual(0.0, pcm_rms(silence))
        self.assertGreater(pcm_rms(speech), 1000.0)

    def test_write_pcm_wav_creates_16k_mono_audio(self) -> None:
        pcm = array("h", [500, -500] * 8000).tobytes()
        with tempfile.TemporaryDirectory() as tmp_dir:
            wav_path = Path(tmp_dir) / "utterance.wav"
            write_pcm_wav(wav_path, pcm, sample_rate=16000)

            with wave.open(str(wav_path), "rb") as wav_file:
                self.assertEqual(1, wav_file.getnchannels())
                self.assertEqual(2, wav_file.getsampwidth())
                self.assertEqual(16000, wav_file.getframerate())
                self.assertEqual(16000, wav_file.getnframes())


if __name__ == "__main__":
    unittest.main()
