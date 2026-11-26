"""Pemancar paket JSON melalui UDP untuk komunikasi antar-lapis."""

from __future__ import annotations

import json
import socket
import time
from typing import Dict, Any


class UdpSignalEmitter:
    """Mengirimkan paket tafsir dan detak jantung (heartbeat) ke lapis pemakai."""

    def __init__(self, host: str = "127.0.0.1", port: int = 5055) -> None:
        self.target = (host, port)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._seq = 0

    def emit_packet(
        self,
        token: str,
        utterance: str,
        confidence: float,
        margin: float,
        signal_level: float,
        signal_to_noise_db: float,
        is_active: bool,
        heartbeat: bool,
    ) -> Dict[str, Any]:
        """Membentuk dan mengirim satu paket kontrak data JSON."""
        self._seq += 1
        payload: Dict[str, Any] = {
            "seq": self._seq,
            "timestamp": round(time.time(), 3),
            "token": token,
            "utterance": utterance,
            "confidence": round(float(confidence), 4),
            "margin": round(float(margin), 4),
            "signal_level": round(float(signal_level), 5),
            "signal_to_noise_db": round(float(signal_to_noise_db), 2),
            "is_active": bool(is_active),
            "heartbeat": bool(heartbeat),
        }
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._sock.sendto(raw, self.target)
        return payload

    def emit_heartbeat(self, signal_level: float, snr_db: float, is_active: bool) -> Dict[str, Any]:
        """Mengirim status hidup berkala tanpa memicu perintah baru."""
        return self.emit_packet(
            token="NONE",
            utterance="",
            confidence=0.0,
            margin=0.0,
            signal_level=signal_level,
            signal_to_noise_db=snr_db,
            is_active=is_active,
            heartbeat=True,
        )

    def close(self) -> None:
        self._sock.close()
