"""Recorder end to end without audio hardware or the real ASR model.

Real FileSource -> real resampler/VAD -> fake transcriber -> real SessionWriter -> real StoreReader.
"""

import threading
import time
from pathlib import Path

import pytest

from audio_notes.capture.base import AudioSource
from audio_notes.capture.file_source import FileSource
from audio_notes.recorder import Recorder
from audio_notes.store.reader import StoreReader

FIX = Path(__file__).parent / "fixtures"


class FakeTranscriber:
    """No `load`, like a test double; returns a fixed text."""

    def transcribe(self, samples):
        return "some words"


class LoadingTranscriber(FakeTranscriber):
    def __init__(self):
        self.downloading_seen = None
        self.recorder = None

    def load(self):
        self.downloading_seen = self.recorder.is_downloading_model()


class SilentSource(AudioSource):
    """Opens and closes without producing audio; `fail` makes the next start() raise."""

    def __init__(self, speaker):
        self.speaker = speaker
        self.starts = self.stops = 0
        self.fail = False

    def start(self, on_chunk, origin):
        if self.fail:
            raise RuntimeError(f"no {self.speaker} device")
        self.starts += 1

    def stop(self):
        self.stops += 1


class FailingSource(AudioSource):
    def __init__(self, speaker):
        self.speaker = speaker

    def start(self, on_chunk, origin):
        raise RuntimeError(f"no {self.speaker} device")

    def stop(self):
        pass


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIO_NOTES_DATA_DIR", str(tmp_path))
    return tmp_path


def _files():
    return [
        FileSource(FIX / "them_budget.wav", "them", realtime=False),
        FileSource(FIX / "me_followup.wav", "me", realtime=False),
    ]


def test_two_files_become_labelled_segments():
    sources = _files()
    rec = Recorder(source_factory=lambda mic: sources, transcriber=FakeTranscriber())
    rec.start()
    assert rec.is_recording() and rec.session_id
    for s in sources:
        s.join()
    rec.stop()
    assert not rec.is_recording() and rec.last_error() is None

    segs, cursor = StoreReader().read_segments(rec.session_id if rec.session_id else None)
    assert segs, "nothing was transcribed"
    assert {s.speaker for s in segs} == {"me", "them"}
    assert [s.seq for s in segs] == list(range(1, len(segs) + 1)) and cursor == len(segs)
    assert all(0 <= s.t0 < s.t1 for s in segs)
    st = StoreReader().read_status()
    assert st.recording is False


def test_session_is_readable_while_recording_and_closed_after():
    sources = _files()
    rec = Recorder(source_factory=lambda mic: sources, transcriber=FakeTranscriber())
    rec.start()
    sid = rec.session_id
    for s in sources:
        s.join()
    rec.stop()
    assert rec.session_id is None  # session is closed
    sessions = StoreReader().list_sessions()
    assert [s.id for s in sessions] == [sid] and sessions[0].is_active is False


def test_pause_keeps_the_session_and_resume_continues_it():
    them, me = SilentSource("them"), SilentSource("me")
    rec = Recorder(source_factory=lambda mic: [them, me], transcriber=FakeTranscriber())
    rec.pause()  # not recording: no-op
    rec.start()
    sid = rec.session_id
    rec.pause()
    assert rec.is_recording() and rec.is_paused() and them.stops == me.stops == 1
    st = StoreReader().read_status()
    assert st.recording and st.paused and st.session_id == sid
    info = StoreReader().list_sessions()[0]
    assert info.is_active and info.is_paused and info.stream == 1
    rec.pause()  # idempotent
    assert them.stops == 1

    them.fail = True  # system audio gone while paused: continue fails, the session stays paused
    with pytest.raises(RuntimeError):
        rec.resume()
    assert rec.is_paused() and "Cannot capture audio" in rec.last_error()
    them.fail = False
    rec.resume()
    assert not rec.is_paused() and rec.last_error() is None and rec.session_id == sid
    assert them.starts == 2 and not StoreReader().read_status().paused

    rec.pause()
    rec.stop()  # stop works while paused
    assert not rec.is_recording() and not rec.is_paused()
    st = StoreReader().read_status()
    assert not st.recording and not st.paused
    rec.start()
    assert rec.session_id != sid  # after stop, only a new session
    rec.stop()


def test_mic_flag_reaches_the_source_factory():
    seen = []

    def factory(mic):
        seen.append(mic)
        return [FileSource(FIX / "them_budget.wav", "them", realtime=False)]

    rec = Recorder(source_factory=factory, transcriber=FakeTranscriber())
    rec.set_mic_enabled(False)
    rec.start()
    rec.stop()
    rec.set_mic_enabled(True)
    rec.start()
    rec.stop()
    assert seen == [False, True]


