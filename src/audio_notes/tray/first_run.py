"""One-time legal notice (REQUIREMENTS F17) and, on macOS, the one-time permission explanation.
Acknowledgement is a flag file in the data dir."""

from __future__ import annotations

import logging
import sys
from typing import Callable

from audio_notes import paths

log = logging.getLogger(__name__)

TITLE = "Audio Notes"
NOTICE = (
    "Audio Notes records system audio and your microphone and transcribes it on this computer.\n\n"
    "Recording other people's voices may require their consent under local law. Before recording "
    "a meeting or call, make sure this is lawful where you are and tell the participants.\n\n"
    "Do you understand and want to continue?"
)

PERMISSIONS_TITLE = "Audio Notes needs two permissions"
MAC_PERMISSIONS_NOTICE = (
    "macOS will now ask for:\n\n"
    "• Microphone: to transcribe your side of a conversation.\n"
    "• System Audio Recording: to transcribe what the others say (the sound this Mac plays).\n\n"
    "Because you started Audio Notes from a terminal, the prompts and the entries in System Settings "
    "> Privacy & Security name that terminal app rather than Audio Notes.\n\n"
    "If you deny system audio, recordings stay silent; the menu bar icon then shows a warning and "
    "a shortcut to the right System Settings page. Everything stays on this Mac."
)

# A dialog takes (title, message) and returns True when the user accepts.
Dialog = Callable[[str, str], bool]


def flag_path():
    return paths.data_dir() / "first_run_ack"


def permissions_flag_path():
    return paths.data_dir() / "permissions_explained"


def is_acknowledged() -> bool:
    return flag_path().is_file()


def native_confirm(title: str, message: str) -> bool:
    """Native Yes/No message box (Windows) or NSAlert (macOS). Anything but Yes counts as declined."""
    if sys.platform == "darwin":
        from audio_notes.tray.mac_statusbar import alert

        return alert(title, message, buttons=("Continue", "Cancel"), warning=True) == 0
    if sys.platform != "win32":
        return False
    import ctypes

    MB_YESNO, MB_ICONWARNING, MB_TOPMOST = 0x4, 0x30, 0x40000
    IDYES = 6
    return ctypes.windll.user32.MessageBoxW(None, message, title, MB_YESNO | MB_ICONWARNING | MB_TOPMOST) == IDYES


def _write_flag(p) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("acknowledged\n", encoding="utf-8")


def ensure_acknowledged(dialog: Dialog = native_confirm) -> bool:
    """True when the user has accepted (now or earlier). On False the app must not record."""
    if is_acknowledged():
        return True
    if not dialog(TITLE, NOTICE):
        return False
    _write_flag(flag_path())
    return True


def ensure_permissions_explained(dialog: Dialog, request: Callable[[], object]) -> bool:
    """macOS: once, explain the two permissions, then `request()` them (which shows the system
    prompts). Returns True when the explanation was shown now.

    Asked only once whatever the answer: a user who chooses "Cancel" is not nagged again; the menu
    offers the System Settings shortcut whenever a permission turns out to be missing."""
    p = permissions_flag_path()
    if p.is_file():
        return False
    accepted = dialog(PERMISSIONS_TITLE, MAC_PERMISSIONS_NOTICE)
    _write_flag(p)
    if accepted:
        try:
            request()
        except Exception:  # noqa: BLE001 - the prompts come again on first recording anyway
            log.exception("requesting permissions failed")
    return True
