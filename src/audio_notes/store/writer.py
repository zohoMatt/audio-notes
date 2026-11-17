"""SessionWriter: the single writer of one session's JSONL file."""

from __future__ import annotations

import threading
from datetime import datetime
from typing import IO

from audio_notes import paths
from audio_notes.capture.base import Speaker
from audio_notes.store.models import Segment
from audio_notes.store.status import HEARTBEAT_INTERVAL_S, StatusPublisher

_MAX_SAME_SECOND = 1000


class SessionWriter:
    """Implements `TranscriptSink`. One instance = one new session file.

    Status: pass the process-wide `StatusPublisher` (the tray does) and the writer only reports
    session changes to it. Without one, the writer runs a private publisher for its own lifetime
    (the `record` command, tests).
    """

    def __init__(
        self,
        now: datetime | None = None,
        heartbeat_interval: float = HEARTBEAT_INTERVAL_S,
        status: StatusPublisher | None = None,
    ) -> None:
        now = now or datetime.now()
        paths.sessions_dir().mkdir(parents=True, exist_ok=True)
        self._fh: IO[str] = self._create(now)
        self.session_id = self.path.stem
        self._lock = threading.Lock()
        self._seq = 0
        self._closed = False
        self._owns_status = status is None
        self._status = status or StatusPublisher(heartbeat_interval).start()
        self._status.update(recording=True, session_id=self.session_id, segments=0, paused=False)

    def _create(self, now: datetime) -> IO[str]:
        # Exclusive create: a second session started within the same second gets a "-2" suffix
        # instead of appending to (and restarting the seq numbers of) the previous file.
        for n in range(1, _MAX_SAME_SECOND):
            path = paths.session_path_for(now, n)
            try:
                fh = open(path, "x", encoding="utf-8", newline="\n")
            except FileExistsError:
                continue
            self.path = path
            return fh
        raise RuntimeError(f"too many sessions started at {now}")

    def append(self, t0: float, t1: float, speaker: Speaker, text: str) -> Segment:
        with self._lock:
            if self._closed:
                raise ValueError("SessionWriter is closed")
            self._seq += 1
            seg = Segment(seq=self._seq, t0=t0, t1=t1, speaker=speaker, text=text)
            self._fh.write(seg.to_json_line() + "\n")
            self._fh.flush()
            try:
                self._status.update(segments=self._seq)
            except OSError:
                pass  # the transcript line is written; the status catches up on the next beat
            return seg

    def set_paused(self, paused: bool) -> None:
        """Publish that capture of this (still open) session is paused or running again."""
        with self._lock:
            if self._closed:
                return
        try:
            self._status.update(paused=paused)
        except OSError:
            pass  # the next heartbeat writes it

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._fh.close()
        try:
            self._status.update(recording=False)
        except OSError:
            pass
        if self._owns_status:
            self._status.close()

    def __enter__(self) -> "SessionWriter":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
