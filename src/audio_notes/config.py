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

    @classmethod
    def from_env(cls) -> "Config":
        d = cls()
        return cls(
            model=os.environ.get("AUDIO_NOTES_MODEL", d.model),
            device=os.environ.get("AUDIO_NOTES_DEVICE", d.device),
            compute_type=os.environ.get("AUDIO_NOTES_COMPUTE_TYPE", d.compute_type),
            web_port=int(os.environ.get("AUDIO_NOTES_WEB_PORT", d.web_port)),
        )
