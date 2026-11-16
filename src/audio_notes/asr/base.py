"""ASR contract (frozen; see DEV_TRACKS.md before changing)."""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class Transcriber(ABC):
    @abstractmethod
    def transcribe(self, samples: np.ndarray) -> str:
        """`samples`: float32 mono 16 kHz, one VAD-delimited speech segment (<= ~30 s).

        Returns the stripped text, or "" if nothing was recognised.
        """
