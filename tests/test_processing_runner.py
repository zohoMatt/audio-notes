import threading
import time
import wave
from pathlib import Path

import numpy as np
import pytest
import soxr

from audio_notes.asr.base import Transcriber
from audio_notes.capture.base import AudioChunk, AudioSource
from audio_notes.processing.runner import PipelineRunner
from audio_notes.store.models import Segment

FIX = Path(__file__).parent / "fixtures"
SR = 16000


def load(name):
    with wave.open(str(FIX / name), "rb") as w:
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


def silence(sec):
    return np.zeros(int(sec * SR), dtype=np.float32)


class FakeSource(AudioSource):
    """Pushes `audio` (16 kHz) as chunks at `rate`, starting at session time `t_start`."""

    def __init__(self, speaker, audio, rate=48000, t_start=0.0, chunk_s=0.02, fail_on_start=False, bad_chunk=False):
        self.speaker = speaker
        self.rate = rate
        self.audio = soxr.resample(audio, SR, rate).astype(np.float32) if rate != SR else audio
        self.t_start = t_start
        self.chunk = int(chunk_s * rate)
        self.fail_on_start = fail_on_start
        self.bad_chunk = bad_chunk
        self.origin = None
        self.stopped = False
        self._thread = None

    def start(self, on_chunk, origin):
        if self.fail_on_start:
            raise RuntimeError("device gone")
        self.origin = origin

        def run():
            if self.bad_chunk:
                on_chunk(AudioChunk(np.array(["x"]), self.rate, 0.0, self.speaker))
            for i in range(0, len(self.audio), self.chunk):
                on_chunk(
                    AudioChunk(self.audio[i : i + self.chunk], self.rate, self.t_start + i / self.rate, self.speaker)
                )

        self._thread = threading.Thread(target=run)
        self._thread.start()

    def stop(self):
        self.stopped = True
        if self._thread:
            self._thread.join()


class MemorySink:
    def __init__(self):
        self.items = []
        self.closed = False
        self._lock = threading.Lock()

    def append(self, t0, t1, speaker, text):
        with self._lock:
            seg = Segment(len(self.items) + 1, t0, t1, speaker, text)
            self.items.append(seg)
            return seg

    def close(self):
        self.closed = True


class FakeTranscriber(Transcriber):
    def __init__(self, fail_first=0, empty_for=()):
        self.calls = []
        self.threads = set()
        self.fail_first = fail_first
        self.empty_for = empty_for

    def transcribe(self, samples):
        self.threads.add(threading.current_thread().name)
        n = len(self.calls)
        self.calls.append(len(samples))
        if n < self.fail_first:
            raise RuntimeError("boom")
        return f"utterance {n}"


def utterances(*names):
    parts = [silence(1.0)]
    for n in names:
        parts += [load(n), silence(1.0)]
    return np.concatenate(parts)


def run(sources, transcriber):
    sink = MemorySink()
    r = PipelineRunner(sources, transcriber, sink, clock=lambda: 123.0)
    r.start()
    r.stop()
    return sink


def test_two_sources_speakers_and_ordering():
    me = FakeSource("me", utterances("me_followup.wav", "me_question.wav"))
    them = FakeSource("them", utterances("them_budget.wav", "them_release.wav"), rate=44100)
    tr = FakeTranscriber()
    sink = run([me, them], tr)

    assert me.origin == them.origin == 123.0  # shared origin from the injected clock
    assert me.stopped and them.stopped
    by = {s: [x for x in sink.items if x.speaker == s] for s in ("me", "them")}
    assert len(by["me"]) == 2 and len(by["them"]) == 2
    for segs in by.values():
        assert segs[0].t0 < segs[0].t1 <= segs[1].t0 < segs[1].t1
    d_me = len(load("me_followup.wav")) / SR
    assert by["me"][0].t0 == pytest.approx(1.0, abs=0.4)
    assert by["me"][1].t0 == pytest.approx(1.0 + d_me + 1.0, abs=0.5)
    assert tr.threads == {"asr"}  # exactly one ASR worker
    assert [s.seq for s in sink.items] == [1, 2, 3, 4]


def test_timestamps_follow_chunk_t():
    src = FakeSource("them", utterances("them_budget.wav"), t_start=500.0)
    sink = run([src], FakeTranscriber())
    assert len(sink.items) == 1
    assert sink.items[0].t0 == pytest.approx(501.0, abs=0.4)


def test_stop_flushes_pending_speech():
    audio = np.concatenate([silence(0.5), load("them_budget.wav")])  # ends mid-speech
    sink = run([FakeSource("them", audio)], FakeTranscriber())
    assert len(sink.items) == 1


def test_stop_drains_queue_before_returning():
    names = ["them_budget.wav", "them_release.wav"] * 3
    slow = FakeTranscriber()
    orig = slow.transcribe

    def slow_transcribe(s):
        time.sleep(0.05)
        return orig(s)

    slow.transcribe = slow_transcribe
    sink = run([FakeSource("them", utterances(*names))], slow)
    assert len(sink.items) == 6


def test_empty_text_is_skipped():
    class Empty(Transcriber):
        def transcribe(self, samples):
            return "  "

    sink = run([FakeSource("me", utterances("me_followup.wav"))], Empty())
    assert sink.items == []


def test_transcriber_error_does_not_kill_worker():
    tr = FakeTranscriber(fail_first=1)
    sink = run([FakeSource("them", utterances("them_budget.wav", "them_release.wav"))], tr)
    assert len(tr.calls) == 2
    assert [s.text for s in sink.items] == ["utterance 1"]


def test_source_start_failure_is_isolated():
    bad = FakeSource("me", utterances("me_followup.wav"), fail_on_start=True)
    good = FakeSource("them", utterances("them_budget.wav"))
    sink = run([bad, good], FakeTranscriber())
    assert [s.speaker for s in sink.items] == ["them"]


def test_bad_chunk_is_isolated():
    bad = FakeSource("me", utterances("me_followup.wav"), bad_chunk=True)
    good = FakeSource("them", utterances("them_budget.wav"))
    sink = run([bad, good], FakeTranscriber())
    speakers = sorted(s.speaker for s in sink.items)
    assert "them" in speakers


def test_sink_error_does_not_kill_worker():
    class FlakySink(MemorySink):
        def append(self, *a):
            if not self.items and not getattr(self, "tried", False):
                self.tried = True
                raise OSError("disk")
            return super().append(*a)

    sink = FlakySink()
    r = PipelineRunner([FakeSource("them", utterances("them_budget.wav", "them_release.wav"))], FakeTranscriber(), sink)
    r.start()
    r.stop()
    assert len(sink.items) == 1


def test_stop_without_start_and_double_stop():
    r = PipelineRunner([], FakeTranscriber(), MemorySink())
    r.stop()
    r.start()
    r.stop()
    r.stop()
