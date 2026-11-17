"""Filesystem locations. Tests redirect everything via AUDIO_NOTES_DATA_DIR.

Where transcripts live:
1. `AUDIO_NOTES_DATA_DIR`, when set (tests, advanced use).
2. macOS (any install): `~/Library/Application Support/Audio Notes`. Never inside an .app bundle,
   which would break its signature and be lost on update.
3. Windows packaged build (PyInstaller): a `data` folder next to the program. Every process of one
   install (tray, CLI, MCP server) then agrees on the location without any setup. This also
   avoids the per-app AppData redirection of Microsoft Store apps (such as Claude Desktop),
   which would otherwise give the MCP server a different %APPDATA% than the tray.
4. Otherwise (pip / uv / source tree): `%APPDATA%\\audio-notes` (`~/.local/share/audio-notes`
   where there is no %APPDATA%).

Logs go to the data dir, except on macOS: `~/Library/Logs/Audio Notes` (Console.app finds them).
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path


MAC_APP_NAME = "Audio Notes"  # folder name under ~/Library/Application Support and ~/Library/Logs


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
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / MAC_APP_NAME
    app = app_dir()
    if app is not None and _can_create(app / "data"):
        return app / "data"
    base = os.environ.get("APPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "audio-notes"


def log_dir() -> Path:
    if sys.platform == "darwin" and not os.environ.get("AUDIO_NOTES_DATA_DIR"):
        return Path.home() / "Library" / "Logs" / MAC_APP_NAME
    return data_dir()


def sessions_dir() -> Path:
    return data_dir() / "sessions"


def status_path() -> Path:
    return data_dir() / "status.json"


SESSION_STAMP = "%Y-%m-%d_%H-%M-%S"
_STAMP_LEN = 19  # len("2026-11-16_14-30-00")


def session_path_for(now: datetime, n: int = 1) -> Path:
    """JSONL path for a session starting at `now`; the file stem is the session id.

    `n` > 1 gives the n-th session started within the same second ("..._14-30-00-2"), so a quick
    stop/start never reopens (and corrupts) the previous file."""
    stem = f"{now:{SESSION_STAMP}}" + (f"-{n}" if n > 1 else "")
    return sessions_dir() / f"{stem}.jsonl"


def session_sort_key(session_id: str) -> tuple[str, int, str]:
    """Chronological order of session ids, including same-second suffixes ("-2" < "-10")."""
    stamp, rest = session_id[:_STAMP_LEN], session_id[_STAMP_LEN:]
    n = int(rest[1:]) if rest[:1] == "-" and rest[1:].isdigit() else (1 if not rest else 0)
    return (stamp, n, rest)


def session_started_at(session_id: str) -> datetime | None:
    try:
        return datetime.strptime(session_id[:_STAMP_LEN], SESSION_STAMP)
    except ValueError:
        return None


def is_valid_session_id(session_id: str) -> bool:
    """Rejects ids that would escape the sessions folder (they come from URLs and tool calls)."""
    return bool(session_id) and not any(c in session_id for c in '/\\:') and ".." not in session_id
