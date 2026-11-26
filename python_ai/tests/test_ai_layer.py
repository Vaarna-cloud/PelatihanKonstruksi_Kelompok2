"""Unit test untuk lapis penghasil data dan audit pemisahan dua lapis (Bagian 4.6)."""

from __future__ import annotations

from array import array
import json
import math
from pathlib import Path
import socket
import sys
import unittest

PYTHON_AI_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PYTHON_AI_DIR.parent
UNITY_SCRIPTS_DIR = PROJECT_ROOT / "unity_scripts" / "Assets" / "Scripts" / "Intelligence"

sys.path.insert(0, str(PYTHON_AI_DIR))

from audio_features import AdaptiveSignalMeter, EnergyUtteranceSegmenter  # noqa: E402
from recognizers import CommandVocabMatcher, MockRecognizerEngine  # noqa: E402
from udp_emitter import UdpSignalEmitter  # noqa: E402


def _make_tone_pcm(amplitude: int, samples_count: int = 1600) -> bytes:
    buf = array("h")
    for i in range(samples_count):
        val = int(amplitude * math.sin(2.0 * math.pi * 440.0 * i / 16000.0))
        buf.append(val)
    return buf.tobytes()


class TestAudioAndVocabLayer(unittest.TestCase):
    def setUp(self) -> None:
        self.matcher = CommandVocabMatcher(PYTHON_AI_DIR / "vocab_config.json")

    def test_minimum_classes_for_kelompok_2(self) -> None:
        # Kelompok 2 wajib minimal 4 kelas
        self.assertGreaterEqual(len(self.matcher.tokens), 4)

    def test_vocab_matcher_all_tokens_and_unknown(self) -> None:
        expected = {
            "up": "CMD_1",
            "down": "CMD_2",
            "stop": "CMD_3",
            "cancel": "CMD_4",
            "confirm": "CMD_5",
        }
        for word, expected_token in expected.items():
            token, sim, margin = self.matcher.match(word)
            self.assertEqual(token, expected_token)
            self.assertEqual(sim, 1.0)
            self.assertGreater(margin, 0.2)

        unk_token, _, _ = self.matcher.match("xyzabc")
        self.assertEqual(unk_token, "UNKNOWN")

    def test_adaptive_signal_meter_and_vad(self) -> None:
        meter = AdaptiveSignalMeter(initial_noise_floor=0.005)
        quiet_pcm = _make_tone_pcm(amplitude=100, samples_count=1600)
        loud_pcm = _make_tone_pcm(amplitude=12000, samples_count=1600)

        quiet_metrics = meter.update(quiet_pcm)
        self.assertFalse(quiet_metrics.is_speech)

        loud_metrics = meter.update(loud_pcm)
        self.assertTrue(loud_metrics.is_speech)
        self.assertGreater(loud_metrics.snr_db, 10.0)

        segmenter = EnergyUtteranceSegmenter(
            sample_rate=16000,
            min_speech_seconds=0.2,
            hangover_seconds=0.2,
        )
        # 3 frame bicara (300 ms) lalu 3 frame diam (300 ms)
        for _ in range(3):
            self.assertIsNone(segmenter.push(loud_pcm, loud_metrics))
        completed = None
        for _ in range(3):
            res = segmenter.push(quiet_pcm, quiet_metrics)
            if res is not None:
                completed = res
                break
        self.assertIsNotNone(completed)
        audio_bytes, peak_rms, peak_snr = completed
        self.assertGreater(len(audio_bytes), 0)
        self.assertGreater(peak_rms, 0.1)
        self.assertGreater(peak_snr, 10.0)

    def test_mock_recognizer_and_udp_loopback(self) -> None:
        mock = MockRecognizerEngine(self.matcher)
        res = mock.evaluate_manual_input("up 0.91 18.5")
        self.assertIsNotNone(res)
        self.assertEqual(res.token, "CMD_1")
        self.assertAlmostEqual(res.confidence, 0.91, places=3)

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        sock.settimeout(1.0)
        port = sock.getsockname()[1]

        emitter = UdpSignalEmitter(host="127.0.0.1", port=port)
        try:
            emitter.emit_packet(
                token=res.token,
                utterance=res.utterance,
                confidence=res.confidence,
                margin=res.margin,
                signal_level=res.signal_level,
                signal_to_noise_db=res.signal_to_noise_db,
                is_active=True,
                heartbeat=False,
            )
            data, _ = sock.recvfrom(4096)
            decoded = json.loads(data.decode("utf-8"))
            self.assertEqual(decoded["token"], "CMD_1")
            self.assertEqual(decoded["seq"], 1)
            self.assertFalse(decoded["heartbeat"])
        finally:
            emitter.close()
            sock.close()

    def test_pedoman_4_6_two_layer_separation(self) -> None:
        """Memastikan lapis penghasil data dan pemakai tidak saling menyebut isi masing-masing."""
        forbidden_in_python = [
            "crane",
            "supervisor",
            "mandor",
            "harness",
            "scaffolding",
            "konstruksi",
            "material",
            "operator",
            "walkie",
            "pallet",
            "gondola",
            "menu",
            "tokoh",
        ]
        for py_file in PYTHON_AI_DIR.glob("*.py"):
            content = py_file.read_text(encoding="utf-8").lower()
            for word in forbidden_in_python:
                self.assertNotIn(
                    word,
                    content,
                    msg=f"Pelanggaran 4.6: kata '{word}' ditemukan di {py_file.name}",
                )

        forbidden_in_unity = [
            "vosk",
            "whisper",
            "mikrofon",
            "microphone",
            "sounddevice",
            "kaldi",
            "kamera",
            "camera",
            "landmark",
            "sensor",
        ]
        for cs_file in UNITY_SCRIPTS_DIR.glob("*.cs"):
            content = cs_file.read_text(encoding="utf-8").lower()
            for word in forbidden_in_unity:
                self.assertNotIn(
                    word,
                    content,
                    msg=f"Pelanggaran 4.6: kata '{word}' ditemukan di {cs_file.name}",
                )


if __name__ == "__main__":
    unittest.main()
