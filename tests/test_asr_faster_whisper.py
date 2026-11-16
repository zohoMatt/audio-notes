import json
import re
import wave
from pathlib import Path

import numpy as np
import pytest

from audio_notes.config import Config

FIX = Path(__file__).parent / "fixtures"
MANIFEST = json.loads((FIX / "manifest.json").read_text(encoding="utf-8"))


def load(name):
    with wave.open(str(FIX / name), "rb") as w:
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


def words(s):
    return re.findall(r"[a-z0-9']+", s.lower())


def wer(ref, hyp):
    r, h = words(ref), words(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev, d[j] = d[j], cur
    return d[len(h)] / max(len(r), 1)


@pytest.fixture(scope="module")
def tiny():
    from audio_notes.asr.faster_whisper_engine import FasterWhisperTranscriber

    return FasterWhisperTranscriber(Config(model="tiny.en"))


@pytest.mark.slow
@pytest.mark.parametrize("name", sorted(MANIFEST))
def test_transcribes_fixture(tiny, name):
    text = tiny.transcribe(load(name))
    assert wer(MANIFEST[name]["text"], text) <= 0.35, text


@pytest.mark.slow
def test_silence_gives_empty_or_short(tiny):
    text = tiny.transcribe(np.zeros(16000 * 2, dtype=np.float32))
    assert len(words(text)) <= 3
