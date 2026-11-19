"""macOS capture: system audio ("them") and microphone ("me") through the Swift helper.

The helper `audio-notes-capture` (source: macos/capture/) does the real-time audio work outside
Python: `tap` mode records system audio with a Core Audio process tap (macOS 14.2+), `mic` mode
the default input through AVAudioEngine. Each `AudioSource` here runs one helper process and
reads framed float32 PCM from its stdout. The wire format and exit codes are documented in
macos/capture/Sources/AudioNotesCapture/Protocol.swift; keep the two files in sync.

Timestamps follow the Windows rule (wall clock, not frame counting): a frame is dated from the
moment it arrives, back-dated by the helper's own `sent_ns - host_ns` (capture-to-write delay
measured on the helper's clock), so the two processes never need a shared time base.

Nothing here imports macOS-only modules, so it is importable and testable on any platform with a
fake helper (see tests/test_capture_mac_tap.py).
"""

from __future__ import annotations

import json
import logging
import os
import re
import struct
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Callable, Sequence

import numpy as np

from .base import AudioChunk, AudioSource, Speaker

log = logging.getLogger(__name__)

HELPER_NAME = "audio-notes-capture"
HELPER_ENV = "AUDIO_NOTES_CAPTURE_HELPER"  # explicit helper path (development, tests)

HEADER = struct.Struct("<4sIIIQQ")  # magic, sample_rate, count, flags, host_ns, sent_ns
MAGIC_READY = b"ANCR"
MAGIC_FRAME = b"ANCF"
MAX_SAMPLES = 1 << 22  # sanity bound on one frame (~87 s at 48 kHz); larger means a corrupt stream

# Helper exit codes (Protocol.swift `ExitCode`).
EXIT_OK = 0
EXIT_DEVICE_CHANGED = 10
EXIT_DEVICE_LOST = 11
EXIT_PERMISSION_DENIED = 12
EXIT_UNSUPPORTED = 13
EXIT_NO_DEVICE = 14
EXIT_PERMISSION_UNAVAILABLE = 15  # macOS will not grant system audio to the app that started us

READY_TIMEOUT_S = 30.0  # mic mode may wait for the user to answer the first permission prompt
STOP_TIMEOUT_S = 2.0
MAX_LATENCY_S = 5.0  # a larger capture-to-write delay is treated as bogus host time

# Shown in errors and matched by the menu bar to offer the right System Settings page.
SYSTEM_AUDIO_PERMISSION_HINT = "System Audio Recording permission"
MICROPHONE_PERMISSION_HINT = "Microphone permission"


class HelperMissing(RuntimeError):
    """The capture helper binary is not installed / not built."""


class CapturePermissionError(PermissionError):
    """macOS denied the microphone or system audio recording permission."""


def _package_helper() -> Path:
    return Path(__file__).resolve().parent / "bin" / HELPER_NAME


def _source_tree_helper() -> Path:
    # src/audio_notes/capture/mac_tap.py -> repo root (editable / source-tree installs)
    return Path(__file__).resolve().parents[3] / "macos" / "capture" / ".build" / "release" / HELPER_NAME


def helper_candidates() -> list[Path]:
    env = os.environ.get(HELPER_ENV)
    if env:
        return [Path(env)]
    found = [_package_helper()]
    if getattr(sys, "frozen", False):  # a future .app keeps it next to the executable
        found.append(Path(sys.executable).resolve().parent / HELPER_NAME)
    found.append(_source_tree_helper())
    return found


def helper_path() -> Path:
    """Locate the helper: $AUDIO_NOTES_CAPTURE_HELPER > the wheel's capture/bin > a packaged app >
    the source tree's SwiftPM build output."""
    for p in helper_candidates():
        if p.is_file():
            if not os.access(p, os.X_OK):
                try:  # a wheel unpacked without the executable bit
                    p.chmod(p.stat().st_mode | 0o111)
                except OSError:
                    pass
            return p
    raise HelperMissing(
        f"The macOS capture helper ({HELPER_NAME}) is not installed. Reinstall with Xcode's command line "
        "tools available (xcode-select --install), or build it from the source tree with "
        "`swift build -c release --package-path macos/capture`."
    )


def default_helper_command() -> list[str]:
    return [str(helper_path())]


# ---- frames ------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Frame:
    magic: bytes
    sample_rate: int
    host_ns: int
    sent_ns: int
    samples: np.ndarray | None = None  # ANCF
    device_name: str | None = None  # ANCR


class ProtocolError(RuntimeError):
    pass


