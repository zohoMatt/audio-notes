import json
import threading
import time
from datetime import datetime

import pytest

from audio_notes import paths
from audio_notes.store.reader import StoreReader
from audio_notes.store.writer import SessionWriter


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIO_NOTES_DATA_DIR", str(tmp_path))
    return tmp_path


def test_writer_assigns_seq_and_writes_jsonl():
    w = SessionWriter(datetime(2026, 1, 2, 3, 4, 5))
    a = w.append(0.0, 1.0, "me", "héllo 你好")
    b = w.append(1.0, 2.0, "them", "world")
    w.close()
    assert (a.seq, b.seq) == (1, 2)
    lines = w.path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["seq"] for x in lines] == [1, 2]
    assert w.session_id == "2026-01-02_03-04-05"
    with pytest.raises(ValueError):
        w.append(0, 1, "me", "x")


def test_cursor_semantics():
    w = SessionWriter(datetime(2026, 1, 1))
    for i in range(5):
        w.append(i, i + 1, "me", f"t{i}")
    r = StoreReader()
    segs, cur = r.read_segments()
    assert [s.seq for s in segs] == [1, 2, 3, 4, 5] and cur == 5
    segs, cur = r.read_segments(since_cursor=5)
    assert segs == [] and cur == 5
    segs, cur = r.read_segments(since_cursor=1, limit=2)
    assert [s.seq for s in segs] == [2, 3] and cur == 3
    w.append(5, 6, "them", "t5")
    segs, cur = r.read_segments(since_cursor=cur)
    assert [s.seq for s in segs] == [4, 5, 6] and cur == 6
    w.close()


def test_none_session_is_latest_and_empty_store():
    r = StoreReader()
    assert r.read_segments() == ([], 0)
    assert r.list_sessions() == []
    w1 = SessionWriter(datetime(2026, 1, 1, 10))
    w1.append(0, 1, "me", "old")
    w1.close()
    w2 = SessionWriter(datetime(2026, 1, 1, 11))
    w2.append(0, 1, "me", "new")
    segs, _ = r.read_segments()
    assert segs[0].text == "new"
    segs, _ = r.read_segments("2026-01-01_10-00-00")
    assert segs[0].text == "old"
    assert [s.id for s in r.list_sessions()] == ["2026-01-01_11-00-00", "2026-01-01_10-00-00"]
    w2.close()


def test_torn_last_line_ignored():
    w = SessionWriter(datetime(2026, 1, 1))
    w.append(0, 1, "me", "ok")
    with open(w.path, "a", encoding="utf-8") as f:
        f.write('{"seq": 2, "t0": 1.0, "t1": 2.0, "spea')
    segs, cur = StoreReader().read_segments()
    assert [s.seq for s in segs] == [1] and cur == 1
    with open(w.path, "a", encoding="utf-8") as f:
        f.write('ker": "them", "text": "done"}\n')
    segs, cur = StoreReader().read_segments(since_cursor=1)
    assert [s.text for s in segs] == ["done"] and cur == 2
    w.close()


def test_search_case_insensitive_across_sessions():
    w1 = SessionWriter(datetime(2026, 1, 1, 10))
    w1.append(0, 1, "me", "Budget review")
    w1.close()
    w2 = SessionWriter(datetime(2026, 1, 1, 11))
    w2.append(0, 1, "them", "the BUDGET is fine")
    w2.append(1, 2, "me", "unrelated")
    w2.close()
    r = StoreReader()
    assert [s.text for s in r.search("budget")] == ["Budget review", "the BUDGET is fine"]
    assert [s.text for s in r.search("budget", "2026-01-01_11-00-00")] == ["the BUDGET is fine"]
    assert r.search("nothing") == []


def test_status_alive_and_active():
    r = StoreReader()
    assert r.read_status().alive is False
    w = SessionWriter(datetime(2026, 1, 1), heartbeat_interval=0.05)
    st = r.read_status()
    assert st.alive and st.recording and st.session_id == "2026-01-01_00-00-00" and st.pid
    assert r.list_sessions()[0].is_active
    w.append(0, 1, "me", "x")
    assert r.read_status().segments == 1
    t1 = r.read_status().last_heartbeat
    time.sleep(0.3)
    assert r.read_status().last_heartbeat > t1  # heartbeat thread refreshes
    w.close()
    st = r.read_status()
    assert st.recording is False and st.alive is True
    assert not r.list_sessions()[0].is_active


def test_stale_heartbeat_means_not_alive():
    w = SessionWriter(datetime(2026, 1, 1))
    w.close()
    data = json.loads(paths.status_path().read_text())
    data.update(recording=True, last_heartbeat=time.time() - 60)
    paths.status_path().write_text(json.dumps(data))
    st = StoreReader().read_status()
    assert st.alive is False and st.recording is False
    assert not StoreReader().list_sessions()[0].is_active


def test_concurrent_writer_and_reader():
    w = SessionWriter(datetime(2026, 1, 1), heartbeat_interval=0.01)
    total = 300
    errors: list[Exception] = []
    got: list[int] = []

    def write():
        for i in range(total):
            w.append(i, i + 1, "me" if i % 2 else "them", f"line {i} " + "é" * 50)

    def read():
        r = StoreReader()
        cur = 0
        deadline = time.time() + 20
        try:
            while cur < total and time.time() < deadline:
                segs, cur = r.read_segments(since_cursor=cur)
                got.extend(s.seq for s in segs)
                r.read_status()
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    tw, tr = threading.Thread(target=write), threading.Thread(target=read)
    tr.start()
    tw.start()
    tw.join()
    tr.join()
    w.close()
    assert not errors
    assert got == list(range(1, total + 1))
