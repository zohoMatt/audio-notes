"""macOS capture (capture/mac_tap.py) against a fake helper process: runs on any platform."""

import io
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from audio_notes.capture import mac_tap
from audio_notes.capture.mac_tap import (
    CapturePermissionError,
    Frame,
    MicSource,
    ProtocolError,
    TapSource,
    chunk_time,
    encode_frame,
    encode_ready,
    read_frame,
)

FAKE = [sys.executable, str(Path(__file__).with_name("fake_mac_helper.py"))]


@pytest.fixture
def scenario(monkeypatch):
    def set_(name: str) -> None:
        monkeypatch.setenv("FAKE_HELPER_SCENARIO", name)

    set_("normal")
    return set_


class Collector:
    def __init__(self):
        self.chunks = []
        self.lost = []
        self.got = threading.Event()

    def on_chunk(self, chunk):
        self.chunks.append(chunk)
        if len(self.chunks) >= 3:
            self.got.set()

    def on_lost(self, exc):
        self.lost.append(exc)
        self.got.set()


# ---- wire format -------------------------------------------------------------------------------
def test_frame_roundtrip():
    samples = np.linspace(-1, 1, 7, dtype=np.float32)
    buf = io.BytesIO(encode_ready(44100, "Speakers é") + encode_frame(samples, 44100, 5, 9))
    ready = read_frame(buf)
    assert ready.magic == b"ANCR" and ready.sample_rate == 44100 and ready.device_name == "Speakers é"
    frame = read_frame(buf)
    assert frame.magic == b"ANCF" and frame.host_ns == 5 and frame.sent_ns == 9
    np.testing.assert_array_equal(frame.samples, samples)
    assert frame.samples.dtype == np.float32
    assert read_frame(buf) is None  # clean EOF


def test_header_layout_matches_the_swift_side():
    # Protocol.swift: 32-byte little-endian header "magic, rate, count, flags, host_ns, sent_ns"
    raw = encode_frame(np.zeros(2, np.float32), 48000, host_ns=1, sent_ns=2)
    assert mac_tap.HEADER.size == 32 and len(raw) == 32 + 8
    assert raw[:4] == b"ANCF" and int.from_bytes(raw[4:8], "little") == 48000
    assert int.from_bytes(raw[8:12], "little") == 2


def test_bad_magic_and_truncation_raise():
    with pytest.raises(ProtocolError):
        read_frame(io.BytesIO(b"XXXX" * 8))
    with pytest.raises(ProtocolError):
        read_frame(io.BytesIO(encode_frame(np.zeros(10, np.float32), 16000)[:-3]))


def test_chunk_time_backdates_by_the_helpers_latency():
    f = Frame(b"ANCF", 48000, host_ns=1_000_000_000, sent_ns=1_020_000_000, samples=np.zeros(480, np.float32))
    assert chunk_time(received=12.5, origin=2.5, frame=f) == pytest.approx(10.0 - 0.02)
    # no host time: Windows-style fallback (duration of the frame)
    f0 = Frame(b"ANCF", 48000, host_ns=0, sent_ns=5, samples=np.zeros(480, np.float32))
    assert chunk_time(12.5, 2.5, f0) == pytest.approx(10.0 - 0.01)
    # bogus host time (latency far too large or negative) falls back as well; never negative
    bogus = Frame(b"ANCF", 48000, host_ns=1, sent_ns=60 * 10**9, samples=np.zeros(480, np.float32))
    assert chunk_time(12.5, 2.5, bogus) == pytest.approx(10.0 - 0.01)
    assert chunk_time(0.0, 2.5, f) == 0.0


def test_exit_codes_map_to_errors():
    assert isinstance(mac_tap.error_for_exit("tap", 12), CapturePermissionError)
    assert mac_tap.SYSTEM_AUDIO_PERMISSION_HINT in str(mac_tap.error_for_exit("tap", 12))
    assert mac_tap.MICROPHONE_PERMISSION_HINT in str(mac_tap.error_for_exit("mic", 12))
    assert "default audio device changed" in str(mac_tap.error_for_exit("tap", 10))
    assert "14.2" in str(mac_tap.error_for_exit("tap", 13))
    assert "boom" in str(mac_tap.error_for_exit("mic", 1, "boom"))


