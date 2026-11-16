"""faster-whisper backed Transcriber (CPU int8 by default)."""

from __future__ import annotations

import threading

import numpy as np

from audio_notes.asr.base import Transcriber
from audio_notes.config import Config


class FasterWhisperTranscriber(Transcriber):
    def __init__(self, config: Config | None = None, beam_size: int = 2) -> None:
        self._config = config or Config()
        self._beam_size = beam_size
        self._model = None
        self._lock = threading.Lock()

    def load(self) -> None:
        """Load the model now (downloads it on first use). Called lazily otherwise."""
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel  # heavy: import lazily

                self._model = WhisperModel(
                    self._config.model,
                    device=self._config.device,
                    compute_type=self._config.compute_type,
                )

    def transcribe(self, samples: np.ndarray) -> str:
        if self._model is None:
            self.load()
        audio = np.ascontiguousarray(samples, dtype=np.float32)
        segments, _info = self._model.transcribe(
            audio,
            language="en",
            beam_size=self._beam_size,
            vad_filter=False,  # segments are already cut by our own VAD
            condition_on_previous_text=False,
            without_timestamps=True,
        )
        return " ".join(s.text.strip() for s in segments).strip()
