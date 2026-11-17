"""Pipeline orchestration: sources -> (resample, VAD) per source -> one ASR worker -> sink."""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Callable, Sequence

from audio_notes.asr.base import Transcriber
from audio_notes.capture.base import AudioChunk, AudioSource, Speaker
from audio_notes.processing.resample import StreamResampler
from audio_notes.processing.vad import SpeechSegment, VadSegmenter
from audio_notes.store.models import TranscriptSink

log = logging.getLogger(__name__)

_STOP = object()
# A chunk starting this far from where the previous one ended means the stream had a
# gap (device switch, dropped buffers): restart VAD there so timestamps stay honest.
_GAP_S = 0.5

# speaker -> the exception its source raised from start()
StartFailures = dict[Speaker, Exception]


class PipelineRunner:
    def __init__(
        self,
        sources: Sequence[AudioSource],
        transcriber: Transcriber,
        sink: TranscriptSink,
        clock: Callable[[], float] = time.monotonic,
        vad_factory: Callable[[], VadSegmenter] = VadSegmenter,
        on_source_lost: Callable[[Speaker, Exception], None] | None = None,
    ) -> None:
        self._sources = list(sources)
        self._transcriber = transcriber
        self._sink = sink
        self._clock = clock
        self._vad_factory = vad_factory
        self._on_source_lost = on_source_lost
        self._asr_q: queue.Queue = queue.Queue()
        self._in_qs: list[queue.Queue] = []
        self._threads: list[threading.Thread] = []
        self._asr_thread: threading.Thread | None = None
        self._origin = 0.0
        self._started = False
        self._src_lock = threading.Lock()  # serialises start / restart / stop of the sources

    def start(self) -> StartFailures:
        """Start the workers and every source. Returns the sources that failed to start; the
        others keep running. A failed source's worker stays idle, so `restart_sources()` can
        still bring it back (e.g. a headset plugged in later)."""
        with self._src_lock:
            if self._started:
                return {}
            self._started = True
            self._origin = self._clock()
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
            return self._start_sources_locked()

    def restart_sources(self) -> StartFailures:
        """Stop every source, then start them all again on the current default devices.

        All of them go down together on purpose: PortAudio only re-scans the device list (and so
        sees a new default device) once no stream of the process is open. Chunks after the restart
        carry later timestamps, which the per-source loop treats as a gap."""
        with self._src_lock:
            if not self._started:
                return {}
            self._stop_sources_locked()
            return self._start_sources_locked()

    def stop(self) -> None:
        with self._src_lock:
            if not self._started:
                return
            self._started = False
            self._stop_sources_locked()
        for q in self._in_qs:
            q.put(_STOP)
        for t in self._threads:
            t.join()
        self._asr_q.put(_STOP)
        if self._asr_thread is not None:
            self._asr_thread.join()
        self._in_qs, self._threads, self._asr_thread = [], [], None

    # -- sources -----------------------------------------------------------

    def _start_sources_locked(self) -> StartFailures:
        failed: StartFailures = {}
        for src, q in zip(self._sources, self._in_qs):
            speaker = getattr(src, "speaker", "?")
            src.on_lost = lambda exc, speaker=speaker: self._source_lost(speaker, exc)
            try:
                src.start(q.put, self._origin)
            except Exception as e:
                log.warning("source %s failed to start: %s", speaker, e)
                failed[speaker] = e
        return failed

    def _stop_sources_locked(self) -> None:
        for src in self._sources:
            try:
                src.stop()
            except Exception:
                log.exception("source %s failed to stop", getattr(src, "speaker", "?"))

    def _source_lost(self, speaker: Speaker, exc: Exception) -> None:
        if not self._started or self._on_source_lost is None:
            return
        try:
            self._on_source_lost(speaker, exc)
        except Exception:
            log.exception("on_source_lost handler failed")

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
        while True:
            item = q.get()
            if item is _STOP:
                break
            try:
                chunk: AudioChunk = item
                if next_t is None or abs(chunk.t - next_t) > _GAP_S:
                    if next_t is not None:
                        self._emit(speaker, self._finish(rs, vad))
                    rs = StreamResampler()
                    vad.reset(chunk.t)
                pcm = rs.process(chunk.samples, chunk.sample_rate)
                next_t = chunk.t + len(chunk.samples) / chunk.sample_rate
                self._emit(speaker, vad.feed(pcm))
            except Exception:
                log.exception("[%s] processing failed", speaker)
        try:
            self._emit(speaker, self._finish(rs, vad))
        except Exception:
            log.exception("[%s] flush failed", speaker)

    @staticmethod
    def _finish(rs: StreamResampler, vad: VadSegmenter) -> list[SpeechSegment]:
        """End of a stretch of audio: the resampler's buffered tail goes through VAD first,
        then VAD gives up its pending speech."""
        tail = rs.flush()
        out = vad.feed(tail) if len(tail) else []
        return out + vad.flush()

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
