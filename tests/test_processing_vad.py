import json
import wave
from pathlib import Path

import numpy as np
import pytest

from audio_notes.processing.resample import StreamResampler, resample_to_16k
from audio_notes.processing.vad import VadSegmenter

FIX = Path(__file__).parent / "fixtures"
MANIFEST = json.loads((FIX / "manifest.json").read_text(encoding="utf-8"))
SR = 16000


def load(name: str) -> np.ndarray:
    with wave.open(str(FIX / name), "rb") as w:
        assert w.getframerate() == SR and w.getnchannels() == 1
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


def trim(a: np.ndarray) -> np.ndarray:
    """Cut the silent tail TTS leaves at the end of a file."""
    return a[: np.nonzero(np.abs(a) > 0.01)[0][-1] + 1]


def silence(sec: float) -> np.ndarray:
    return np.zeros(int(sec * SR), dtype=np.float32)


def run_vad(audio: np.ndarray, start: float = 0.0, chunk: int = 1600):
    vad = VadSegmenter()
    vad.reset(start)
    segs = []
    for i in range(0, len(audio), chunk):
        segs += vad.feed(audio[i : i + chunk])
    return vad, segs


@pytest.mark.parametrize("name", sorted(MANIFEST))
def test_fixture_is_one_segment(name):
    speech = load(name)
    audio = np.concatenate([silence(1.0), speech, silence(1.5)])
    vad, segs = run_vad(audio)
    segs += vad.flush()
    assert len(segs) == 1
    s = segs[0]
    dur = len(speech) / SR
    assert 0.7 <= s.t0 <= 1.2
    assert dur * 0.8 <= (s.t1 - s.t0) <= dur + 1.0
    assert len(s.samples) == pytest.approx((s.t1 - s.t0) * SR, abs=1)


def test_pure_silence_yields_nothing():
    vad, segs = run_vad(silence(5.0))
    assert segs == [] and vad.flush() == []


def test_low_noise_yields_nothing():
    rng = np.random.default_rng(0)
    noise = (rng.standard_normal(SR * 3) * 0.003).astype(np.float32)
    vad, segs = run_vad(noise)
    assert segs + vad.flush() == []


def test_start_time_offset():
    speech = load("them_budget.wav")
    audio = np.concatenate([silence(1.0), speech, silence(1.5)])
    _, segs = run_vad(audio, start=100.0)
    assert len(segs) == 1 and 100.7 <= segs[0].t0 <= 101.2


def test_two_utterances_split_on_silence():
    a, b = load("them_budget.wav"), load("them_release.wav")
    audio = np.concatenate([silence(0.5), a, silence(1.0), b, silence(1.0)])
    _, segs = run_vad(audio)
    assert len(segs) == 2
    assert segs[0].t1 <= segs[1].t0


def test_short_pause_does_not_split():
    a = trim(load("them_budget.wav"))  # exact 0.2 s gap, no TTS tail
    audio = np.concatenate([silence(0.5), a, silence(0.2), a, silence(1.0)])
    _, segs = run_vad(audio)
    assert len(segs) == 1


def test_blip_is_dropped():
    speech = load("me_followup.wav")
    # take ~100 ms from the middle of an utterance: too short to count as speech
    blip = speech[SR : SR + int(0.1 * SR)]
    audio = np.concatenate([silence(1.0), blip, silence(1.5)])
    vad, segs = run_vad(audio)
    assert segs + vad.flush() == []


def test_flush_returns_pending_speech():
    speech = trim(load("them_budget.wav"))
    audio = np.concatenate([silence(0.5), speech])  # no trailing silence
    vad, segs = run_vad(audio)
    assert segs == []
    flushed = vad.flush()
    assert len(flushed) == 1
    assert vad.flush() == []


def test_long_speech_is_force_cut():
    a = load("them_release.wav")
    audio = np.concatenate([np.concatenate([a, silence(0.1)]) for _ in range(9)])
    assert len(audio) / SR > 28
    vad, segs = run_vad(audio)
    segs += vad.flush()
    assert len(segs) >= 2
    assert all((s.t1 - s.t0) <= 25.2 for s in segs)
    # segments are contiguous / non-overlapping and cover the audio
    for p, n in zip(segs, segs[1:]):
        assert p.t1 <= n.t0 + 1e-6
    assert segs[-1].t1 >= len(audio) / SR - 1.0


def test_chunking_does_not_change_result():
    speech = load("me_question.wav")
    audio = np.concatenate([silence(1.0), speech, silence(1.5)])
    _, s1 = run_vad(audio, chunk=1600)
    _, s2 = run_vad(audio, chunk=777)
    assert len(s1) == len(s2) == 1
    assert s1[0].t0 == pytest.approx(s2[0].t0, abs=0.04)
    assert s1[0].t1 == pytest.approx(s2[0].t1, abs=0.04)


# -- resampling ----------------------------------------------------------


def test_resample_length_and_mono():
    x = np.random.default_rng(1).standard_normal((48000, 2)).astype(np.float32)
    y = resample_to_16k(x, 48000)
    assert y.dtype == np.float32 and y.ndim == 1
    assert len(y) == pytest.approx(16000, abs=2)
    assert resample_to_16k(x[:, 0], 16000).shape == (48000,)


def test_stream_resampler_matches_total_length():
    speech = load("them_budget.wav")
    up = resample_to_16k(speech, 16000)
    import soxr

    x48 = soxr.resample(up, 16000, 48000)
    rs = StreamResampler()
    out = [rs.process(x48[i : i + 960], 48000) for i in range(0, len(x48), 960)]
    out.append(rs.flush())
    y = np.concatenate(out)
    assert len(y) == pytest.approx(len(up), abs=64)