# ---- sources against the fake helper -----------------------------------------------------------
def test_tap_source_streams_chunks_and_stops(scenario):
    src = TapSource(FAKE, ready_timeout=10)
    c = Collector()
    src.on_lost = c.on_lost
    origin = mac_tap.session_clock()  # the sources' clock
    src.start(c.on_chunk, origin)
    try:
        assert src.device_name == "Fake Output" and src.sample_rate == 48000
        assert c.got.wait(10)
    finally:
        src.stop()
    assert c.lost == []  # a requested stop is not a lost device
    ch = c.chunks[0]
    assert ch.speaker == "them" and ch.sample_rate == 48000 and len(ch.samples) == 480
    assert ch.samples.dtype == np.float32 and float(ch.samples[0]) == pytest.approx(0.25)
    assert 0.0 <= ch.t < 10.0
    assert all(b.t >= a.t for a, b in zip(c.chunks, c.chunks[1:]))
    n = len(c.chunks)
    time.sleep(0.1)
    assert len(c.chunks) == n  # nothing after stop()


def test_mic_source_is_me_and_can_restart(scenario):
    src = MicSource(FAKE, ready_timeout=10)
    for _ in range(2):  # start() may be called again after stop()
        c = Collector()
        src.start(c.on_chunk, time.monotonic())
        try:
            assert c.got.wait(10)
        finally:
            src.stop()
        assert c.chunks[0].speaker == "me" and float(c.chunks[0].samples[0]) == pytest.approx(-0.5)


def test_start_twice_raises(scenario):
    src = TapSource(FAKE, ready_timeout=10)
    src.start(lambda c: None, time.monotonic())
    try:
        with pytest.raises(RuntimeError, match="already started"):
            src.start(lambda c: None, time.monotonic())
    finally:
        src.stop()


def test_permission_denied_fails_start_with_a_readable_error(scenario):
    scenario("permission")
    with pytest.raises(CapturePermissionError) as e:
        TapSource(FAKE, ready_timeout=10).start(lambda c: None, time.monotonic())
    assert "Screen & System Audio Recording" in str(e.value)


def test_ungrantable_launch_app_fails_start_and_names_it(scenario):
    from audio_notes.tray.mac_menu import missing_permissions

    scenario("unavailable")
    with pytest.raises(CapturePermissionError) as e:
        TapSource(FAKE, ready_timeout=10).start(lambda c: None, time.monotonic())
    msg = str(e.value)
    assert "does not let claude record system audio" in msg and "Terminal" in msg
    # an "Allow System Audio Recording…" shortcut cannot help here, so the menu must not offer it
    assert missing_permissions(msg, None, mic_on=False) == (False, False)


def test_device_change_after_start_reports_on_lost(scenario):
    scenario("device_change")
    src = TapSource(FAKE, ready_timeout=10)
    c = Collector()
    src.on_lost = c.on_lost
    src.start(c.on_chunk, time.monotonic())
    try:
        deadline = time.monotonic() + 10
        while not c.lost and time.monotonic() < deadline:
            time.sleep(0.02)
    finally:
        src.stop()
    assert len(c.lost) == 1 and "default audio device changed" in str(c.lost[0])


def test_garbage_after_start_is_reported_as_lost(scenario):
    scenario("garbage")
    src = TapSource(FAKE, ready_timeout=10, stop_timeout=2)
    c = Collector()
    src.on_lost = c.on_lost
    src.start(c.on_chunk, time.monotonic())
    try:
        deadline = time.monotonic() + 10
        while not c.lost and time.monotonic() < deadline:
            time.sleep(0.02)
    finally:
        src.stop()
    assert len(c.lost) == 1


def test_ready_timeout_kills_the_helper(scenario):
    scenario("hang")
    with pytest.raises(RuntimeError, match="did not start"):
        TapSource(FAKE, ready_timeout=0.5, stop_timeout=2).start(lambda c: None, time.monotonic())


def test_stop_escalates_when_the_helper_ignores_stdin(scenario):
    scenario("ignore_stdin")
    src = TapSource(FAKE, ready_timeout=10, stop_timeout=0.5)
    src.start(lambda c: None, time.monotonic())
    t0 = time.monotonic()
    src.stop()
    assert time.monotonic() - t0 < 5


def test_missing_helper_explains_how_to_build_it(monkeypatch, tmp_path):
    monkeypatch.setenv(mac_tap.HELPER_ENV, str(tmp_path / "nope"))
    with pytest.raises(mac_tap.HelperMissing, match="swift build"):
        mac_tap.helper_path()
    with pytest.raises(mac_tap.HelperMissing):
        TapSource().start(lambda c: None, time.monotonic())


def test_helper_lookup_prefers_the_env_override(monkeypatch, tmp_path):
    exe = tmp_path / "audio-notes-capture"
    exe.write_text("x")
    monkeypatch.setenv(mac_tap.HELPER_ENV, str(exe))
    assert mac_tap.helper_path() == exe
    monkeypatch.delenv(mac_tap.HELPER_ENV)
    cands = mac_tap.helper_candidates()
    assert cands[0].parts[-3:] == ("capture", "bin", "audio-notes-capture")
    assert cands[-1].parts[-5:] == ("macos", "capture", ".build", "release", "audio-notes-capture")


