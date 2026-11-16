"""Recorder end to end without audio hardware or the real ASR model.

Real FileSource -> real resampler/VAD -> fake transcriber -> real SessionWriter -> real StoreReader.
"""

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
