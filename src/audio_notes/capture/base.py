"""Audio capture contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Literal

import numpy as np

Speaker = Literal["me", "them"]


@dataclass(frozen=True)
class AudioChunk:
    samples: np.ndarray  # float32, mono, range [-1, 1]
    sample_rate: int  # source-native rate; resampling is the processing layer's job
    t: float  # seconds since the shared session origin, for the chunk's first sample
    speaker: Speaker


class AudioSource(ABC):
    """One audio stream. `them` = system loopback, `me` = microphone.

    Implementations push chunks from their own thread via `on_chunk`; the callback
    must stay cheap (it only enqueues). `origin` is a `time.monotonic()` value
    taken once per session so that every source of a session shares one time base.

    `on_lost`, when set (the pipeline sets it before `start()`), is called from any thread when
    a started source stops delivering for good: its device was removed, or the system default
    device it follows changed. The source must not restart itself; the owner decides.
    `start()` may be called again after `stop()`.
    """

    speaker: Speaker
    on_lost: Callable[[Exception], None] | None = None

    @abstractmethod
    def start(self, on_chunk: Callable[[AudioChunk], None], origin: float) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...
