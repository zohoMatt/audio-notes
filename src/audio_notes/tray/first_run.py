"""One-time legal notice (REQUIREMENTS F17). Acknowledgement is a flag file in the data dir."""

from __future__ import annotations

import sys
from typing import Callable

from audio_notes import paths

TITLE = "audio-notes"
NOTICE = (
    "audio-notes records system audio and your microphone and transcribes it on this computer.\n\n"
    "Recording other people's voices may require their consent under local law. Before recording "
    "a meeting or call, make sure this is lawful where you are and tell the participants.\n\n"
    "Do you understand and want to continue?"
)

# A dialog takes (title, message) and returns True when the user accepts.
Dialog = Callable[[str, str], bool]


def flag_path():
    return paths.data_dir() / "first_run_ack"


def is_acknowledged() -> bool:
    return flag_path().is_file()


def native_confirm(title: str, message: str) -> bool:
    """Native Yes/No message box (Windows). Anything but Yes counts as declined."""
    if sys.platform != "win32":
        return False
    import ctypes

    MB_YESNO, MB_ICONWARNING, MB_TOPMOST = 0x4, 0x30, 0x40000
    IDYES = 6
    return ctypes.windll.user32.MessageBoxW(None, message, title, MB_YESNO | MB_ICONWARNING | MB_TOPMOST) == IDYES


def ensure_acknowledged(dialog: Dialog = native_confirm) -> bool:
    """True when the user has accepted (now or earlier). On False the app must not record."""
    if is_acknowledged():
        return True
    if not dialog(TITLE, NOTICE):
        return False
    p = flag_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("acknowledged\n", encoding="utf-8")
    return True
