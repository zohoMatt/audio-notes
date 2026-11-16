"""WASAPI capture via PyAudioWPatch: system loopback ("them") and microphone ("me").

PyAudioWPatch is imported lazily so this module imports on machines without it.
Timestamps come from `time.monotonic()` (not frame counting): WASAPI loopback delivers
no frames while nothing is playing, so frame counts drift away from wall-clock time.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

import numpy as np

from .base import AudioChunk, AudioSource, Speaker

log = logging.getLogger(__name__)

CHUNK_MS = 50


def _import_pyaudio() -> Any:
    try:
        import pyaudiowpatch as pyaudio
    except ImportError as e:  # pragma: no cover - depends on platform
        raise RuntimeError(
            "PyAudioWPatch is not available (Windows only): pip install PyAudioWPatch"
        ) from e
    return pyaudio


def list_devices() -> dict[str, list[dict[str, Any]]]:
    """Return {"loopback": [...], "microphone": [...]} with name/index/rate/channels/default."""
    pyaudio = _import_pyaudio()
    p = pyaudio.PyAudio()
    try:
        try:
            default_loop = p.get_default_wasapi_loopback()["index"]
        except Exception:
            default_loop = None
        try:
            default_mic = p.get_default_input_device_info()["index"]
        except Exception:
            default_mic = None
        loops = []
        for d in p.get_loopback_device_info_generator():
            loops.append(_summ(d, d["index"] == default_loop))
        loop_idx = {d["index"] for d in loops}
        mics = []
        wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)["index"]
        for i in range(p.get_device_count()):
            d = p.get_device_info_by_index(i)
            if (
                d["hostApi"] == wasapi
                and d["maxInputChannels"] > 0
                and not d.get("isLoopbackDevice", False)
                and d["index"] not in loop_idx
            ):
                mics.append(_summ(d, d["index"] == default_mic))
        return {"loopback": loops, "microphone": mics}
    finally:
        p.terminate()


def _summ(d: dict[str, Any], is_default: bool) -> dict[str, Any]:
    return {
        "index": d["index"],
        "name": d["name"],
        "sample_rate": int(d["defaultSampleRate"]),
        "channels": int(d["maxInputChannels"]),
        "default": is_default,
    }


class _WasapiSource(AudioSource):
    speaker: Speaker

    def __init__(self) -> None:
        self._p: Any = None
        self._stream: Any = None
        self._lock = threading.Lock()
        self._stopping = threading.Event()
        self._watchdog: threading.Thread | None = None
        self.device_name: str | None = None

    def _pick_device(self, p: Any) -> dict[str, Any]:
        raise NotImplementedError

    def start(self, on_chunk: Callable[[AudioChunk], None], origin: float) -> None:
        pyaudio = _import_pyaudio()
        with self._lock:
            if self._stream is not None:
                raise RuntimeError("source already started")
            self._stopping.clear()
            p = pyaudio.PyAudio()
            try:
                dev = self._pick_device(p)
                rate = int(dev["defaultSampleRate"])
                channels = int(dev["maxInputChannels"])
                speaker = self.speaker
                frames = max(1, rate * CHUNK_MS // 1000)

                def cb(in_data, frame_count, time_info, status):  # noqa: ANN001
                    if in_data and not self._stopping.is_set():
                        try:
                            x = np.frombuffer(in_data, dtype=np.float32)
                            if channels > 1:
                                x = x[: (len(x) // channels) * channels].reshape(-1, channels).mean(axis=1)
                            else:
                                x = x.copy()
                            t = max(0.0, time.monotonic() - origin - len(x) / rate)
                            on_chunk(AudioChunk(x.astype(np.float32, copy=False), rate, t, speaker))
                        except Exception:
                            log.exception("%s: on_chunk failed", speaker)
                    return (None, pyaudio.paContinue)

                stream = p.open(
                    format=pyaudio.paFloat32,
                    channels=channels,
                    rate=rate,
                    input=True,
                    input_device_index=dev["index"],
                    frames_per_buffer=frames,
                    stream_callback=cb,
                )
            except Exception:
                p.terminate()
                raise
            self._p, self._stream = p, stream
            self.device_name = dev["name"]
            log.info("%s capture started on %r (%d Hz, %d ch)", self.speaker, dev["name"], rate, channels)
            self._watchdog = threading.Thread(target=self._watch, daemon=True, name=f"wasapi-watch-{self.speaker}")
            self._watchdog.start()

    def _watch(self) -> None:
        # A removed / switched device makes PortAudio deactivate the stream. Log and stop
        # just this source instead of crashing the process.
        while not self._stopping.wait(0.5):
            stream = self._stream
            try:
                alive = stream is not None and stream.is_active()
            except Exception:
                alive = False
            if not alive:
                log.error("%s: audio device lost or stream stopped; stopping this source", self.speaker)
                threading.Thread(target=self.stop, daemon=True).start()
                return

    def stop(self) -> None:
        self._stopping.set()
        with self._lock:
            stream, p = self._stream, self._p
            self._stream = self._p = None
        if stream is not None:
            try:
                stream.stop_stream()
            except Exception:
                log.debug("stop_stream failed", exc_info=True)
            try:
                stream.close()
            except Exception:
                log.debug("close failed", exc_info=True)
        if p is not None:
            try:
                p.terminate()
            except Exception:
                log.debug("terminate failed", exc_info=True)


class LoopbackSource(_WasapiSource):
    """System audio (default output device, WASAPI loopback) -> speaker "them"."""

    speaker: Speaker = "them"

    def _pick_device(self, p: Any) -> dict[str, Any]:
        return p.get_default_wasapi_loopback()


class MicSource(_WasapiSource):
    """Default input device -> speaker "me"."""

    speaker: Speaker = "me"

    def _pick_device(self, p: Any) -> dict[str, Any]:
        return p.get_default_input_device_info()
