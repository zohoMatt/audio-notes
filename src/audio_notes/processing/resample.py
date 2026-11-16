"""Resample arbitrary-rate audio to 16 kHz mono float32."""

from __future__ import annotations

import numpy as np
import soxr

TARGET_RATE = 16000


def to_mono(samples: np.ndarray) -> np.ndarray:
    """Collapse (n,) or (n, channels) to float32 mono (n,)."""
    a = np.asarray(samples)
    if a.ndim == 2:
        a = a.mean(axis=1)
    return np.ascontiguousarray(a, dtype=np.float32)


def resample_to_16k(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    """One-shot conversion (no state kept between calls)."""
    mono = to_mono(samples)
    if sample_rate == TARGET_RATE or mono.size == 0:
        return mono
    return soxr.resample(mono, sample_rate, TARGET_RATE).astype(np.float32, copy=False)


class StreamResampler:
    """Stateful converter for consecutive chunks of one stream (no seams between chunks).

    If the incoming rate changes (e.g. device switch) the filter is rebuilt.
    """

    def __init__(self) -> None:
        self._rate: int | None = None
        self._stream: soxr.ResampleStream | None = None

    def process(self, samples: np.ndarray, sample_rate: int) -> np.ndarray:
        mono = to_mono(samples)
        if sample_rate == TARGET_RATE:
            self._rate, self._stream = sample_rate, None
            return mono
        if self._stream is None or self._rate != sample_rate:
            self._rate = sample_rate
            self._stream = soxr.ResampleStream(
                sample_rate, TARGET_RATE, 1, dtype="float32"
            )
        if mono.size == 0:
            return mono
        return self._stream.resample_chunk(mono).astype(np.float32, copy=False).reshape(-1)

    def flush(self) -> np.ndarray:
        if self._stream is None:
            return np.zeros(0, dtype=np.float32)
        out = self._stream.resample_chunk(np.zeros(0, dtype=np.float32), last=True)
        self._stream = None
        return out.astype(np.float32, copy=False).reshape(-1)
