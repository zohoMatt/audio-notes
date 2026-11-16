import sys
import time

import numpy as np
import pytest

pytestmark = [
    pytest.mark.hardware,
    pytest.mark.skipif(sys.platform != "win32", reason="Windows only"),
]


def _tone_wav(path, seconds=2.0, rate=44100, freq=880):
    import wave

    t = np.arange(int(seconds * rate)) / rate
    pcm = (0.3 * np.sin(2 * np.pi * freq * t) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def test_loopback_receives_tone_and_silence_behaviour(tmp_path, capsys):
    import winsound

    from audio_notes.capture.win_wasapi import LoopbackSource

    chunks = []
    origin = time.monotonic()
    src = LoopbackSource()
    src.start(chunks.append, origin)
    try:
        # silence phase: loopback may deliver nothing at all
        time.sleep(1.0)
        silent_n = len(chunks)

        wav = tmp_path / "tone.wav"
        _tone_wav(wav)
        winsound.PlaySound(str(wav), winsound.SND_FILENAME | winsound.SND_ASYNC)
        time.sleep(2.5)
    finally:
        src.stop()
        src.stop()  # idempotent
    winsound.PlaySound(None, winsound.SND_PURGE)

    assert len(chunks) > silent_n, "no frames arrived while tone played"
    loud = [c for c in chunks if c.samples.size and np.abs(c.samples).max() > 1e-3]
    assert loud, "tone not audible in loopback (is system volume muted?)"
    assert all(c.speaker == "them" and c.samples.dtype == np.float32 and c.samples.ndim == 1 for c in chunks)
    ts = [c.t for c in chunks]
    assert ts == sorted(ts) and ts[0] >= 0
    with capsys.disabled():
        print(f"\n[hardware] chunks during 1s silence: {silent_n}; total: {len(chunks)}; loud chunks: {len(loud)}")
