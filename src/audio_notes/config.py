"""Runtime configuration: defaults overridable by environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    model: str = "base.en"  # faster-whisper model name
    device: str = "cpu"  # MVP: CPU only
    compute_type: str = "int8"
    web_port: int = 8765
    # Latency knobs: a segment is sent to ASR after this much trailing silence, or is
    # force-cut after vad_max_s of continuous speech. Lower = text appears sooner.
    vad_silence_ms: int = 400
    vad_max_s: float = 10.0

    @classmethod
    def from_env(cls) -> "Config":
        d = cls()
        return cls(
            model=os.environ.get("AUDIO_NOTES_MODEL", d.model),
            device=os.environ.get("AUDIO_NOTES_DEVICE", d.device),
            compute_type=os.environ.get("AUDIO_NOTES_COMPUTE_TYPE", d.compute_type),
            web_port=int(os.environ.get("AUDIO_NOTES_WEB_PORT", d.web_port)),
            vad_silence_ms=int(os.environ.get("AUDIO_NOTES_VAD_SILENCE_MS", d.vad_silence_ms)),
            vad_max_s=float(os.environ.get("AUDIO_NOTES_VAD_MAX_S", d.vad_max_s)),
        )
