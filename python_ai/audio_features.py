"""Pemrosesan sinyal audio murni: RMS, estimasi noise floor adaptif, SNR, dan VAD."""

from __future__ import annotations

from array import array
import math
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class FrameMetrics:
    """Metrik sinyal untuk satu potongan audio."""

    rms: float
    noise_floor: float
    snr_db: float
    is_speech: bool


class AdaptiveSignalMeter:
    """Mengukur energi sinyal (RMS), noise floor adaptif, dan SNR (dB)."""

    def __init__(
        self,
        initial_noise_floor: float = 0.008,
        min_noise_floor: float = 0.002,
        ema_alpha: float = 0.05,
        speech_snr_threshold_db: float = 6.0,
        min_speech_rms: float = 0.015,
    ) -> None:
        self.noise_floor = max(initial_noise_floor, min_noise_floor)
        self.min_noise_floor = min_noise_floor
        self.ema_alpha = ema_alpha
        self.speech_snr_threshold_db = speech_snr_threshold_db
        self.min_speech_rms = min_speech_rms

    @staticmethod
    def compute_rms_int16(pcm_bytes: bytes) -> float:
        """Menghitung Root Mean Square ternormalisasi [0.0, 1.0] dari buffer PCM int16."""
        if not pcm_bytes:
            return 0.0
        usable_len = len(pcm_bytes) - (len(pcm_bytes) % 2)
        if usable_len == 0:
            return 0.0
        samples = array("h")
        samples.frombytes(pcm_bytes[:usable_len])
        mean_sq = sum((s / 32768.0) ** 2 for s in samples) / len(samples)
        return float(math.sqrt(mean_sq))

    def update(self, pcm_bytes: bytes) -> FrameMetrics:
        """Memperbarui noise floor adaptif dan mengembalikan metrik frame terkini."""
        rms = self.compute_rms_int16(pcm_bytes)
        safe_floor = max(self.noise_floor, self.min_noise_floor)
        snr_db = 20.0 * math.log10(max(rms, 1e-6) / safe_floor)

        is_speech = (
            rms >= self.min_speech_rms
            and snr_db >= self.speech_snr_threshold_db
        )

        # Noise floor hanya diperbarui saat tidak ada suara ucapan aktif
        if not is_speech:
            updated = (1.0 - self.ema_alpha) * self.noise_floor + self.ema_alpha * rms
            self.noise_floor = max(updated, self.min_noise_floor)

        return FrameMetrics(
            rms=round(rms, 5),
            noise_floor=round(self.noise_floor, 5),
            snr_db=round(snr_db, 2),
            is_speech=is_speech,
        )

    @staticmethod
    def snr_to_quality(snr_db: float, low_db: float = 3.0, high_db: float = 20.0) -> float:
        """Memetakan SNR (dB) ke faktor kualitas [0.0, 1.0]."""
        if high_db <= low_db:
            return 1.0
        ratio = (snr_db - low_db) / (high_db - low_db)
        return max(0.0, min(1.0, ratio))


class EnergyUtteranceSegmenter:
    """Segmentasi ujaran berbasis energi (VAD) untuk mesin pengenal non-streaming."""

    def __init__(
        self,
        sample_rate: int = 16000,
        min_speech_seconds: float = 0.25,
        hangover_seconds: float = 0.45,
        max_utterance_seconds: float = 3.5,
        pre_roll_frames: int = 4,
    ) -> None:
        self.sample_rate = sample_rate
        self.min_speech_bytes = int(sample_rate * min_speech_seconds) * 2
        self.hangover_samples = int(sample_rate * hangover_seconds)
        self.max_utterance_bytes = int(sample_rate * max_utterance_seconds) * 2
        self.pre_roll_frames = pre_roll_frames

        self._pre_roll: list[bytes] = []
        self._buffer = bytearray()
        self._in_speech = False
        self._silence_samples = 0
        self._peak_snr_db = -60.0
        self._peak_rms = 0.0

    def push(self, pcm_bytes: bytes, metrics: FrameMetrics) -> Optional[tuple[bytes, float, float]]:
        """Memasukkan satu frame PCM.

        Mengembalikan (audio_bytes, peak_rms, peak_snr_db) saat satu segmen ujaran selesai.
        """
        frame_samples = len(pcm_bytes) // 2

        if not self._in_speech:
            self._pre_roll.append(pcm_bytes)
            if len(self._pre_roll) > self.pre_roll_frames:
                self._pre_roll.pop(0)

            if metrics.is_speech:
                self._in_speech = True
                self._silence_samples = 0
                self._buffer.clear()
                for pre in self._pre_roll:
                    self._buffer.extend(pre)
                self._buffer.extend(pcm_bytes)
                self._peak_rms = metrics.rms
                self._peak_snr_db = metrics.snr_db
            return None

        self._buffer.extend(pcm_bytes)
        self._peak_rms = max(self._peak_rms, metrics.rms)
        self._peak_snr_db = max(self._peak_snr_db, metrics.snr_db)

        if metrics.is_speech:
            self._silence_samples = 0
        else:
            self._silence_samples += frame_samples

        ended_by_silence = self._silence_samples >= self.hangover_samples
        ended_by_max_len = len(self._buffer) >= self.max_utterance_bytes

        if ended_by_silence or ended_by_max_len:
            audio = bytes(self._buffer)
            peak_rms = self._peak_rms
            peak_snr = self._peak_snr_db
            self._reset()
            if len(audio) >= self.min_speech_bytes:
                return audio, peak_rms, peak_snr

        return None

    def _reset(self) -> None:
        self._in_speech = False
        self._silence_samples = 0
        self._buffer.clear()
        self._pre_roll.clear()
        self._peak_rms = 0.0
        self._peak_snr_db = -60.0
