"""Recorder: glues capture -> processing -> ASR -> store.

Implements `tray.controller.RecorderController`, so the tray and the `record` command drive
exactly the same code. Heavy imports (faster-whisper, PyAudioWPatch, the macOS helper) stay lazy.
"""

from __future__ import annotations

import logging
import sys
import threading
from typing import Callable, Sequence

from audio_notes.asr.base import Transcriber
from audio_notes.capture.base import AudioSource, Speaker
from audio_notes.config import Config
from audio_notes.processing.runner import PipelineRunner, StartFailures
from audio_notes.processing.vad import VadSegmenter
from audio_notes.store.status import StatusPublisher
from audio_notes.store.writer import SessionWriter

log = logging.getLogger(__name__)

# Builds the audio sources for a session; the argument says whether the microphone is wanted.
SourceFactory = Callable[[bool], Sequence[AudioSource]]

RECOVER_DELAY_S = 1.0  # after a device change, let the OS settle before re-opening streams
RETRY_INTERVAL_S = 3.0  # while system audio cannot be re-opened, try again this often


def default_sources(mic: bool) -> list[AudioSource]:
    """System audio ("them") plus, optionally, the default microphone ("me"): WASAPI loopback on
    Windows, a Core Audio process tap (through the Swift helper) on macOS."""
    if sys.platform == "darwin":
        from audio_notes.capture.mac_tap import MicSource, TapSource

        sources: list[AudioSource] = [TapSource()]
        if mic:
            sources.append(MicSource())
        return sources
    from audio_notes.capture.win_wasapi import LoopbackSource, MicSource as WasapiMicSource

    sources = [LoopbackSource()]
    if mic:
        sources.append(WasapiMicSource())
    return sources


def model_is_cached(model: str) -> bool:
    """True when the ASR model is already on disk (so loading it will not download)."""
    try:
        from faster_whisper.utils import download_model

        download_model(model, local_files_only=True)
        return True
    except Exception:
        return False


def capture_problem(failed: StartFailures, n_sources: int) -> str | None:
    """Why a session cannot count as recording, or None.

    System audio is the point of the tool: without it, or with no source at all, a "recording"
    would be misleading. A missing microphone only degrades the session."""
    if "them" in failed or (failed and len(failed) >= n_sources):
        bad = failed.get("them") or next(iter(failed.values()))
        return f"Cannot capture audio: {_short(bad)}"
    return None


class _Session:
    """One running recording: its pipeline, its file and its device-recovery thread."""

    def __init__(self, runner: PipelineRunner, writer: SessionWriter, n_sources: int) -> None:
        self.runner = runner
        self.writer = writer
        self.n_sources = n_sources
        self.lost = threading.Event()  # a source reported its device gone / switched
        self.done = threading.Event()  # the session is stopping
        self.recovery: threading.Thread | None = None
        self.degraded = False  # the recorder's error describes this session's capture
        self.paused = False


