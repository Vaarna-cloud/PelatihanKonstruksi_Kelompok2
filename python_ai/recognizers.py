"""Mesin pengenal suara lokal (Vosk, faster-whisper, dan simulator uji)."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from audio_features import AdaptiveSignalMeter, EnergyUtteranceSegmenter, FrameMetrics


@dataclass(frozen=True)
class RecognitionResult:
    """Hasil tafsir akustik beserta ukuran kelayakan yang dihitung dari data."""

    token: str
    utterance: str
    confidence: float
    margin: float
    signal_level: float
    signal_to_noise_db: float
    is_active: bool


class CommandVocabMatcher:
    """Memetakan teks transkripsi ke token perintah netral beserta margin kemiripan."""

    def __init__(self, config_path: Path) -> None:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        self.tokens: Dict[str, List[str]] = {}
        self.alias_to_token: Dict[str, str] = {}

        for token, entry in raw["tokens"].items():
            aliases = [a.strip().lower() for a in entry["aliases"] if a.strip()]
            self.tokens[token] = aliases
            for alias in aliases:
                self.alias_to_token[alias] = token

    def grammar_words(self) -> List[str]:
        """Mengembalikan daftar kata terbatas untuk grammar Vosk."""
        words = sorted(self.alias_to_token.keys())
        words.append("[unk]")
        return words

    def initial_prompt(self) -> str:
        """Mengembalikan daftar kata acuan untuk decoder Whisper."""
        return ", ".join(sorted(self.alias_to_token.keys()))

    def match(self, text: str) -> Tuple[str, float, float]:
        """Mencocokkan teks ke token terbaik.

        Mengembalikan (token, best_similarity, margin_ke_peringkat_kedua).
        """
        cleaned = " ".join(text.lower().strip().split())
        if not cleaned or cleaned == "[unk]":
            return "UNKNOWN", 0.0, 0.0

        # Cek kecocokan persis per kata terlebih dahulu
        words = [w for w in cleaned.split() if w != "[unk]"]
        for word in words:
            if word in self.alias_to_token:
                best_token = self.alias_to_token[word]
                second_score = self._best_other_similarity(word, best_token)
                margin = max(0.0, round(1.0 - second_score, 4))
                return best_token, 1.0, margin

        # Jika tidak persis sama, hitung kemiripan teks per token
        token_scores: List[Tuple[str, float]] = []
        for token, aliases in self.tokens.items():
            best_alias_score = max(
                SequenceMatcher(None, cleaned, alias).ratio()
                for alias in aliases
            )
            token_scores.append((token, best_alias_score))

        token_scores.sort(key=lambda item: item[1], reverse=True)
        if not token_scores:
            return "UNKNOWN", 0.0, 0.0

        best_token, best_score = token_scores[0]
        second_score = token_scores[1][1] if len(token_scores) > 1 else 0.0
        margin = max(0.0, round(best_score - second_score, 4))

        if best_score < 0.65:
            return "UNKNOWN", round(best_score, 4), margin
        return best_token, round(best_score, 4), margin

    def _best_other_similarity(self, word: str, excluded_token: str) -> float:
        best = 0.0
        for token, aliases in self.tokens.items():
            if token == excluded_token:
                continue
            for alias in aliases:
                ratio = SequenceMatcher(None, word, alias).ratio()
                if ratio > best:
                    best = ratio
        return best


class BaseRecognizerEngine:
    """Antarmuka dasar mesin pengenal suara."""

    def process_frame(
        self, pcm_bytes: bytes, metrics: FrameMetrics
    ) -> Optional[RecognitionResult]:
        raise NotImplementedError


class VoskRecognizerEngine(BaseRecognizerEngine):
    """Mesin pengenal berbasis Vosk lokal dengan grammar terbatas dan word confidence."""

    def __init__(
        self,
        model_path: Path,
        matcher: CommandVocabMatcher,
        sample_rate: int = 16000,
    ) -> None:
        from vosk import KaldiRecognizer, Model, SetLogLevel

        SetLogLevel(-1)
        if not model_path.exists():
            raise FileNotFoundError(
                f"Folder model Vosk tidak ditemukan di: {model_path}"
            )

        self.matcher = matcher
        self.model = Model(str(model_path))
        grammar_json = json.dumps(matcher.grammar_words())
        self.recognizer = KaldiRecognizer(self.model, sample_rate, grammar_json)
        self.recognizer.SetWords(True)
        self._peak_rms = 0.0
        self._peak_snr = -60.0

    def process_frame(
        self, pcm_bytes: bytes, metrics: FrameMetrics
    ) -> Optional[RecognitionResult]:
        if metrics.is_speech:
            self._peak_rms = max(self._peak_rms, metrics.rms)
            self._peak_snr = max(self._peak_snr, metrics.snr_db)

        if not self.recognizer.AcceptWaveform(pcm_bytes):
            return None

        payload = json.loads(self.recognizer.Result())
        raw_text = payload.get("text", "").strip()
        word_entries = payload.get("result", [])

        peak_rms = max(self._peak_rms, metrics.rms)
        peak_snr = max(self._peak_snr, metrics.snr_db)
        self._peak_rms = 0.0
        self._peak_snr = -60.0

        if not raw_text:
            return None

        token, text_sim, margin = self.matcher.match(raw_text)

        # Ambil rata-rata word confidence asli dari decoder Vosk untuk kata non-[unk]
        valid_confs = [
            float(item.get("conf", 0.0))
            for item in word_entries
            if item.get("word") and item.get("word") != "[unk]"
        ]

        if token == "UNKNOWN" or not valid_confs:
            return RecognitionResult(
                token="UNKNOWN",
                utterance=raw_text,
                confidence=round(0.25 * text_sim, 4),
                margin=0.0,
                signal_level=round(peak_rms, 5),
                signal_to_noise_db=round(peak_snr, 2),
                is_active=True,
            )

        acoustic_conf = sum(valid_confs) / len(valid_confs)
        snr_quality = AdaptiveSignalMeter.snr_to_quality(peak_snr)
        composite_conf = acoustic_conf * text_sim * (0.75 + 0.25 * snr_quality)
        composite_conf = max(0.0, min(1.0, composite_conf))

        return RecognitionResult(
            token=token,
            utterance=raw_text,
            confidence=round(composite_conf, 4),
            margin=round(margin, 4),
            signal_level=round(peak_rms, 5),
            signal_to_noise_db=round(peak_snr, 2),
            is_active=True,
        )


class WhisperRecognizerEngine(BaseRecognizerEngine):
    """Mesin pengenal berbasis faster-whisper lokal dengan segmentasi VAD."""

    def __init__(
        self,
        model_size: str,
        matcher: CommandVocabMatcher,
        sample_rate: int = 16000,
        device: str = "cpu",
        compute_type: str = "int8",
    ) -> None:
        from faster_whisper import WhisperModel

        self.matcher = matcher
        self.sample_rate = sample_rate
        self.segmenter = EnergyUtteranceSegmenter(sample_rate=sample_rate)
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def process_frame(
        self, pcm_bytes: bytes, metrics: FrameMetrics
    ) -> Optional[RecognitionResult]:
        utterance = self.segmenter.push(pcm_bytes, metrics)
        if utterance is None:
            return None

        audio_bytes, peak_rms, peak_snr = utterance
        import numpy as np

        audio_np = (
            np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        )

        segments, _ = self.model.transcribe(
            audio_np,
            language="id",
            beam_size=2,
            best_of=1,
            temperature=0.0,
            condition_on_previous_text=False,
            initial_prompt=self.matcher.initial_prompt(),
            vad_filter=False,
        )

        seg_list = list(segments)
        if not seg_list:
            return None

        text = " ".join(seg.text.strip() for seg in seg_list).strip()
        if not text:
            return None

        # Hitung probabilitas ucapan asli dari keluaran segmen Whisper
        avg_logprob = sum(seg.avg_logprob for seg in seg_list) / len(seg_list)
        no_speech_prob = max(seg.no_speech_prob for seg in seg_list)

        decoder_prob = math.exp(max(avg_logprob, -5.0))
        decoder_prob = max(0.0, min(1.0, decoder_prob))
        speech_likelihood = max(0.0, min(1.0, 1.0 - no_speech_prob))

        token, text_sim, margin = self.matcher.match(text)
        snr_quality = AdaptiveSignalMeter.snr_to_quality(peak_snr)

        if token == "UNKNOWN":
            conf = round(0.3 * decoder_prob * speech_likelihood, 4)
        else:
            conf = (
                decoder_prob
                * speech_likelihood
                * text_sim
                * (0.75 + 0.25 * snr_quality)
            )
            conf = round(max(0.0, min(1.0, conf)), 4)

        return RecognitionResult(
            token=token,
            utterance=text,
            confidence=conf,
            margin=round(margin, 4),
            signal_level=round(peak_rms, 5),
            signal_to_noise_db=round(peak_snr, 2),
            is_active=True,
        )


class MockRecognizerEngine:
    """Simulator input terminal untuk menguji jembatan dan ambang tanpa mikrofon."""

    def __init__(self, matcher: CommandVocabMatcher) -> None:
        self.matcher = matcher

    def evaluate_manual_input(self, line: str) -> Optional[RecognitionResult]:
        """Memparsing input teks seperti: 'angkat 0.88' atau 'turun 0.45 4.0'."""
        parts = line.strip().split()
        if not parts:
            return None

        raw_text = parts[0].lower()
        # Mendukung shortcut angka 1..5
        shortcut_map = {
            "1": "CMD_1",
            "2": "CMD_2",
            "3": "CMD_3",
            "4": "CMD_4",
            "5": "CMD_5",
        }

        if raw_text in shortcut_map:
            token = shortcut_map[raw_text]
            utterance = self.matcher.tokens[token][0]
            margin = 0.85
        else:
            token, text_sim, margin = self.matcher.match(raw_text)
            utterance = raw_text
            if token == "UNKNOWN" and len(parts) < 2:
                return RecognitionResult(
                    token="UNKNOWN",
                    utterance=utterance,
                    confidence=round(0.25 * text_sim, 4),
                    margin=round(margin, 4),
                    signal_level=0.04,
                    signal_to_noise_db=5.0,
                    is_active=True,
                )

        confidence = float(parts[1]) if len(parts) >= 2 else 0.88
        snr_db = float(parts[2]) if len(parts) >= 3 else 16.0
        confidence = max(0.0, min(1.0, confidence))

        return RecognitionResult(
            token=token,
            utterance=utterance,
            confidence=round(confidence, 4),
            margin=round(margin, 4),
            signal_level=0.09 if snr_db >= 6.0 else 0.02,
            signal_to_noise_db=round(snr_db, 2),
            is_active=True,
        )