# ---- one-shot commands -------------------------------------------------------------------------
def test_list_devices_groups_outputs_and_inputs():
    found = mac_tap.list_devices(helper_command=FAKE)
    assert [d["name"] for d in found["output"]] == ["MacBook Speakers", "USB Headset"]
    assert [d["name"] for d in found["input"]] == ["MacBook Microphone", "USB Headset"]
    assert found["output"][0]["default"] and not found["output"][1]["default"]
    assert found["input"][1] == {"name": "USB Headset", "uid": "usb", "channels": 1, "sample_rate": 44100,
                                 "default": False}


def test_permissions(monkeypatch):
    monkeypatch.setenv("FAKE_MIC", "authorized")
    monkeypatch.setenv("FAKE_SYSTEM_AUDIO", "denied")
    monkeypatch.setenv("FAKE_RESPONSIBLE", "iTerm")
    p = mac_tap.permissions(helper_command=FAKE)
    assert p.system_audio_denied and not p.microphone_denied and p.responsible == "iTerm"
    monkeypatch.setenv("FAKE_MIC", "restricted")
    assert mac_tap.permissions(helper_command=FAKE).microphone_denied


# ---- recorder wiring ---------------------------------------------------------------------------
def test_recorder_picks_the_mac_sources_on_darwin(monkeypatch):
    from audio_notes import recorder

    monkeypatch.setattr(sys, "platform", "darwin")
    srcs = recorder.default_sources(True)
    assert [type(s) for s in srcs] == [TapSource, MicSource]
    assert [s.speaker for s in srcs] == ["them", "me"]
    assert [type(s) for s in recorder.default_sources(False)] == [TapSource]


def test_recorder_records_from_the_fake_helper_and_recovers_from_a_device_change(tmp_path, monkeypatch, scenario):
    """End to end through Recorder + PipelineRunner: a device change (exit 10) re-binds the
    sources, and recording carries on in the same session."""
    from audio_notes.recorder import Recorder

    monkeypatch.setenv("AUDIO_NOTES_DATA_DIR", str(tmp_path))
    starts = []

    class CountingTap(TapSource):
        def start(self, on_chunk, origin):
            starts.append(time.monotonic())
            scenario("device_change" if len(starts) == 1 else "normal")
            super().start(on_chunk, origin)

    class NoAsr:
        def transcribe(self, samples):
            return ""

    rec = Recorder(source_factory=lambda mic: [CountingTap(FAKE, ready_timeout=10)], transcriber=NoAsr(),
                   model_cached=lambda m: True, recover_delay=0.05, retry_interval=0.1)
    rec.start()
    try:
        deadline = time.monotonic() + 15
        while len(starts) < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert len(starts) >= 2, "the source was not re-opened after the device change"
        assert rec.is_recording() and rec.last_error() is None
    finally:
        rec.stop()


# ---- clocks --------------------------------------------------------------------------------------
def test_session_clock_counts_through_sleep_on_macos():
    # time.monotonic() is mach_absolute_time on macOS and stops while the Mac sleeps; the session
    # clock must not, or transcript times lag the wall clock by the sleep length after a wake.
    if sys.platform == "darwin":
        assert abs(mac_tap.session_clock() - time.clock_gettime(time.CLOCK_MONOTONIC)) < 0.5
    else:
        assert abs(mac_tap.session_clock() - time.monotonic()) < 0.5
    assert TapSource()._clock is mac_tap.session_clock
    assert MicSource()._clock is mac_tap.session_clock


def test_recorder_session_origin_uses_the_sources_clock(monkeypatch):
    import audio_notes.recorder as recorder_mod

    monkeypatch.setattr(recorder_mod.sys, "platform", "darwin")
    assert recorder_mod.default_clock() is mac_tap.session_clock
    monkeypatch.setattr(recorder_mod.sys, "platform", "win32")
    assert recorder_mod.default_clock() is time.monotonic


def test_permission_errors_keep_the_settings_path():
    # Seen on a real Mac: the 160-char cut ended the message at "Screen & System Audio Rec...".
    from audio_notes.recorder import Recorder, capture_problem

    for mode, page in (("tap", "Screen & System Audio Recording"), ("mic", "Privacy & Security > Microphone")):
        problem = capture_problem({"them": mac_tap.error_for_exit(mode, mac_tap.EXIT_PERMISSION_DENIED)}, 2)
        assert problem and problem.endswith(page)

    class Failing:
        def load(self):
            raise RuntimeError(capture_problem({"them": mac_tap.error_for_exit("tap", 12)}, 2))

    rec = Recorder(transcriber=Failing(), model_cached=lambda m: True)
    with pytest.raises(RuntimeError):
        rec.start()
    assert rec.last_error().endswith("Screen & System Audio Recording")
