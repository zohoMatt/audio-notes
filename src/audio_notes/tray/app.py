"""TrayApp: tray / menu bar icon + menu (F16). `run()` blocks and must be called on the main thread.

All menu actions are plain methods with injected side effects, so they are testable without any
GUI toolkit. The native shell is a `TrayBackend` (tray/backend.py): pystray on Windows, an
NSStatusItem on macOS; both are imported lazily inside `run()`.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Callable

from audio_notes import paths
from audio_notes.tray import first_run
from audio_notes.tray.backend import TrayBackend, default_backend
from audio_notes.tray.controller import RecorderController
from audio_notes.tray.state import TrayView, compute_state, describe

log = logging.getLogger(__name__)


def _open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", str(path)], check=False)


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
        claude_running: Callable[[], bool] | None = None,
        on_quit: Callable[[], None] | None = None,
        backend: TrayBackend | None = None,
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
        self._claude_running = claude_running
        self._on_quit = on_quit
        self._backend_choice = backend  # None: the platform default, created in run()
        self._backend: TrayBackend | None = None  # the running shell
        self._stop = threading.Event()
        self._last_view: tuple | None = None

    # ---- state -------------------------------------------------------------
    def view(self) -> TrayView:
        err = self.controller.last_error()
        recording = self.controller.is_recording()
        paused = recording and self.controller.is_paused()
        state = compute_state(recording, err, self.controller.is_downloading_model(), paused)
        return describe(state, err, recording, paused)

    def refresh(self) -> None:
        """Re-read the controller; update icon, tooltip and menu when something changed."""
        v = self.view()
        backend = self._backend
        mic = self.controller.mic_enabled()
        key = (v.state, v.tooltip, mic, backend.refresh_key() if backend is not None else None)
        if key == self._last_view:
            return
        self._last_view = key
        if backend is not None:
            backend.update(v, mic)

    def _notify(self, message: str, title: str = "Audio Notes") -> None:
        if self._backend is not None:
            try:
                self._backend.notify(message, title)
                return
            except Exception:  # notifications are best-effort
                log.exception("notify failed")
        log.info("%s: %s", title, message)

    # ---- actions (menu callbacks) -----------------------------------------
    def toggle_recording(self) -> None:
        """Start when idle, pause while recording, continue while paused."""
        try:
            if not self.controller.is_recording():
                self.controller.start()
            elif self.controller.is_paused():
                self.controller.resume()
            else:
                self.controller.pause()
        except Exception as e:
            log.exception("toggle recording failed")
            self._notify(f"Could not change recording state: {e}")
        self.refresh()

    def stop_recording(self) -> None:
        try:
            self.controller.stop()
        except Exception as e:
            log.exception("stop recording failed")
            self._notify(f"Could not stop recording: {e}")
        self.refresh()

    def toggle_mic(self) -> None:
        if self.controller.is_recording():  # the menu item is disabled then; guard anyway
            return
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
        running = self._claude_running or setup_cli.claude_desktop_running
        how = "Cmd+Q" if sys.platform == "darwin" else "also from the tray"
        question = f"Add the Audio Notes MCP server to the Claude Desktop config?\n\n{path}\n\n"
        tail = " A backup of the existing file is made first. Start Claude Desktop afterwards."
        if not running():
            if not self._confirm("Connect to Claude", f"{question}Quit Claude Desktop completely first "
                                 f"({how}): it rewrites this file when it exits.{tail}"):
                return
        else:
            # Claude Desktop rewrites its config when it exits, which would erase the change: ask
            # again (a modal dialog, not an easily missed notification) until it is gone or Cancel.
            head = (f"Claude Desktop is running. Quit it completely now ({how}), then choose Continue: "
                    "it rewrites its config when it exits, which would undo this change.")
            while running():
                if not self._confirm("Connect to Claude", f"{question}{head}{tail}"):
                    return
                head = (f"Claude Desktop is still running, so nothing was changed. Quit it completely "
                        f"({how}), then choose Continue, or choose Cancel.")
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
        if self._backend is not None:
            self._backend.stop()

    # ---- main loop ---------------------------------------------------------
    def _start_polling(self) -> None:
        def poll() -> None:
            while not self._stop.wait(self._poll_interval):
                try:
                    self.refresh()
                except Exception:
                    log.exception("tray refresh failed")

        threading.Thread(target=poll, name="tray-poll", daemon=True).start()

    def run(self) -> bool:
        """Show the first-run notice if needed, then block in the tray loop.

        Returns False (without creating the icon or touching the recorder) when the user
        declines the notice; True after a normal quit."""
        if not first_run.ensure_acknowledged(self._first_run_dialog):
            return False
        backend = self._backend_choice or default_backend()
        self._backend = backend
        try:
            backend.run(self, self._start_polling)
        finally:
            self._stop.set()
        return True
