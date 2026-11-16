"""Filesystem locations. Tests redirect everything via AUDIO_NOTES_DATA_DIR."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("AUDIO_NOTES_DATA_DIR")
    if override:
        return Path(override)
    base = os.environ.get("APPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "audio-notes"


def sessions_dir() -> Path:
    return data_dir() / "sessions"


def status_path() -> Path:
    return data_dir() / "status.json"


def session_path_for(now: datetime) -> Path:
    """JSONL path for a session starting at `now`; the file stem is the session id."""
    return sessions_dir() / f"{now:%Y-%m-%d_%H-%M-%S}.jsonl"