def test_missing_system_audio_is_a_hard_error_and_recoverable():
    state = {"broken": True}

    def factory(mic):
        if state["broken"]:
            return [FailingSource("them"), FileSource(FIX / "me_followup.wav", "me", realtime=False)]
        return [FileSource(FIX / "them_budget.wav", "them", realtime=False)]

    rec = Recorder(source_factory=factory, transcriber=FakeTranscriber())
    with pytest.raises(RuntimeError, match="no them device"):
        rec.start()
    assert not rec.is_recording()
    assert "no them device" in (rec.last_error() or "")
    assert StoreReader().read_status().recording is False  # the half-opened session was closed

    state["broken"] = False
    rec.start()  # a later start clears the error
    assert rec.is_recording() and rec.last_error() is None
    rec.stop()


def test_missing_microphone_only_degrades():
    sources = [FileSource(FIX / "them_budget.wav", "them", realtime=False), FailingSource("me")]
    rec = Recorder(source_factory=lambda mic: sources, transcriber=FakeTranscriber())
    rec.start()
    assert rec.is_recording() and rec.last_error() is None
    sources[0].join()
    rec.stop()
    segs, _ = StoreReader().read_segments(None)
    assert segs and {s.speaker for s in segs} == {"them"}


def test_model_download_is_reported_while_loading():
    t = LoadingTranscriber()
    rec = Recorder(
        source_factory=lambda mic: [FileSource(FIX / "them_budget.wav", "them", realtime=False)],
        transcriber=t,
        model_cached=lambda name: False,
    )
    t.recorder = rec
    rec.start()
    assert t.downloading_seen is True
    assert rec.is_downloading_model() is False  # cleared once loading is done
    rec.stop()


def test_stop_is_idempotent_and_safe_before_start():
    rec = Recorder(source_factory=lambda mic: _files(), transcriber=FakeTranscriber())
    rec.stop()
    rec.start()
    rec.stop()
    rec.stop()


class BlockingTranscriber(FakeTranscriber):
    """`load()` blocks until released, like a first-run model download."""

    def __init__(self):
        self.release = threading.Event()
        self.loading = threading.Event()

    def load(self):
        self.loading.set()
        self.release.wait(10)


def test_stop_does_not_wait_for_a_model_download_and_cancels_the_start():
    t = BlockingTranscriber()
    rec = Recorder(source_factory=lambda mic: _files(), transcriber=t, model_cached=lambda n: False)
    th = threading.Thread(target=rec.start)
    th.start()
    assert t.loading.wait(5)
    assert rec.is_downloading_model()
    t0 = time.monotonic()
    rec.stop()  # used to block on the recorder lock until the download finished
    rec.start()  # a second start while one is loading is a no-op, not a second load
    assert time.monotonic() - t0 < 1.0
    t.release.set()
    th.join(5)
    assert not rec.is_recording() and rec.last_error() is None
    assert StoreReader().list_sessions() == []  # the cancelled start opened no session


class LosableSource(AudioSource):
    def __init__(self, speaker, broken_after=None):
        self.speaker = speaker
        self.starts = 0
        self.broken = False

    def start(self, on_chunk, origin):
        self.starts += 1
        if self.broken:
            raise RuntimeError(f"no {self.speaker} device")

    def stop(self):
        pass

    def lose(self):
        self.on_lost(RuntimeError("default device changed"))


def _wait(cond, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_lost_device_is_rebound_and_a_failed_rebind_is_reported_then_retried():
    them = LosableSource("them")
    rec = Recorder(source_factory=lambda mic: [them], transcriber=FakeTranscriber(),
                   recover_delay=0.01, retry_interval=0.05)
    rec.start()
    them.lose()
    assert _wait(lambda: them.starts == 2)  # re-opened on the (new) default device
    assert rec.is_recording() and rec.last_error() is None

    them.broken = True
    them.lose()
    assert _wait(lambda: "retrying" in (rec.last_error() or ""))
    assert rec.is_recording()  # still a session; the tray shows the error with a Stop item
    n = them.starts
    assert _wait(lambda: them.starts > n)  # keeps retrying
    them.broken = False
    assert _wait(lambda: rec.last_error() is None)
    rec.stop()
    assert not rec.is_recording()


def test_stop_during_failed_rebind_clears_the_capture_error():
    them = LosableSource("them")
    rec = Recorder(source_factory=lambda mic: [them], transcriber=FakeTranscriber(),
                   recover_delay=0.01, retry_interval=10)
    rec.start()
    them.broken = True
    them.lose()
    assert _wait(lambda: rec.last_error() is not None)
    t0 = time.monotonic()
    rec.stop()
    assert time.monotonic() - t0 < 2  # does not sit out the retry interval
    assert rec.last_error() is None and not rec.is_recording()
