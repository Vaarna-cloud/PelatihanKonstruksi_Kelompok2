"""Titik masuk utama lapis penghasil data suara (Python 3.12)."""

from __future__ import annotations

import argparse
import queue
import threading
import time
from pathlib import Path
from typing import Optional

from audio_features import AdaptiveSignalMeter
from recognizers import (
    BaseRecognizerEngine,
    CommandVocabMatcher,
    MockRecognizerEngine,
    RecognitionResult,
    VoskRecognizerEngine,
    WhisperRecognizerEngine,
)
from udp_emitter import UdpSignalEmitter

DEFAULT_CONFIG = Path(__file__).resolve().parent / "vocab_config.json"
DEFAULT_VOSK_MODEL = (
    Path(__file__).resolve().parent / "models" / "vosk-model-small-en-us-0.15"
)


def build_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Lapis penghasil data perintah suara lokal (Vosk / faster-whisper / Mock)."
    )
    parser.add_argument(
        "--engine",
        choices=["vosk", "whisper", "mock"],
        default="vosk",
        help="Mesin pengenal suara yang dipakai (default: vosk).",
    )
    parser.add_argument(
        "--model-path",
        type=Path,
        default=DEFAULT_VOSK_MODEL,
        help="Lokasi folder model Vosk lokal (khusus --engine vosk).",
    )
    parser.add_argument(
        "--whisper-size",
        default="tiny",
        help="Ukuran model faster-whisper lokal: tiny, base, small (default: tiny).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="Berkas JSON pemetaan kosakata ke token netral.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Alamat tujuan UDP.")
    parser.add_argument("--port", type=int, default=5055, help="Port tujuan UDP.")
    parser.add_argument(
        "--device",
        type=int,
        default=None,
        help="Indeks perangkat audio input (opsional).",
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=16000,
        help="Frekuensi sampling audio Hz (default: 16000).",
    )
    return parser.parse_args()


def _emit_recognition(emitter: UdpSignalEmitter, res: RecognitionResult) -> None:
    payload = emitter.emit_packet(
        token=res.token,
        utterance=res.utterance,
        confidence=res.confidence,
        margin=res.margin,
        signal_level=res.signal_level,
        signal_to_noise_db=res.signal_to_noise_db,
        is_active=res.is_active,
        heartbeat=False,
    )
    print(
        f"[KIRIM] token={payload['token']} teks='{payload['utterance']}' "
        f"conf={payload['confidence']:.3f} margin={payload['margin']:.3f} "
        f"snr={payload['signal_to_noise_db']:.1f}dB"
    )


def run_mock_loop(
    matcher: CommandVocabMatcher, emitter: UdpSignalEmitter
) -> None:
    mock_engine = MockRecognizerEngine(matcher)
    stop_event = threading.Event()

    def heartbeat_worker() -> None:
        while not stop_event.is_set():
            emitter.emit_heartbeat(signal_level=0.005, snr_db=0.0, is_active=False)
            time.sleep(0.5)

    hb_thread = threading.Thread(target=heartbeat_worker, daemon=True)
    hb_thread.start()

    print("Mode MOCK aktif. Ketik perintah + opsional [confidence] [snr_db].")
    print("Contoh: '1', '1 0.90', '2 0.48', '4', atau 'exit' untuk keluar.")
    try:
        while True:
            line = input("> ").strip()
            if line.lower() in {"exit", "quit"}:
                break
            res = mock_engine.evaluate_manual_input(line)
            if res is not None:
                _emit_recognition(emitter, res)
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        stop_event.set()
        hb_thread.join(timeout=1.0)


def run_audio_loop(
    engine: BaseRecognizerEngine,
    emitter: UdpSignalEmitter,
    sample_rate: int,
    device: Optional[int],
) -> None:
    import sounddevice as sd

    try:
        sd.query_devices(device, kind="input")
    except sd.PortAudioError as exc:
        print(
            "\n[Galat Audio] Perangkat input suara tidak ditemukan atau belum aktif.\n"
            f"Detail: {exc}\n"
            "Solusi:\n"
            "  1. Pastikan perangkat input suara terpasang dan aktif.\n"
            "  2. Jika memakai WSL2 Linux, pasang jembatan audio: sudo apt install libasound2-plugins -y\n"
            "  3. Atau jalankan Python langsung di Windows, atau uji tanpa perangkat input dengan: python main.py --engine mock"
        )
        return

    audio_queue: "queue.Queue[bytes]" = queue.Queue()
    meter = AdaptiveSignalMeter()
    block_size = int(sample_rate * 0.1)  # 100 ms per blok

    def audio_callback(indata, frames, time_info, status) -> None:
        if status:
            print(f"[Audio] Status: {status}")
        audio_queue.put(bytes(indata))

    last_heartbeat = 0.0
    print(f"Mendengarkan input suara pada {sample_rate} Hz -> UDP {emitter.target[0]}:{emitter.target[1]}")
    print("Tekan Ctrl+C untuk berhenti.")

    with sd.RawInputStream(
        samplerate=sample_rate,
        blocksize=block_size,
        device=device,
        dtype="int16",
        channels=1,
        callback=audio_callback,
    ):
        try:
            while True:
                try:
                    pcm_bytes = audio_queue.get(timeout=0.5)
                except queue.Empty:
                    emitter.emit_heartbeat(0.0, -60.0, False)
                    continue

                metrics = meter.update(pcm_bytes)
                result = engine.process_frame(pcm_bytes, metrics)
                if result is not None:
                    _emit_recognition(emitter, result)
                    last_heartbeat = time.monotonic()
                elif time.monotonic() - last_heartbeat >= 0.5:
                    emitter.emit_heartbeat(
                        signal_level=metrics.rms,
                        snr_db=metrics.snr_db,
                        is_active=metrics.is_speech,
                    )
                    last_heartbeat = time.monotonic()
        except KeyboardInterrupt:
            print("\nLapis penghasil data dihentikan.")


def main() -> None:
    args = build_args()
    matcher = CommandVocabMatcher(args.config)
    emitter = UdpSignalEmitter(host=args.host, port=args.port)

    try:
        if args.engine == "mock":
            run_mock_loop(matcher, emitter)
            return

        if args.engine == "vosk":
            engine: BaseRecognizerEngine = VoskRecognizerEngine(
                model_path=args.model_path,
                matcher=matcher,
                sample_rate=args.sample_rate,
            )
        else:
            engine = WhisperRecognizerEngine(
                model_size=args.whisper_size,
                matcher=matcher,
                sample_rate=args.sample_rate,
            )

        run_audio_loop(engine, emitter, args.sample_rate, args.device)
    finally:
        emitter.close()


if __name__ == "__main__":
    main()