def _read_exact(stream: IO[bytes], n: int) -> bytes | None:
    """n bytes, or None at a clean EOF before the first byte. Raises on a truncated read."""
    buf = bytearray()
    while len(buf) < n:
        part = stream.read(n - len(buf))
        if not part:
            if not buf:
                return None
            raise ProtocolError(f"truncated frame ({len(buf)} of {n} bytes)")
        buf += part
    return bytes(buf)


def read_frame(stream: IO[bytes]) -> Frame | None:
    """Next frame from the helper's stdout, or None at EOF."""
    head = _read_exact(stream, HEADER.size)
    if head is None:
        return None
    magic, rate, count, _flags, host_ns, sent_ns = HEADER.unpack(head)
    if magic == MAGIC_FRAME:
        if count > MAX_SAMPLES:
            raise ProtocolError(f"implausible frame size {count}")
        payload = _read_exact(stream, count * 4) if count else b""
        if payload is None:
            raise ProtocolError("EOF inside a frame")
        return Frame(magic, rate, host_ns, sent_ns, samples=np.frombuffer(payload, dtype="<f4").astype(np.float32))
    if magic == MAGIC_READY:
        payload = _read_exact(stream, count) if count else b""
        if payload is None:
            raise ProtocolError("EOF inside the ready message")
        return Frame(magic, rate, host_ns, sent_ns, device_name=payload.decode("utf-8", "replace"))
    raise ProtocolError(f"bad frame magic {magic!r}")


