"""`tray`, `record`, `mcp`: the commands that run things. Heavy imports stay inside the bodies."""

from __future__ import annotations

import dataclasses
import logging
import time
from pathlib import Path
from typing import Optional

import typer


def _setup_logging(to_file: bool = False) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if to_file:
        # The packaged tray has no console, so keep a log file next to the data (macOS: ~/Library/Logs).
        from audio_notes import paths

        try:
            paths.log_dir().mkdir(parents=True, exist_ok=True)
            handlers.append(logging.FileHandler(paths.log_dir() / "audio-notes.log", encoding="utf-8"))
        except OSError:
            pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def _sigterm_stops_like_ctrl_c() -> None:
    """Make SIGTERM (`kill`, a service manager, a closing terminal session) end the command the way
    Ctrl+C does, so the `finally` blocks run and pending transcription is finished and written.
    Only the main thread can install handlers; elsewhere (tests calling the command) do nothing."""
    import signal
    import threading

    if threading.current_thread() is not threading.main_thread():
        return

    def _raise(signum, frame):
        raise KeyboardInterrupt

    try:
        signal.signal(signal.SIGTERM, _raise)
    except (ValueError, OSError):
        pass


def _wait_until_interrupted() -> None:
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass


def register(app: typer.Typer) -> None:
    @app.command()
    def mcp() -> None:
        """Run the MCP server over stdio."""
        from audio_notes.mcp_server import main

        main()

    @app.command()
    def tray(
        no_tray: bool = typer.Option(
            False, "--no-tray", help="Run only the web panel (real recorder, no tray icon); Ctrl+C stops."
        ),
    ) -> None:
        """Start the tray icon and the local web panel."""
        _setup_logging(to_file=True)
        from audio_notes.config import Config
        from audio_notes.recorder import Recorder
        from audio_notes.store.reader import StoreReader
        from audio_notes.store.status import StatusPublisher
        from audio_notes.tray.app import TrayApp
        from audio_notes.web.server import PanelServer

        cfg = Config.from_env()
        # Heartbeat for the whole life of the tray, so an idle tray reads as running (panel,
        # `status`, MCP get_status) rather than offline.
        status = StatusPublisher()
        recorder = Recorder(cfg, status=status)
        panel = PanelServer(StoreReader(), cfg.web_port, controller=recorder)
        try:
            panel.start()
        except RuntimeError as e:
            typer.echo(
                f"Cannot start the panel on port {cfg.web_port}: {e}\n"
                "Is audio-notes already running? (set AUDIO_NOTES_WEB_PORT to use another port)",
                err=True,
            )
            raise typer.Exit(1)
        # Only once the panel port is ours: a second instance must not overwrite the first's status.
        status.start()
        try:
            if no_tray:
                # Developer mode: like `record`, no first-run notice; start recording from the panel.
                typer.echo(f"Panel: {panel.url}")
                typer.echo("Press Ctrl+C to stop.")
                _sigterm_stops_like_ctrl_c()
                _wait_until_interrupted()
                ran = True
            else:
                ran = TrayApp(recorder, panel.url).run()
        finally:
            recorder.stop()
            panel.stop()
            status.close()
        if not ran:
            typer.echo("Recording notice declined; nothing was started.")

    @app.command()
    def record(
        no_mic: bool = typer.Option(False, "--no-mic", help="Do not capture the microphone."),
        model: Optional[str] = typer.Option(None, "--model", help="ASR model, e.g. tiny.en, base.en, small.en."),
        them_file: Optional[Path] = typer.Option(
            None, "--them-file", help="Transcribe this WAV as 'them' instead of capturing system audio."
        ),
        me_file: Optional[Path] = typer.Option(
            None, "--me-file", help="Transcribe this WAV as 'me' instead of capturing the microphone."
        ),
        fast: bool = typer.Option(False, "--fast", help="With --them-file/--me-file: feed files faster than real time."),
    ) -> None:
        """Record without a UI; Ctrl+C stops. With WAV files it transcribes them instead (offline)."""
        _setup_logging()
        from audio_notes.capture.file_source import FileSource
        from audio_notes.config import Config
        from audio_notes.recorder import Recorder
        from audio_notes.store.reader import StoreReader

        cfg = Config.from_env()
        if model:
            cfg = dataclasses.replace(cfg, model=model)

        file_sources: list[FileSource] = []
        for path, speaker in ((them_file, "them"), (me_file, "me")):
            if path is None:
                continue
            if not path.is_file():
                typer.echo(f"No such file: {path}", err=True)
                raise typer.Exit(1)
            file_sources.append(FileSource(path, speaker, realtime=not fast))

        recorder = Recorder(
            cfg,
            mic_enabled=not no_mic,
            **({"source_factory": lambda _mic: file_sources} if file_sources else {}),
        )
        typer.echo(f"Loading model {cfg.model} (the first run downloads it)...")
        try:
            recorder.start()
        except Exception as e:
            typer.echo(f"Could not start recording: {e}", err=True)
            raise typer.Exit(1)
        session_id = recorder.session_id
        typer.echo(f"Recording session {session_id} -> {recorder.session_path}")
        _sigterm_stops_like_ctrl_c()
        try:
            if file_sources:
                for src in file_sources:
                    src.join()
            else:
                typer.echo("Press Ctrl+C to stop.")
                while True:
                    time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            typer.echo("Stopping (finishing pending transcription)...")
            recorder.stop()
        segments, _ = StoreReader().read_segments(session_id)
        typer.echo(f"Done: {len(segments)} segment(s) in session {session_id}.")
