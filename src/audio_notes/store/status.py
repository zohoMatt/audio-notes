"""StatusPublisher: owns status.json and its heartbeat.

The heartbeat says "the recorder process is alive", so it belongs to the process, not to a
session. The tray starts one publisher for its whole lifetime, which keeps an idle tray visible
as running (not "offline") to the panel, the CLI and the MCP server. A `SessionWriter` used on
its own creates a private publisher instead (see `store.writer`).
"""

from __future__ import annotations

import json
import os
import threading
import time

from audio_notes import paths

HEARTBEAT_INTERVAL_S = 2.0


class StatusPublisher:
    """Nothing is written before `start()`; `update()` before that only records the values."""

    def __init__(self, heartbeat_interval: float = HEARTBEAT_INTERVAL_S) -> None:
        self._path = paths.status_path()  # fixed at construction
        self._interval = heartbeat_interval
        self._lock = threading.Lock()
        self._recording = False
        self._session_id: str | None = None
        self._segments = 0
        self._started = False
        self._closed = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> "StatusPublisher":
        with self._lock:
            if self._started or self._closed:
                return self
            self._started = True
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._write_locked()
        self._thread = threading.Thread(target=self._beat, name="status-heartbeat", daemon=True)
        self._thread.start()
        return self

    def update(
        self,
        *,
        recording: bool | None = None,
        session_id: str | None = None,
        segments: int | None = None,
    ) -> None:
        """Change the published fields (None = keep) and write status.json now."""
        with self._lock:
            if self._closed:
                return
            if recording is not None:
                self._recording = recording
            if session_id is not None:
                self._session_id = session_id
            if segments is not None:
                self._segments = segments
            if self._started:
                self._write_locked()

    def close(self) -> None:
        """Final write (not recording) and stop beating. Readers see the process as gone once
        the last heartbeat goes stale."""
        with self._lock:
            if self._closed:
                return
            self._recording = False
            self._closed = True
            self._stop.set()
            if self._started:
                try:
                    self._write_locked()
                except OSError:
                    pass
        if self._thread is not None:
            self._thread.join(timeout=2)

    def __enter__(self) -> "StatusPublisher":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _beat(self) -> None:
        while not self._stop.wait(self._interval):
            with self._lock:
                if self._closed:
                    return
                try:
                    self._write_locked()
                except OSError:
                    pass  # transient (e.g. a reader holds the file on Windows); next beat retries

    def _write_locked(self) -> None:
        data = {
            "recording": self._recording,
            "session_id": self._session_id,
            "segments": self._segments,
            "last_heartbeat": time.time(),
            "pid": os.getpid(),
        }
        tmp = self._path.with_name(self._path.name + ".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        for attempt in range(5):  # Windows: replace can briefly fail while a reader has it open
            try:
                os.replace(tmp, self._path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.01)
