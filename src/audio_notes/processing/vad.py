"""Streaming Silero VAD segmenter running on onnxruntime (no torch)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000
FRAME = 512  # samples per VAD frame (32 ms)
CONTEXT = 64  # samples of left context the model expects


@dataclass(frozen=True)
class SpeechSegment:
    t0: float  # seconds, same time base as the start_time given to reset()
    t1: float
    samples: np.ndarray  # float32 16 kHz mono


def _model_path() -> str:
    # Reuse the ONNX model that faster-whisper ships; no extra download or dependency.
    import faster_whisper

    return str(Path(faster_whisper.__file__).parent / "assets" / "silero_vad_v6.onnx")


class _SileroModel:
    def __init__(self, path: str | None = None) -> None:
        import onnxruntime

        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.log_severity_level = 4
        self._sess = onnxruntime.InferenceSession(
            path or _model_path(), providers=["CPUExecutionProvider"], sess_options=opts
        )
        self.reset()

    def reset(self) -> None:
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._ctx = np.zeros(CONTEXT, dtype=np.float32)

    def prob(self, frame: np.ndarray) -> float:
        x = np.concatenate([self._ctx, frame])[None, :]
        out, self._h, self._c = self._sess.run(
            None, {"input": x, "h": self._h, "c": self._c}
        )
        self._ctx = frame[-CONTEXT:].copy()
        return float(np.asarray(out).ravel()[0])


class VadSegmenter:
    """Feed 16 kHz mono float32 audio; get speech segments out.

    A segment ends after `silence_ms` of non-speech, or is force-cut at `max_s`.
    Segments with less than `min_speech_ms` of detected speech are dropped.
    Not thread-safe: use one instance per stream.
    """

    def __init__(
        self,
        threshold: float = 0.5,
        silence_ms: int = 500,
        max_s: float = 25.0,
        min_speech_ms: int = 250,
        pad_ms: int = 160,
        model_path: str | None = None,
    ) -> None:
        self._model = _SileroModel(model_path)
        self._on = threshold
        self._off = max(threshold - 0.15, 0.01)
        self._silence_frames = max(1, round(silence_ms / 1000 * SAMPLE_RATE / FRAME))
        self._max_frames = int(max_s * SAMPLE_RATE / FRAME)
        self._min_voiced = max(1, round(min_speech_ms / 1000 * SAMPLE_RATE / FRAME))
        self._pad_frames = max(0, round(pad_ms / 1000 * SAMPLE_RATE / FRAME))
        self.reset(0.0)

    def reset(self, start_time: float = 0.0) -> None:
        """Discard all state; the next sample fed is at `start_time` seconds."""
        self._model.reset()
        self._t_origin = start_time
        self._n = 0  # frames consumed
        self._buf = np.zeros(0, dtype=np.float32)
        self._pre: deque[np.ndarray] = deque(maxlen=self._pad_frames)
        self._clear_segment()

    def _clear_segment(self) -> None:
        self._frames: list[np.ndarray] = []
        self._start_idx = 0
        self._voiced = 0
        self._quiet = 0  # trailing non-speech frames inside the current segment
        self._active = False

    def _t(self, frame_idx: int) -> float:
        return self._t_origin + frame_idx * FRAME / SAMPLE_RATE

    def feed(self, samples: np.ndarray) -> list[SpeechSegment]:
        self._buf = np.concatenate([self._buf, np.asarray(samples, dtype=np.float32)])
        out: list[SpeechSegment] = []
        k = len(self._buf) // FRAME
        for i in range(k):
            seg = self._step(self._buf[i * FRAME : (i + 1) * FRAME])
            if seg is not None:
                out.append(seg)
        self._buf = self._buf[k * FRAME :].copy()
        return out

    def _step(self, frame: np.ndarray) -> SpeechSegment | None:
        p = self._model.prob(frame)
        idx = self._n
        self._n += 1
        if not self._active:
            if p >= self._on:
                self._active = True
                self._frames = list(self._pre) + [frame]
                self._start_idx = idx - len(self._pre)
                self._pre.clear()
                self._voiced, self._quiet = 1, 0
            else:
                self._pre.append(frame)
            return None
        self._frames.append(frame)
        if p >= self._off:
            self._quiet = 0
            if p >= self._on:
                self._voiced += 1
        else:
            self._quiet += 1
        if self._quiet >= self._silence_frames:
            return self._emit(forced=False)
        if len(self._frames) >= self._max_frames:
            return self._emit(forced=True)
        return None

    def _emit(self, forced: bool) -> SpeechSegment | None:
        frames = self._frames
        if not forced:
            drop = max(0, self._quiet - self._pad_frames)
            if drop:
                frames = frames[:-drop]
        seg = None
        if self._voiced >= self._min_voiced and frames:
            seg = SpeechSegment(
                self._t(self._start_idx),
                self._t(self._start_idx + len(frames)),
                np.concatenate(frames),
            )
        if forced:
            # speech continues: stay active, next segment starts right after this one
            self._start_idx += len(self._frames)
            self._frames, self._voiced, self._quiet = [], 0, 0
        else:
            self._clear_segment()
            self._pre.clear()
        return seg

    def flush(self) -> list[SpeechSegment]:
        """Return pending speech (if any) and end the current segment."""
        out: list[SpeechSegment] = []
        if len(self._buf):  # zero-pad the partial frame so it is still analysed
            pad = np.zeros(FRAME - len(self._buf), dtype=np.float32)
            seg = self._step(np.concatenate([self._buf, pad]))
            if seg is not None:
                out.append(seg)
            self._buf = np.zeros(0, dtype=np.float32)
        if self._active:
            seg = self._emit(forced=False)
            if seg is not None:
                out.append(seg)
        self._clear_segment()
        return out
