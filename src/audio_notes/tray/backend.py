"""The seam between `TrayApp` (actions and state, platform-neutral) and the native shell that shows
it: pystray in the Windows notification area, an NSStatusItem in the macOS menu bar."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Callable, Protocol

if TYPE_CHECKING:
    from audio_notes.tray.app import TrayApp
    from audio_notes.tray.state import TrayView


class TrayBackend(Protocol):
    def run(self, app: "TrayApp", on_ready: Callable[[], None]) -> None:
        """Show the icon and block in the UI loop on the main thread until `stop()`. Call
        `on_ready` once the icon is up (TrayApp then starts polling the recorder)."""

    def update(self, view: "TrayView", mic_on: bool) -> None:
        """New state: redraw icon / tooltip / menu. Called from any thread, only on changes."""

    def notify(self, message: str, title: str) -> None:
        """Best-effort user notification. May raise; TrayApp then logs the message instead."""

    def stop(self) -> None:
        """Leave the UI loop (from any thread)."""

    def refresh_key(self) -> object:
        """Extra state that should trigger `update()` when it changes (e.g. the menu bar's light /
        dark appearance), or None."""


def default_backend() -> TrayBackend:
    if sys.platform == "darwin":
        from audio_notes.tray.mac_statusbar import MacStatusBarBackend

        return MacStatusBarBackend()
    from audio_notes.tray.pystray_backend import PystrayBackend

    return PystrayBackend()
