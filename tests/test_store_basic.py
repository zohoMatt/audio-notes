import json
import threading
import time
from datetime import datetime

import pytest

from audio_notes import paths
from audio_notes.store.follow import Follower, format_cursor, parse_cursor
from audio_notes.store.models import Segment
from audio_notes.store.reader import StoreReader
from audio_notes.store.status import StatusPublisher
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
    assert st.recording is False and st.alive is False  # a closed writer's process reads as gone at once
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


def test_same_second_sessions_get_their_own_file():
    at = datetime(2026, 1, 1, 10)
    w1 = SessionWriter(at)
    w1.append(0, 1, "me", "first")
    w1.close()
    w2 = SessionWriter(at)  # e.g. stop + start within one second
    w2.append(0, 1, "me", "second")
    w2.close()
    assert w1.path != w2.path and w2.session_id == "2026-01-01_10-00-00-2"
    r = StoreReader()
    assert [s.id for s in r.list_sessions()] == ["2026-01-01_10-00-00-2", "2026-01-01_10-00-00"]
    assert r.latest_session_id() == "2026-01-01_10-00-00-2"
    assert r.list_sessions()[0].started_at == "2026-01-01T10:00:00"
    assert [s.seq for s in r.read_segments(w1.session_id)[0]] == [1]  # no duplicated seq
    assert paths.session_sort_key("2026-01-01_10-00-00-10") > paths.session_sort_key("2026-01-01_10-00-00-9")


def test_one_reader_picks_up_appends_incrementally():
    w = SessionWriter(datetime(2026, 1, 1))
    r = StoreReader()
    w.append(0, 1, "me", "a")
    assert [s.text for s in r.read_segments()[0]] == ["a"]
    assert r.list_sessions()[0].segment_count == 1
    w.append(1, 2, "me", "b")
    assert [s.text for s in r.read_segments()[0]] == ["a", "b"]
    assert r.list_sessions()[0].segment_count == 2
    w.close()
    # a file replaced by a shorter one (not something the writer does) is re-read from scratch
    w.path.write_text(Segment(1, 0, 1, "them", "z").to_json_line() + "\n", encoding="utf-8")
    assert [s.text for s in r.read_segments()[0]] == ["z"]
    assert r.list_sessions()[0].segment_count == 1


def test_session_ids_cannot_escape_the_sessions_folder(data_dir):
    (data_dir / "secret.jsonl").write_text(Segment(1, 0, 1, "me", "x").to_json_line() + "\n")
    SessionWriter(datetime(2026, 1, 1)).close()
    r = StoreReader()
    assert r.read_segments("../secret") == ([], 0)
    assert r.read_segments(r"..\secret") == ([], 0)


def test_idle_daemon_publisher_is_alive_but_not_recording():
    r = StoreReader()
    pub = StatusPublisher(heartbeat_interval=0.05)
    pub.update(recording=True)  # nothing is written before start()
    assert r.read_status().alive is False
    pub.update(recording=False)
    pub.start()
    st = r.read_status()
    assert st.alive and not st.recording and st.session_id is None
    w = SessionWriter(datetime(2026, 1, 1), status=pub)
    w.append(0, 1, "me", "x")
    st = r.read_status()
    assert st.recording and st.session_id == w.session_id and st.segments == 1
    w.close()
    time.sleep(0.2)
    st = r.read_status()
    assert st.alive and not st.recording  # the daemon keeps beating after the session ends
    pub.close()
    st = r.read_status()
    assert st.recording is False
    assert st.alive is False  # gone right after a clean exit, without waiting for staleness


def test_follower_switches_to_a_newer_session_after_finishing_the_old_one():
    w1 = SessionWriter(datetime(2026, 1, 1, 10))
    w1.append(0, 1, "me", "old1")
    f = Follower(StoreReader())
    assert [(k, getattr(v, "text", v)) for k, v in f.poll()] == [("segment", "old1")]
    w1.append(1, 2, "me", "old2")
    w2 = SessionWriter(datetime(2026, 1, 1, 11))
    w2.append(0, 1, "them", "new1")
    events = [(k, getattr(v, "text", v)) for k, v in f.poll()]
    assert events == [("segment", "old2"), ("session", "2026-01-01_11-00-00"), ("segment", "new1")]
    assert f.poll() == []
    pinned = Follower(StoreReader(), "2026-01-01_10-00-00", cursor=1)  # an explicit session never switches
    assert [getattr(v, "text", v) for _, v in pinned.poll()] == ["old2"]
    w1.close()
    w2.close()


@pytest.mark.parametrize(
    "token,expected",
    [(None, (None, 0)), ("", (None, 0)), (5, (None, 5)), ("7", (None, 7)),
     ("2026-01-01_10-00-00:3", ("2026-01-01_10-00-00", 3)), ("2026-01-01_10-00-00-2:0", ("2026-01-01_10-00-00-2", 0))],
)
def test_cursor_tokens(token, expected):
    assert parse_cursor(token) == expected
    sid, seq = expected
    if sid:
        assert format_cursor(sid, seq) == token


def test_bad_cursor_token():
    with pytest.raises(ValueError):
        parse_cursor("abc:x")


def test_stream_names_number_sessions_oldest_first():
    from audio_notes.store.models import stream_label

    for hour in (9, 11, 10):  # created out of order: numbering follows the session time
        SessionWriter(datetime(2026, 1, 1, hour)).close()
    SessionWriter(datetime(2026, 1, 1, 11)).close()  # same second: "-2", after its twin
    r = StoreReader()
    assert [(s.stream, s.id) for s in r.list_sessions()] == [
        (4, "2026-01-01_11-00-00-2"),
        (3, "2026-01-01_11-00-00"),
        (2, "2026-01-01_10-00-00"),
        (1, "2026-01-01_09-00-00"),
    ]
    assert stream_label(3) == "Stream003" and stream_label(1234) == "Stream1234"
    for ref in ("Stream002", "stream2", "Stream #2", " stream 002 ", "2"):
        assert r.resolve_session_id(ref) == "2026-01-01_10-00-00", ref
    assert r.resolve_session_id("Stream005") is None and r.resolve_session_id("Stream000") is None
    assert r.resolve_session_id("2026-01-01_09-00-00") == "2026-01-01_09-00-00"
    assert r.resolve_session_id("2026-01-01_08-00-00") is None
    assert r.resolve_session_id(None) == "2026-01-01_11-00-00-2"
    assert r.stream_name("2026-01-01_11-00-00") == "Stream003" and r.stream_name("nope") is None
    assert r.read_segments("Stream001") == ([], 0)


def test_paused_status_is_published_and_cleared_on_close():
    r = StoreReader()
    w = SessionWriter(datetime(2026, 1, 1))
    assert r.read_status().paused is False
    w.set_paused(True)
    st = r.read_status()
    assert st.recording and st.paused and r.list_sessions()[0].is_paused
    w.close()
    st = r.read_status()
    assert not st.recording and not st.paused and not r.list_sessions()[0].is_paused
    w.set_paused(True)  # closed: ignored
    assert r.read_status().paused is False
