"""Recorder: glues capture -> processing -> ASR -> store.

Implements `tray.controller.RecorderController`, so the tray and the `record` command drive
exactly the same code. Heavy imports (faster-whisper, PyAudioWPatch) stay lazy.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Sequence

from audio_notes.asr.base import Transcriber
from audio_notes.capture.base import AudioChunk, AudioSource, Speaker
from audio_notes.config import Config
from audio_notes.processing.runner import PipelineRunner
from audio_notes.store.writer import SessionWriter

log = logging.getLogger(__name__)

# Builds the audio sources for a session; the argument says whether the microphone is wanted.
SourceFactory = Callable[[bool], Sequence[AudioSource]]


def default_sources(mic: bool) -> list[AudioSource]:
    """System-audio loopback ("them") plus, optionally, the default microphone ("me")."""
    from audio_notes.capture.win_wasapi import LoopbackSource, MicSource

    sources: list[AudioSource] = [LoopbackSource()]
    if mic:
        sources.append(MicSource())
    return sources


def model_is_cached(model: str) -> bool:
    """True when the ASR model is already on disk (so loading it will not download)."""
    try:
        from faster_whisper.utils import download_model

        download_model(model, local_files_only=True)
        return True
    except Exception:
        return False


class _Guarded(AudioSource):
    """Reports a failed start to the recorder, then re-raises so the runner still logs it."""

    def __init__(self, inner: AudioSource, on_fail: Callable[[Speaker, Exception], None]) -> None:
        self._inner = inner
        self._on_fail = on_fail
        self.speaker = inner.speaker

    def start(self, on_chunk: Callable[[AudioChunk], None], origin: float) -> None:
        try:
            self._inner.start(on_chunk, origin)
        except Exception as e:
            self._on_fail(self.speaker, e)
            raise

    def stop(self) -> None:
        self._inner.stop()


class Recorder:
    def __init__(
        self,
        config: Config | None = None,
        *,
        source_factory: SourceFactory = default_sources,
        transcriber: Transcriber | None = None,
        mic_enabled: bool = True,
        model_cached: Callable[[str], bool] = model_is_cached,
    ) -> None:
        self._config = config or Config.from_env()
        self._source_factory = source_factory
        self._transcriber = transcriber
        self._mic = mic_enabled
        self._model_cached = model_cached
        self._lock = threading.Lock()
        self._recording = False
        self._downloading = False
        self._error: str | None = None
        self._failed: dict[str, Exception] = {}
        self._runner: PipelineRunner | None = None
        self._writer: SessionWriter | None = None

    # -- RecorderController ------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._recording:
                return
            self._error = None
            self._failed = {}
            try:
                self._start_locked()
            except Exception as e:
                self._error = _short(e)
                log.exception("could not start recording")
                raise

    def stop(self) -> None:
        with self._lock:
            runner, writer = self._runner, self._writer
            self._runner = self._writer = None
            self._recording = False  # the UI shows "idle" at once; the drain below can take seconds
            if runner is not None:
                runner.stop()
            if writer is not None:
                writer.close()

    def is_recording(self) -> bool:
        return self._recording

    def mic_enabled(self) -> bool:
        return self._mic

    def set_mic_enabled(self, enabled: bool) -> None:
        """Applies from the next `start()`; a running session keeps its sources."""
        self._mic = enabled

    def last_error(self) -> str | None:
        return self._error

    def is_downloading_model(self) -> bool:
        return self._downloading

    # -- extras ------------------------------------------------------------

    @property
    def session_id(self) -> str | None:
        writer = self._writer
        return writer.session_id if writer is not None else None

    @property
    def session_path(self):
        writer = self._writer
        return writer.path if writer is not None else None

    # -- internals ---------------------------------------------------------

    def _transcriber_ready(self) -> Transcriber:
        if self._transcriber is None:
            from audio_notes.asr.faster_whisper_engine import FasterWhisperTranscriber

            self._transcriber = FasterWhisperTranscriber(self._config)
        load = getattr(self._transcriber, "load", None)
        if load is not None:
            # Load before the pipeline starts so a first-run download cannot stall it.
            self._downloading = not self._model_cached(self._config.model)
            try:
                load()
            finally:
                self._downloading = False
        return self._transcriber

    def _source_failed(self, speaker: Speaker, exc: Exception) -> None:
        self._failed[speaker] = exc

    def _start_locked(self) -> None:
        transcriber = self._transcriber_ready()
        sources = [_Guarded(s, self._source_failed) for s in self._source_factory(self._mic)]
        writer = SessionWriter()
        runner = PipelineRunner(sources, transcriber, writer)
        try:
            runner.start()
            # The system-audio side is the point of the tool: without it, or with no source
            # at all, a "recording" would be misleading, so that is a hard failure. A missing
            # microphone only degrades the session.
            if "them" in self._failed or (self._failed and len(self._failed) >= len(sources)):
                bad = self._failed.get("them") or next(iter(self._failed.values()))
                raise RuntimeError(f"Cannot capture audio: {_short(bad)}")
            for speaker, exc in self._failed.items():
                log.warning("%s source unavailable, recording without it: %s", speaker, exc)
        except Exception:
            runner.stop()
            writer.close()
            raise
        self._runner, self._writer = runner, writer
        self._recording = True


def _short(exc: BaseException) -> str:
    text = str(exc).strip() or type(exc).__name__
    return text if len(text) <= 160 else text[:157] + "..."