class Recorder:
    def __init__(
        self,
        config: Config | None = None,
        *,
        source_factory: SourceFactory = default_sources,
        transcriber: Transcriber | None = None,
        mic_enabled: bool = True,
        model_cached: Callable[[str], bool] = model_is_cached,
        status: StatusPublisher | None = None,
        recover_delay: float = RECOVER_DELAY_S,
        retry_interval: float = RETRY_INTERVAL_S,
    ) -> None:
        self._config = config or Config.from_env()
        self._source_factory = source_factory
        self._transcriber = transcriber
        self._mic = mic_enabled
        self._model_cached = model_cached
        self._status = status
        self._recover_delay = recover_delay
        self._retry_interval = retry_interval
        self._lock = threading.Lock()
        self._starting = False
        self._cancel_start = False
        self._downloading = False
        self._error: str | None = None
        self._session: _Session | None = None

    # -- RecorderController ------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._session is not None or self._starting:
                return
            self._starting = True
            self._cancel_start = False
            self._error = None
        try:
            # Outside the lock: the first run downloads the model, which can take minutes, and
            # stop() / quit must not wait for that.
            transcriber = self._transcriber_ready()
            with self._lock:
                if self._cancel_start:
                    log.info("start cancelled while the model was loading")
                    return
                self._session = self._open_session(transcriber)
        except Exception as e:
            self._error = _short(e)
            log.exception("could not start recording")
            raise
        finally:
            with self._lock:
                self._starting = False

    def stop(self) -> None:
        with self._lock:
            if self._starting:
                self._cancel_start = True  # a start still loading the model gives up when done
            session, self._session = self._session, None
            if session is None:
                return
            # The UI shows "idle" at once (is_recording() is already False); draining below can
            # take seconds.
            session.done.set()
            if session.recovery is not None:
                session.recovery.join()
            session.runner.stop()
            session.writer.close()
            if session.degraded:
                self._error = None  # it described this session's capture, which is over

    def pause(self) -> None:
        """Release the audio devices but keep the session open; `resume()` continues it."""
        with self._lock:
            s = self._session
            if s is None or s.paused:
                return
            s.paused = True
            s.runner.pause_sources()
            s.writer.set_paused(True)
            if s.degraded:  # capture is off, so a re-binding problem no longer applies
                s.degraded, self._error = False, None

    def resume(self) -> None:
        """Continue a paused session in the same file. Raises (and stays paused) when system
        audio cannot be opened."""
        with self._lock:
            s = self._session
            if s is None or not s.paused:
                return
            try:
                failed = s.runner.resume_sources()
            except Exception as e:  # noqa: BLE001
                failed = {"them": e}
            problem = capture_problem(failed, s.n_sources)
            if problem:
                s.runner.pause_sources()
                s.degraded, self._error = True, problem
                raise RuntimeError(problem)
            for speaker, exc in failed.items():
                log.warning("%s source unavailable after resuming: %s", speaker, exc)
            if s.degraded:
                s.degraded, self._error = False, None
            s.paused = False
            s.writer.set_paused(False)

    def is_recording(self) -> bool:
        """A session is open (capturing or paused)."""
        return self._session is not None

    def is_paused(self) -> bool:
        session = self._session
        return session is not None and session.paused

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
        session = self._session
        return session.writer.session_id if session is not None else None

    @property
    def session_path(self):
        session = self._session
        return session.writer.path if session is not None else None

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

    def _open_session(self, transcriber: Transcriber) -> _Session:
        sources = list(self._source_factory(self._mic))
        writer = SessionWriter(status=self._status)
        cfg = self._config
        holder: list[_Session] = []

        def on_lost(speaker: Speaker, exc: Exception) -> None:
            log.warning("%s capture lost (%s); re-binding to the current default devices", speaker, exc)
            if holder:
                holder[0].lost.set()

        runner = PipelineRunner(
            sources,
            transcriber,
            writer,
            vad_factory=lambda: VadSegmenter(silence_ms=cfg.vad_silence_ms, max_s=cfg.vad_max_s),
            on_source_lost=on_lost,
        )
        session = _Session(runner, writer, len(sources))
        holder.append(session)
        try:
            failed = runner.start()
            problem = capture_problem(failed, len(sources))
            if problem:
                raise RuntimeError(problem)
            for speaker, exc in failed.items():
                log.warning("%s source unavailable, recording without it: %s", speaker, exc)
        except Exception:
            runner.stop()
            writer.close()
            raise
        session.recovery = threading.Thread(
            target=self._recover, args=(session,), name="capture-recovery", daemon=True
        )
        session.recovery.start()
        return session

    def _recover(self, s: _Session) -> None:
        """Re-open the sources whenever one reports its device lost or switched; while system
        audio cannot be opened, show the error and keep retrying until it can or the session ends."""
        while not s.done.is_set():
            if not s.lost.wait(0.2):
                continue
            if s.done.wait(self._recover_delay):
                return
            s.lost.clear()
            try:
                failed = s.runner.restart_sources()
            except Exception as e:  # noqa: BLE001
                failed = {"them": e}
            problem = capture_problem(failed, s.n_sources)
            if problem:
                s.degraded = True
                self._error = f"{problem} (retrying)"
                log.warning("re-binding failed: %s; retrying in %.0f s", problem, self._retry_interval)
                if s.done.wait(self._retry_interval):
                    return
                s.lost.set()
                continue
            if s.degraded:
                s.degraded, self._error = False, None
            for speaker, exc in failed.items():
                log.warning("%s source unavailable after re-binding: %s", speaker, exc)
            log.info("audio capture re-bound")


def _short(exc: BaseException) -> str:
    text = str(exc).strip() or type(exc).__name__
    return text if len(text) <= 160 else text[:157] + "..."
