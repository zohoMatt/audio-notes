"""TrayApp: pystray icon + menu (F16). `run()` blocks and must be called on the main thread.

All menu actions are plain methods with injected side effects, so they are testable without
pystray; pystray itself is imported lazily inside `run()`.
"""

from __future__ import annotations

import logging
import os
import threading
import webbrowser
from pathlib import Path
from typing import Callable

from audio_notes import paths
from audio_notes.tray import first_run
from audio_notes.tray.controller import RecorderController
from audio_notes.tray.icons import make_icon
from audio_notes.tray.state import TrayView, compute_state, describe

log = logging.getLogger(__name__)


def _open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.startfile(path)  # type: ignore[attr-defined]  # Windows only


class TrayApp:
    def __init__(
        self,
        controller: RecorderController,
        panel_url: str | Callable[[], str],
        *,
        poll_interval: float = 1.0,
        first_run_dialog: first_run.Dialog = first_run.native_confirm,
        confirm: first_run.Dialog = first_run.native_confirm,
        open_url: Callable[[str], object] = webbrowser.open,
        open_folder: Callable[[Path], None] = _open_folder,
        merge_config: Callable[[Path], Path | None] | None = None,
        claude_config_path: Callable[[], Path] | None = None,
        on_quit: Callable[[], None] | None = None,
    ) -> None:
        self.controller = controller
        self._panel_url = panel_url
        self._poll_interval = poll_interval
        self._first_run_dialog = first_run_dialog
        self._confirm = confirm
        self._open_url = open_url
        self._open_folder = open_folder
        self._merge_config = merge_config
        self._claude_config_path = claude_config_path
        self._on_quit = on_quit
        self._icon = None  # pystray.Icon once running
        self._stop = threading.Event()
        self._last_view: tuple | None = None

    # ---- state -------------------------------------------------------------
    def view(self) -> TrayView:
        err = self.controller.last_error()
        state = compute_state(self.controller.is_recording(), err, self.controller.is_downloading_model())
        return describe(state, err)

    def refresh(self) -> None:
        """Re-read the controller; update icon, tooltip and menu when something changed."""
        v = self.view()
        key = (v.state, v.tooltip, self.controller.mic_enabled())
        if key == self._last_view:
            return
        self._last_view = key
        if self._icon is not None:
            self._icon.icon = make_icon(v.state)
            self._icon.title = v.tooltip
            self._icon.update_menu()

    def _notify(self, message: str, title: str = "Audio Notes") -> None:
        if self._icon is not None:
            try:
                self._icon.notify(message, title)
                return
            except Exception:  # notifications are best-effort
                log.exception("notify failed")
        log.info("%s: %s", title, message)

    # ---- actions (menu callbacks) -----------------------------------------
    def toggle_recording(self) -> None:
        try:
            if self.controller.is_recording():
                self.controller.stop()
            else:
                self.controller.start()
        except Exception as e:
            log.exception("toggle recording failed")
            self._notify(f"Could not change recording state: {e}")
        self.refresh()

    def toggle_mic(self) -> None:
        self.controller.set_mic_enabled(not self.controller.mic_enabled())
        self.refresh()

    def open_panel(self) -> None:
        url = self._panel_url() if callable(self._panel_url) else self._panel_url
        self._open_url(url)

    def open_transcripts(self) -> None:
        try:
            self._open_folder(paths.sessions_dir())
        except OSError as e:
            self._notify(f"Could not open the transcripts folder: {e}")

    def connect_to_claude(self) -> None:
        from audio_notes.cli import setup as setup_cli

        path = (self._claude_config_path or setup_cli.claude_desktop_config_path)()
        merge = self._merge_config or setup_cli.merge_config
        if not setup_cli.claude_desktop_installed(path):
            self._notify("Claude Desktop does not seem to be installed, so there is nothing to connect.",
                         "Connect to Claude")
            return
        if not self._confirm(
            "Connect to Claude",
            f"Add the Audio Notes MCP server to the Claude Desktop config?\n\n{path}\n\n"
            "Quit Claude Desktop completely first (also from the tray): it rewrites this file when it "
            "exits. A backup of the existing file is made first. Start Claude Desktop afterwards.",
        ):
            return
        try:
            backup = merge(path)
        except (ValueError, OSError, setup_cli.ClaudeNotInstalled) as e:
            self._notify(f"Could not update the Claude config: {e}", "Connect to Claude")
            return
        extra = f" Backup: {backup.name}." if backup else ""
        self._notify(f"Connected.{extra} Restart Claude Desktop to load it.", "Connect to Claude")

    def quit(self) -> None:
        self._stop.set()
        try:
            if self.controller.is_recording():
                self.controller.stop()
        except Exception:
            log.exception("stop on quit failed")
        if self._on_quit:
            self._on_quit()
        if self._icon is not None:
            self._icon.stop()

    # ---- pystray wiring ----------------------------------------------------
    def _build_menu(self):
        import pystray

        def bg(fn: Callable[[], None]) -> Callable:
            # start() may load a model for seconds; never block pystray's UI thread
            return lambda icon, item: threading.Thread(target=fn, daemon=True).start()

        Item = pystray.MenuItem
        return pystray.Menu(
            Item(lambda item: self.view().toggle_label, bg(self.toggle_recording),
                 enabled=lambda item: self.view().toggle_enabled),
            Item("Microphone", bg(self.toggle_mic), checked=lambda item: self.controller.mic_enabled(),
                 enabled=lambda item: self.view().mic_enabled),
            pystray.Menu.SEPARATOR,
            Item("Open panel", bg(self.open_panel), default=True),
            Item("Open transcripts folder", bg(self.open_transcripts)),
            Item("Connect to Claude", bg(self.connect_to_claude)),
            pystray.Menu.SEPARATOR,
            Item("Quit", bg(self.quit)),
        )

    def run(self) -> bool:
        """Show the first-run notice if needed, then block in the tray loop.

        Returns False (without creating the icon or touching the recorder) when the user
        declines the notice; True after a normal quit."""
        if not first_run.ensure_acknowledged(self._first_run_dialog):
            return False
        import pystray

        v = self.view()
        self._icon = pystray.Icon("audio-notes", make_icon(v.state), v.tooltip, self._build_menu())

        def setup(icon) -> None:
            icon.visible = True

            def poll() -> None:
                while not self._stop.wait(self._poll_interval):
                    try:
                        self.refresh()
                    except Exception:
                        log.exception("tray refresh failed")

            threading.Thread(target=poll, name="tray-poll", daemon=True).start()

        self._icon.run(setup)
        self._stop.set()
        return True
