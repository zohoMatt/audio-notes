"""Pipeline orchestration: sources -> (resample, VAD) per source -> one ASR worker -> sink."""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Callable, Sequence

from audio_notes.asr.base import Transcriber
from audio_notes.capture.base import AudioChunk, AudioSource
from audio_notes.processing.resample import TARGET_RATE, StreamResampler
from audio_notes.processing.vad import SpeechSegment, VadSegmenter
from audio_notes.store.models import TranscriptSink

log = logging.getLogger(__name__)

_STOP = object()
# A chunk starting this far from where the previous one ended means the stream had a
# gap (device switch, dropped buffers): restart VAD there so timestamps stay honest.
_GAP_S = 0.5


class PipelineRunner:
    def __init__(
        self,
        sources: Sequence[AudioSource],
        transcriber: Transcriber,
        sink: TranscriptSink,
        clock: Callable[[], float] = time.monotonic,
        vad_factory: Callable[[], VadSegmenter] = VadSegmenter,
    ) -> None:
        self._sources = list(sources)
        self._transcriber = transcriber
        self._sink = sink
        self._clock = clock
        self._vad_factory = vad_factory
        self._asr_q: queue.Queue = queue.Queue()
        self._in_qs: list[queue.Queue] = []
        self._threads: list[threading.Thread] = []
        self._asr_thread: threading.Thread | None = None
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        origin = self._clock()
        self._asr_thread = threading.Thread(target=self._asr_loop, name="asr", daemon=True)
        self._asr_thread.start()
        for i, src in enumerate(self._sources):
            q: queue.Queue = queue.Queue()
            self._in_qs.append(q)
            t = threading.Thread(
                target=self._source_loop,
                args=(src, q),
                name=f"proc-{getattr(src, 'speaker', i)}",
                daemon=True,
            )
            t.start()
            self._threads.append(t)
            try:
                src.start(q.put, origin)
            except Exception:
                log.exception("source %s failed to start", getattr(src, "speaker", i))
                q.put(_STOP)

    def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        for src in self._sources:
            try:
                src.stop()
            except Exception:
                log.exception("source %s failed to stop", getattr(src, "speaker", "?"))
        for q in self._in_qs:
            q.put(_STOP)
        for t in self._threads:
            t.join()
        self._asr_q.put(_STOP)
        if self._asr_thread is not None:
            self._asr_thread.join()
        self._in_qs, self._threads, self._asr_thread = [], [], None

    # -- per-source thread -------------------------------------------------

    def _source_loop(self, src: AudioSource, q: queue.Queue) -> None:
        speaker = src.speaker
        try:
            vad = self._vad_factory()
        except Exception:
            log.exception("[%s] VAD init failed; this source is disabled", speaker)
            self._drain(q)
            return
        rs = StreamResampler()
        next_t: float | None = None
        broken = False
        while True:
            item = q.get()
            if item is _STOP:
                break
            if broken:
                continue
            try:
                chunk: AudioChunk = item
                if next_t is None or abs(chunk.t - next_t) > _GAP_S:
                    if next_t is not None:
                        self._emit(speaker, vad.flush() + self._flush_rs(rs, vad))
                    rs = StreamResampler()
                    vad.reset(chunk.t)
                pcm = rs.process(chunk.samples, chunk.sample_rate)
                next_t = chunk.t + len(chunk.samples) / chunk.sample_rate
                self._emit(speaker, vad.feed(pcm))
            except Exception:
                log.exception("[%s] processing failed", speaker)
        try:
            self._emit(speaker, self._flush_rs(rs, vad) + vad.flush())
        except Exception:
            log.exception("[%s] flush failed", speaker)

    @staticmethod
    def _flush_rs(rs: StreamResampler, vad: VadSegmenter) -> list[SpeechSegment]:
        tail = rs.flush()
        return vad.feed(tail) if len(tail) else []

    @staticmethod
    def _drain(q: queue.Queue) -> None:
        while q.get() is not _STOP:
            pass

    def _emit(self, speaker: str, segs: list[SpeechSegment]) -> None:
        for s in segs:
            self._asr_q.put((speaker, s))

    # -- ASR worker --------------------------------------------------------

    def _asr_loop(self) -> None:
        while True:
            item = self._asr_q.get()
            if item is _STOP:
                return
            speaker, seg = item
            try:
                text = self._transcriber.transcribe(seg.samples).strip()
            except Exception:
                log.exception("transcription failed (%s %.2f-%.2f)", speaker, seg.t0, seg.t1)
                continue
            if not text:
                continue
            try:
                self._sink.append(seg.t0, seg.t1, speaker, text)
            except Exception:
                log.exception("sink.append failed")


__all__ = ["PipelineRunner", "TARGET_RATE"]
