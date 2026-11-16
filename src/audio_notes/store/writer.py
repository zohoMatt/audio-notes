"""SessionWriter: the single writer. Appends JSONL lines and keeps status.json fresh."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from typing import IO

from audio_notes import paths
from audio_notes.capture.base import Speaker
from audio_notes.store.models import Segment

HEARTBEAT_INTERVAL_S = 2.0


class SessionWriter:
    """Implements `TranscriptSink`. One instance = one new session file."""

    def __init__(
        self,
        now: datetime | None = None,
        heartbeat_interval: float = HEARTBEAT_INTERVAL_S,
    ) -> None:
        now = now or datetime.now()
        self.path = paths.session_path_for(now)
        self.session_id = self.path.stem
        self._status_path = paths.status_path()  # fixed at construction
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._interval = heartbeat_interval
        self._lock = threading.Lock()
        self._seq = 0
        self._closed = False
        self._recording = True
        self._fh: IO[str] = open(self.path, "a", encoding="utf-8", newline="\n")
        self._stop = threading.Event()
        self._write_status()
        self._thread = threading.Thread(target=self._beat, name="status-heartbeat", daemon=True)
        self._thread.start()

    def append(self, t0: float, t1: float, speaker: Speaker, text: str) -> Segment:
        with self._lock:
            if self._closed:
                raise ValueError("SessionWriter is closed")
            self._seq += 1
            seg = Segment(seq=self._seq, t0=t0, t1=t1, speaker=speaker, text=text)
            self._fh.write(seg.to_json_line() + "\n")
            self._fh.flush()
            self._write_status_locked()
            return seg

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._recording = False
            self._stop.set()
            self._fh.close()
            self._write_status_locked()
        self._thread.join(timeout=2)

    def __enter__(self) -> "SessionWriter":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- status.json -------------------------------------------------------
    def _beat(self) -> None:
        while not self._stop.wait(self._interval):
            with self._lock:
                if self._closed:
                    return
                try:
                    self._write_status_locked()
                except OSError:
                    pass  # transient (e.g. reader holds file on Windows); next beat retries

    def _write_status(self) -> None:
        with self._lock:
            self._write_status_locked()

    def _write_status_locked(self) -> None:
        data = {
            "recording": self._recording,
            "session_id": self.session_id,
            "segments": self._seq,
            "last_heartbeat": time.time(),
            "pid": os.getpid(),
        }
        target = self._status_path
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        for attempt in range(5):  # Windows: replace can briefly fail while a reader has it open
            try:
                os.replace(tmp, target)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.01)