def encode_frame(samples: np.ndarray, sample_rate: int, host_ns: int = 0, sent_ns: int = 0) -> bytes:
    """Inverse of `read_frame` for an audio frame (used by tests and fake helpers)."""
    data = np.asarray(samples, dtype="<f4").tobytes()
    return HEADER.pack(MAGIC_FRAME, sample_rate, len(data) // 4, 0, host_ns, sent_ns) + data


def encode_ready(sample_rate: int, device_name: str) -> bytes:
    name = device_name.encode("utf-8")
    return HEADER.pack(MAGIC_READY, sample_rate, len(name), 0, 0, 0) + name


def session_clock() -> float:
    """Seconds on a clock that keeps counting while the Mac sleeps.

    On macOS `time.monotonic()` is mach_absolute_time, which stops during sleep, so after a
    lid-close every transcript time would lag the wall clock by the sleep length (Windows'
    monotonic clock does count sleep). CLOCK_MONOTONIC on macOS is mach_continuous_time-based.
    The session origin (Recorder -> PipelineRunner) and the sources must use the same clock."""
    if sys.platform == "darwin":
        return time.clock_gettime(time.CLOCK_MONOTONIC)
    return time.monotonic()


def chunk_time(received: float, origin: float, frame: Frame) -> float:
    """Seconds since `origin` for the frame's first sample (see the module docstring)."""
    n = len(frame.samples) if frame.samples is not None else 0
    latency = (frame.sent_ns - frame.host_ns) / 1e9 if frame.host_ns and frame.sent_ns else -1.0
    if not 0.0 <= latency <= MAX_LATENCY_S:
        latency = n / frame.sample_rate if frame.sample_rate else 0.0  # Windows-style fallback
    return max(0.0, received - origin - latency)


# ---- exit codes ------------------------------------------------------------------------------
def _permission_message(mode: str) -> str:
    if mode == "tap":
        return (f"{SYSTEM_AUDIO_PERMISSION_HINT} is off for the app that started Audio Notes. Turn it on in "
                "System Settings > Privacy & Security > Screen & System Audio Recording")
    return (f"{MICROPHONE_PERMISSION_HINT} is off for the app that started Audio Notes. Turn it on in "
            "System Settings > Privacy & Security > Microphone")


def _unavailable_message(stderr_tail: str) -> str:
    """Exit 15: the helper's last line ends "... cannot be granted to <app>". Deliberately not
    SYSTEM_AUDIO_PERMISSION_HINT: an "Allow System Audio Recording…" shortcut cannot help here."""
    m = re.search(r"cannot be granted to (.+?)\s*$", stderr_tail.strip())
    app = m.group(1) if m else "the app that started Audio Notes"
    return (f"macOS does not let {app} record system audio, so Audio Notes would only record silence. "
            "Quit Audio Notes and start it from Terminal (or open the Audio Notes app) instead.")


def error_for_exit(mode: str, code: int, stderr_tail: str = "") -> Exception:
    """Map a helper exit code to the exception the recorder sees (from start() or via on_lost)."""
    detail = f": {stderr_tail}" if stderr_tail else ""
    if code == EXIT_PERMISSION_DENIED:
        return CapturePermissionError(_permission_message(mode))
    if code == EXIT_PERMISSION_UNAVAILABLE:
        return CapturePermissionError(_unavailable_message(stderr_tail))
    if code == EXIT_DEVICE_CHANGED:
        return RuntimeError("the default audio device changed")
    if code == EXIT_DEVICE_LOST:
        return RuntimeError("audio device lost or stream stopped")
    if code == EXIT_UNSUPPORTED:
        return RuntimeError("system audio capture needs macOS 14.2 or later")
    if code == EXIT_NO_DEVICE:
        return RuntimeError(f"no {'output' if mode == 'tap' else 'input'} audio device")
    return RuntimeError(f"capture helper ({mode}) exited with code {code}{detail}")


# ---- sources -----------------------------------------------------------------------------------
Popen = Callable[..., Any]


class _HelperSource(AudioSource):
    speaker: Speaker
    mode: str

    def __init__(
        self,
        helper_command: Sequence[str] | Callable[[], Sequence[str]] | None = None,
        *,
        popen: Popen = subprocess.Popen,
        ready_timeout: float = READY_TIMEOUT_S,
        stop_timeout: float = STOP_TIMEOUT_S,
        clock: Callable[[], float] = session_clock,
    ) -> None:
        self._helper_command = helper_command
        self._popen = popen
        self._ready_timeout = ready_timeout
        self._stop_timeout = stop_timeout
        self._clock = clock
        self._lock = threading.Lock()
        self._proc: Any = None
        self._stopping = threading.Event()
        self._threads: list[threading.Thread] = []
        self.device_name: str | None = None
        self.sample_rate: int | None = None

    def _command(self) -> list[str]:
        cmd = self._helper_command
        if cmd is None:
            base = default_helper_command()
        elif callable(cmd):
            base = list(cmd())
        else:
            base = list(cmd)
        return [*base, self.mode]

    def start(self, on_chunk: Callable[[AudioChunk], None], origin: float) -> None:
        with self._lock:
            if self._proc is not None:
                raise RuntimeError("source already started")
            # A fresh event per start, so a reader of a previous start never sees it cleared.
            stopping = self._stopping = threading.Event()
            proc = self._popen(
                self._command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            ready = threading.Event()
            state: dict[str, Any] = {}
            stderr_tail: list[str] = []
            reader = threading.Thread(
                target=self._read, args=(proc, on_chunk, origin, stopping, ready, state, stderr_tail),
                daemon=True, name=f"mac-capture-{self.speaker}",
            )
            errs = threading.Thread(
                target=self._drain_stderr, args=(proc, stderr_tail), daemon=True,
                name=f"mac-capture-{self.speaker}-stderr",
            )
            errs.start()
            reader.start()
            timed_out = not ready.wait(self._ready_timeout)
            if timed_out or "error" in state or "exited" in state:
                stopping.set()
                code = self._terminate(proc)
                reader.join(timeout=self._stop_timeout)
                errs.join(timeout=self._stop_timeout)
                if "error" in state:
                    raise state["error"]
                if timed_out or code is None:
                    raise RuntimeError(f"capture helper ({self.mode}) did not start within {self._ready_timeout:.0f} s")
                raise error_for_exit(self.mode, code, _tail(stderr_tail))
            self._proc = proc
            self._threads = [reader, errs]
            log.info("%s capture started on %r (%s Hz)", self.speaker, self.device_name, self.sample_rate)

    def _read(self, proc: Any, on_chunk: Callable[[AudioChunk], None], origin: float,
              stopping: threading.Event, ready: threading.Event, state: dict[str, Any],
              stderr_tail: list[str]) -> None:
        try:
            first = read_frame(proc.stdout)
            if first is None or first.magic != MAGIC_READY:
                if first is None:
                    state["exited"] = True  # EOF before ready: start() reports the exit code
                else:
                    state["error"] = ProtocolError("capture helper did not send its ready message first")
                return
            self.device_name, self.sample_rate = first.device_name, first.sample_rate
            ready.set()
            while True:
                frame = read_frame(proc.stdout)
                if frame is None:
                    break
                if frame.magic != MAGIC_FRAME or frame.samples is None or not len(frame.samples):
                    continue
                if stopping.is_set():
                    continue  # keep draining so the helper never blocks on a full pipe
                try:
                    t = chunk_time(self._clock(), origin, frame)
                    on_chunk(AudioChunk(frame.samples, frame.sample_rate, t, self.speaker))
                except Exception:
                    log.exception("%s: on_chunk failed", self.speaker)
        except Exception as e:  # noqa: BLE001
            if not ready.is_set():
                state["error"] = e
                return
            if not stopping.is_set():
                log.warning("%s: bad data from the capture helper: %s", self.speaker, e)
                try:
                    proc.kill()
                except Exception:
                    pass
        finally:
            ready.set()  # unblock start() on every path; it checks state / exit code
        if stopping.is_set():
            return
        try:
            code = proc.wait(timeout=self._stop_timeout)
        except Exception:  # noqa: BLE001
            code = -1
        if stopping.is_set():
            return
        exc = error_for_exit(self.mode, code if code is not None else -1, _tail(stderr_tail))
        handler = self.on_lost
        if handler is None:
            log.error("%s: %s; stopping this source", self.speaker, exc)
            threading.Thread(target=self.stop, daemon=True).start()
        else:
            log.warning("%s: %s", self.speaker, exc)
            handler(exc)

    def _drain_stderr(self, proc: Any, tail: list[str]) -> None:
        try:
            for raw in iter(proc.stderr.readline, b""):
                line = raw.decode("utf-8", "replace").rstrip()
                if line:
                    level = logging.WARNING if "warning:" in line else logging.INFO
                    log.log(level, "[%s helper] %s", self.speaker, line)
                    tail.append(line)
                    del tail[:-5]
        except Exception:  # noqa: BLE001
            pass

    def _terminate(self, proc: Any) -> int | None:
        """Ask the helper to exit (stdin EOF), then SIGTERM, then kill. Returns its exit code."""
        if proc.poll() is None:
            try:
                proc.stdin.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                return proc.wait(timeout=self._stop_timeout)
            except subprocess.TimeoutExpired:
                pass
            for step in (proc.terminate, proc.kill):
                try:
                    step()
                    return proc.wait(timeout=self._stop_timeout)
                except subprocess.TimeoutExpired:
                    continue
                except Exception:  # noqa: BLE001
                    break
        return proc.poll()

    def stop(self) -> None:
        self._stopping.set()
        with self._lock:
            proc, threads = self._proc, self._threads
            self._proc, self._threads = None, []
        if proc is None:
            return
        self._terminate(proc)
        for th in threads:
            if th is not threading.current_thread():
                th.join(timeout=self._stop_timeout)
        for pipe in (proc.stdout, proc.stderr):
            try:
                pipe.close()
            except Exception:  # noqa: BLE001
                pass


def _tail(lines: list[str]) -> str:
    return lines[-1] if lines else ""


class TapSource(_HelperSource):
    """System audio (Core Audio process tap of the default output) -> speaker "them"."""

    speaker: Speaker = "them"
    mode = "tap"


class MicSource(_HelperSource):
    """Default input device -> speaker "me"."""

    speaker: Speaker = "me"
    mode = "mic"


# ---- one-shot helper commands ----------------------------------------------------------------
def run_helper_json(args: Sequence[str], *, timeout: float = 15.0,
                    helper_command: Sequence[str] | None = None) -> Any:
    cmd = [*(helper_command or default_helper_command()), *args]
    r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if r.returncode != 0:
        msg = r.stderr.decode("utf-8", "replace").strip().splitlines()
        raise error_for_exit(args[0] if args else "?", r.returncode, msg[-1] if msg else "")
    return json.loads(r.stdout.decode("utf-8"))


def list_devices(helper_command: Sequence[str] | None = None) -> dict[str, list[dict[str, Any]]]:
    """{"output": [...], "input": [...]}, each device {name, uid, channels, sample_rate, default}."""
    data = run_helper_json(["list"], helper_command=helper_command)
    out: dict[str, list[dict[str, Any]]] = {"output": [], "input": []}
    for d in data.get("devices", []):
        for kind, chans, default in (("output", "outputs", "default_output"), ("input", "inputs", "default_input")):
            if int(d.get(chans) or 0) > 0:
                out[kind].append({
                    "name": d.get("name", "?"),
                    "uid": d.get("uid", ""),
                    "channels": int(d[chans]),
                    "sample_rate": int(d.get("sample_rate") or 0),
                    "default": bool(d.get(default)),
                })
    return out


@dataclass(frozen=True)
class Permissions:
    microphone: str  # authorized / denied / restricted / undetermined / unknown
    system_audio: str  # authorized / denied / undetermined / unknown (private TCC SPI missing)
    responsible: str = ""  # the app macOS credits these permissions to (e.g. Terminal, claude)

    @property
    def microphone_denied(self) -> bool:
        return self.microphone in ("denied", "restricted")

    @property
    def system_audio_denied(self) -> bool:
        return self.system_audio == "denied"


def permissions(request: bool = False, *, helper_command: Sequence[str] | None = None,
                timeout: float | None = None) -> Permissions:
    """Current permission status; with `request`, first shows the system prompts for whatever is
    still undetermined (can take as long as the user needs, hence the long timeout)."""
    args = ["permissions", "--request"] if request else ["permissions"]
    data = run_helper_json(args, helper_command=helper_command, timeout=timeout or (600.0 if request else 15.0))
    return Permissions(str(data.get("microphone", "unknown")), str(data.get("system_audio", "unknown")),
                       str(data.get("responsible", "")))
