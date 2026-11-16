"""Filesystem locations. Tests redirect everything via AUDIO_NOTES_DATA_DIR.

Where transcripts live:
1. `AUDIO_NOTES_DATA_DIR`, when set (tests, advanced use).
2. Packaged build (PyInstaller): a `data` folder next to the program. Every process of one
   install (tray, CLI, MCP server) then agrees on the location without any setup. This also
   avoids the per-app AppData redirection of Microsoft Store apps (such as Claude Desktop),
   which would otherwise give the MCP server a different %APPDATA% than the tray.
3. Otherwise (pip / uv / source tree): `%APPDATA%\\audio-notes`.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path


def app_dir() -> Path | None:
    """Folder of the installed program when running as a packaged build, else None."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return None


def _can_create(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        return True
    except OSError:
        return False


def data_dir() -> Path:
    override = os.environ.get("AUDIO_NOTES_DATA_DIR")
    if override:
        return Path(override)
    app = app_dir()
    if app is not None and _can_create(app / "data"):
        return app / "data"
    base = os.environ.get("APPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "audio-notes"


def sessions_dir() -> Path:
    return data_dir() / "sessions"


def status_path() -> Path:
    return data_dir() / "status.json"


def session_path_for(now: datetime) -> Path:
    """JSONL path for a session starting at `now`; the file stem is the session id."""
    return sessions_dir() / f"{now:%Y-%m-%d_%H-%M-%S}.jsonl"
