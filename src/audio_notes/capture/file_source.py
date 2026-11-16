"""Replay a WAV file as an AudioSource (tests, E2E, offline use)."""

from __future__ import annotations

import threading
import time
import wave
from pathlib import Path
from typing import Callable

import numpy as np

from .base import AudioChunk, AudioSource, Speaker


class FileSource(AudioSource):
    def __init__(
        self,
        path: str | Path,
        speaker: Speaker,
        realtime: bool = True,
        chunk_ms: int = 100,
        start_offset: float = 0.0,
    ) -> None:
        self.path = Path(path)
        self.speaker = speaker
        self.realtime = realtime
        self.chunk_ms = chunk_ms
        self.start_offset = start_offset
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self, on_chunk: Callable[[AudioChunk], None], origin: float) -> None:
        if self._thread is not None:
            raise RuntimeError("source already started")
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, args=(on_chunk,), daemon=True, name=f"file-source-{self.speaker}"
        )
        self._thread.start()

    def _run(self, on_chunk: Callable[[AudioChunk], None]) -> None:
        with wave.open(str(self.path), "rb") as w:
            if w.getsampwidth() != 2:
                raise ValueError("FileSource supports 16-bit PCM WAV only")
            rate, ch = w.getframerate(), w.getnchannels()
            per_chunk = max(1, rate * self.chunk_ms // 1000)
            pos = 0
            t0 = time.monotonic()
            while not self._stop.is_set():
                raw = w.readframes(per_chunk)
                if not raw:
                    break
                x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
                if ch > 1:
                    x = x[: (len(x) // ch) * ch].reshape(-1, ch).mean(axis=1, dtype=np.float32)
                t = self.start_offset + pos / rate
                if self.realtime:
                    delay = pos / rate - (time.monotonic() - t0)
                    if delay > 0 and self._stop.wait(delay):
                        break
                on_chunk(AudioChunk(x, rate, t, self.speaker))
                pos += len(x)

    def stop(self) -> None:
        self._stop.set()
        th = self._thread
        if th is not None and th is not threading.current_thread():
            th.join(timeout=5)

    def join(self, timeout: float | None = None) -> bool:
        """Wait until the file has been fully pushed (or stopped). Returns True if finished."""
        th = self._thread
        if th is not None:
            th.join(timeout)
            return not th.is_alive()
        return True
