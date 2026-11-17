"""pystray shell for `TrayApp` (Windows notification area). pystray is imported lazily in `run()`."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any, Callable

from audio_notes.tray.icons import make_icon

if TYPE_CHECKING:
    from audio_notes.tray.app import TrayApp
    from audio_notes.tray.state import TrayView


class PystrayBackend:
    def __init__(self) -> None:
        self._icon: Any = None

    def _build_menu(self, app: "TrayApp") -> Any:
        import pystray

        def bg(fn: Callable[[], None]) -> Callable:
            # start() may load a model for seconds; never block pystray's UI thread
            return lambda icon, item: threading.Thread(target=fn, daemon=True).start()

        Item = pystray.MenuItem
        return pystray.Menu(
            Item(lambda item: app.view().toggle_label, bg(app.toggle_recording),
                 enabled=lambda item: app.view().toggle_enabled),
            Item("Stop recording", bg(app.stop_recording), visible=lambda item: app.view().stop_visible),
            Item(lambda item: app.view().mic_label, bg(app.toggle_mic),
                 checked=lambda item: app.controller.mic_enabled(),
                 enabled=lambda item: app.view().mic_enabled),
            pystray.Menu.SEPARATOR,
            Item("Open panel", bg(app.open_panel), default=True),
            Item("Open transcripts folder", bg(app.open_transcripts)),
            Item("Connect to Claude", bg(app.connect_to_claude)),
            pystray.Menu.SEPARATOR,
            Item("Quit", bg(app.quit)),
        )

    def run(self, app: "TrayApp", on_ready: Callable[[], None]) -> None:
        import pystray

        v = app.view()
        self._icon = pystray.Icon("audio-notes", make_icon(v.state), v.tooltip, self._build_menu(app))

        def setup(icon: Any) -> None:
            icon.visible = True
            on_ready()

        self._icon.run(setup)

    def update(self, view: "TrayView", mic_on: bool) -> None:
        if self._icon is not None:
            self._icon.icon = make_icon(view.state)
            self._icon.title = view.tooltip
            self._icon.update_menu()

    def notify(self, message: str, title: str) -> None:
        if self._icon is None:
            raise RuntimeError("tray icon not running")
        self._icon.notify(message, title)

    def stop(self) -> None:
        if self._icon is not None:
            self._icon.stop()

    def refresh_key(self) -> object:
        return None
