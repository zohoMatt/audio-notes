import threading
import time
import wave

import numpy as np
import pytest

from audio_notes.capture.file_source import FileSource


def write_wav(path, data, rate=16000, ch=1):
    pcm = (np.asarray(data) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def run(src, timeout=10):
    chunks = []
    src.start(chunks.append, time.monotonic())
    assert src.join(timeout)
    return chunks


def test_chunking_and_timestamps(tmp_path):
    p = tmp_path / "a.wav"
    write_wav(p, np.zeros(16000 * 1), 16000)  # 1 s
    chunks = run(FileSource(p, "me", realtime=False, chunk_ms=100, start_offset=5.0))
    assert len(chunks) == 10
    assert all(len(c.samples) == 1600 for c in chunks)
    assert all(c.speaker == "me" and c.sample_rate == 16000 for c in chunks)
    assert [round(c.t, 6) for c in chunks] == [round(5.0 + i * 0.1, 6) for i in range(10)]
    assert chunks[0].samples.dtype == np.float32


def test_last_partial_chunk(tmp_path):
    p = tmp_path / "a.wav"
    write_wav(p, np.zeros(2500), 16000)
    chunks = run(FileSource(p, "them", realtime=False))
    assert [len(c.samples) for c in chunks] == [1600, 900]
    assert chunks[1].t == pytest.approx(0.1)


def test_stereo_downmix_and_native_rate(tmp_path):
    p = tmp_path / "s.wav"
    n = 4410
    data = np.stack([np.full(n, 0.5), np.full(n, -0.25)], axis=1)
    write_wav(p, data, 44100, 2)
    chunks = run(FileSource(p, "them", realtime=False))
    assert all(c.sample_rate == 44100 for c in chunks)
    x = np.concatenate([c.samples for c in chunks])
    assert x.ndim == 1 and len(x) == n
    assert np.allclose(x, 0.125, atol=1e-3)


def test_fast_vs_realtime(tmp_path):
    p = tmp_path / "a.wav"
    write_wav(p, np.zeros(16000), 16000)  # 1 s
    t = time.monotonic()
    run(FileSource(p, "me", realtime=False))
    assert time.monotonic() - t < 0.5
    t = time.monotonic()
    run(FileSource(p, "me", realtime=True))
    assert time.monotonic() - t >= 0.8


def test_stop_midway_and_idempotent(tmp_path):
    p = tmp_path / "a.wav"
    write_wav(p, np.zeros(16000 * 10), 16000)
    chunks = []
    src = FileSource(p, "me", realtime=True)
    src.start(chunks.append, time.monotonic())
    time.sleep(0.35)
    src.stop()
    src.stop()
    n = len(chunks)
    assert 1 <= n < 20
    time.sleep(0.2)
    assert len(chunks) == n
    assert threading.active_count() >= 1
