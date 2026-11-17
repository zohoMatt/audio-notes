"""The macOS menu bar menu as plain data (docs/MACOS.md section 2.2), so its logic is testable on
any platform. `mac_statusbar.py` turns the entries into an NSMenu each time it opens.

Mac conventions: title case, an ellipsis on items that open a dialog or another app, a grey
status line on top, "Quit Audio Notes" with Cmd+Q. There is deliberately no "Open at Login" item:
Audio Notes only runs when the user starts it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from audio_notes.capture.mac_tap import (
    MICROPHONE_PERMISSION_HINT,
    SYSTEM_AUDIO_PERMISSION_HINT,
    Permissions,
)
from audio_notes.tray.state import TrayState, TrayView

SETTINGS_SYSTEM_AUDIO_URL = "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
SETTINGS_MICROPHONE_URL = "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"
RELEASES_URL = "https://github.com/zohoMatt/audio-notes/releases"
MAX_STATUS = 70


@dataclass(frozen=True)
class MenuEntry:
    title: str = ""
    action: Callable[[], None] | None = None  # None: a disabled, informational line
    enabled: bool = True
    checked: bool = False
    separator: bool = False
    key: str = ""  # key equivalent (with Cmd)
    symbol: str = ""  # optional SF Symbol name for the item image


SEPARATOR = MenuEntry(separator=True)

_TOGGLE_TITLES = {
    "Start recording": "Start Recording",
    "Pause recording": "Pause Recording",
    "Continue recording": "Continue Recording",
}


def status_line(view: TrayView, error: str | None) -> str:
    if view.state is TrayState.ERROR:
        text = error or "unknown error"
        text = text if len(text) <= MAX_STATUS else text[: MAX_STATUS - 1] + "…"
        return f"⚠ {text}"
    return {
        TrayState.IDLE: "Not Recording",
        TrayState.RECORDING: "● Recording",
        TrayState.PAUSED: "Paused",
        TrayState.DOWNLOADING: "Downloading Speech Model…",
    }[view.state]


def missing_permissions(error: str | None, perms: Permissions | None, mic_on: bool) -> tuple[bool, bool]:
    """(system audio, microphone): which "Allow ..." items to show. A permission counts as missing
    when the helper's TCC check says denied, or when the last capture error says so."""
    err = error or ""
    system_audio = SYSTEM_AUDIO_PERMISSION_HINT in err or bool(perms and perms.system_audio_denied)
    microphone = mic_on and (MICROPHONE_PERMISSION_HINT in err or bool(perms and perms.microphone_denied))
    return system_audio, microphone


@dataclass(frozen=True)
class MenuActions:
    toggle_recording: Callable[[], None]
    stop_recording: Callable[[], None]
    toggle_mic: Callable[[], None]
    open_panel: Callable[[], None]
    open_transcripts: Callable[[], None]
    connect_to_claude: Callable[[], None]
    open_url: Callable[[str], object]
    check_for_updates: Callable[[], None]
    about: Callable[[], None]
    quit: Callable[[], None]


def build_menu(view: TrayView, *, mic_on: bool, error: str | None, perms: Permissions | None,
               actions: MenuActions) -> list[MenuEntry]:
    toggle_symbol = {"Start recording": "record.circle", "Pause recording": "pause.circle",
                     "Continue recording": "record.circle"}.get(view.toggle_label, "")
    items: list[MenuEntry] = [
        MenuEntry(status_line(view, error)),
        SEPARATOR,
        MenuEntry(_TOGGLE_TITLES.get(view.toggle_label, view.toggle_label), actions.toggle_recording,
                  enabled=view.toggle_enabled, symbol=toggle_symbol),
    ]
    if view.stop_visible:
        items.append(MenuEntry("Stop Recording", actions.stop_recording, symbol="stop.circle"))
    # Disabled while a session is open, like Windows: the microphone is chosen per session.
    items.append(MenuEntry("Include Microphone", actions.toggle_mic, enabled=view.mic_enabled, checked=mic_on))
    items += [
        SEPARATOR,
        MenuEntry("Open Panel…", actions.open_panel, symbol="macwindow"),
        MenuEntry("Show Transcripts in Finder", actions.open_transcripts, symbol="folder"),
        MenuEntry("Connect to Claude…", actions.connect_to_claude, symbol="link"),
    ]
    need_system_audio, need_mic = missing_permissions(error, perms, mic_on)
    if need_system_audio or need_mic:
        items.append(SEPARATOR)
        if need_system_audio:
            items.append(MenuEntry("⚠ Allow System Audio Recording…",
                                   lambda: actions.open_url(SETTINGS_SYSTEM_AUDIO_URL)))
        if need_mic:
            items.append(MenuEntry("⚠ Allow Microphone Access…",
                                   lambda: actions.open_url(SETTINGS_MICROPHONE_URL)))
    items += [
        SEPARATOR,
        MenuEntry("Check for Updates…", actions.check_for_updates),
        MenuEntry("About Audio Notes", actions.about),
        MenuEntry("Quit Audio Notes", actions.quit, key="q"),
    ]
    return items


def updates_message(version: str) -> str:
    return (f"You have Audio Notes {version}.\n\nInstalled with uv, it updates from Terminal:\n\n"
            "    uv tool upgrade audio-notes\n\nThen quit and start it again. Open the releases page "
            "to see what is new?")


def about_message(version: str) -> str:
    return (f"Version {version}\n\nCaptures system audio and your microphone, transcribes locally "
            "with faster-whisper and shares the transcript with Claude over MCP. Nothing leaves this Mac.")
