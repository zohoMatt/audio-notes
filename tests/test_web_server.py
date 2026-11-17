import json
import socket
import threading
import time
from datetime import datetime

import httpx
import pytest
from starlette.testclient import TestClient

from audio_notes.store.reader import StoreReader
from audio_notes.store.writer import SessionWriter
from audio_notes.web.server import PanelServer, create_app

TOKEN = "test-token-123"
HOST = {"Host": "127.0.0.1:8765"}


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIO_NOTES_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def client():
    app = create_app(StoreReader(), TOKEN, port=8765, sse_poll_interval=0.05, sse_max_seconds=1.0)
    return TestClient(app)


def get(client, path, token=TOKEN, headers=HOST, **kw):
    sep = "&" if "?" in path else "?"
    url = path if token is None else f"{path}{sep}token={token}"
    return client.get(url, headers=headers, **kw)


def parse_sse(text):
    events = []
    for block in text.split("\n\n"):
        ev, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                ev = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if ev:
            events.append((ev, data))
    return events


@pytest.mark.parametrize("host", ["evil.example.com", "127.0.0.1:9999", "127.0.0.1", "localhost:1", ""])
def test_bad_host_rejected(client, host):
    r = get(client, "/api/status", headers={"Host": host})
    assert r.status_code == 403


@pytest.mark.parametrize("host", ["127.0.0.1:8765", "localhost:8765", "LOCALHOST:8765"])
def test_good_hosts_accepted(client, host):
    assert get(client, "/api/status", headers={"Host": host}).status_code == 200


def test_missing_or_wrong_token(client):
    for path in ["/", "/static/app.js", "/api/status", "/api/sessions", "/api/segments", "/api/stream"]:
        assert get(client, path, token=None).status_code == 401, path
        assert get(client, path, token="wrong").status_code == 401, path


def test_token_via_header(client):
    r = client.get("/api/status", headers={**HOST, "X-Audio-Notes-Token": TOKEN})
    assert r.status_code == 200


def test_no_store_and_no_cors(client):
    for r in (
        get(client, "/api/status"),
        get(client, "/api/status", token=None),
        get(client, "/api/status", headers={"Host": "evil.test"}),
        get(client, "/"),
    ):
        assert r.headers["cache-control"] == "no-store"
        assert not any(h.lower().startswith("access-control-") for h in r.headers)
    r = client.options("/api/status?token=" + TOKEN, headers={**HOST, "Origin": "http://evil.test"})
    assert "access-control-allow-origin" not in r.headers


def test_index_and_static(client):
    r = get(client, "/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert f"token={TOKEN}" in r.text and "__TOKEN__" not in r.text
    assert "EventSource" in get(client, "/static/app.js").text
    assert "--me" in get(client, "/static/style.css").text
    assert get(client, "/static/nope.js").status_code == 404


def test_status_and_sessions_and_segments(client):
    assert get(client, "/api/status").json()["recording"] is False
    assert get(client, "/api/sessions").json() == []
    w1 = SessionWriter(datetime(2026, 1, 1, 10, 0, 0))
    w1.append(0, 1, "me", "first")
    w1.close()
    w2 = SessionWriter(datetime(2026, 1, 2, 10, 0, 0))
    w2.append(0, 1, "them", "second")
    w2.append(1, 2, "me", "third")
    try:
        st = get(client, "/api/status").json()
        assert st["recording"] is True and st["segments"] == 2
        sessions = get(client, "/api/sessions").json()
        assert [s["id"] for s in sessions] == ["2026-01-02_10-00-00", "2026-01-01_10-00-00"]
        assert sessions[0]["is_active"] is True and sessions[0]["segment_count"] == 2
        assert "path" not in sessions[0]
        d = get(client, "/api/segments?session=2026-01-01_10-00-00").json()
        assert [s["text"] for s in d["segments"]] == ["first"] and d["cursor"] == 1
        d = get(client, "/api/segments?since=1").json()  # latest session
        assert [s["text"] for s in d["segments"]] == ["third"]
        assert get(client, "/api/segments?since=abc").status_code == 400
    finally:
        w2.close()


def test_sse_delivers_appended_line(client):
    w = SessionWriter(datetime(2026, 1, 1, 10, 0, 0))
    w.append(0, 1, "them", "already there")

    def later():
        time.sleep(0.3)
        w.append(1, 2, "me", "live line")

    t = threading.Thread(target=later)
    t.start()
    try:
        r = get(client, "/api/stream")
    finally:
        t.join()
        w.close()
    assert r.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(r.text)
    assert events[0] == ("session", {"id": "2026-01-01_10-00-00"})
    segs = [d for e, d in events if e == "segment"]
    assert [(s["seq"], s["speaker"], s["text"]) for s in segs] == [
        (1, "them", "already there"),
        (2, "me", "live line"),
    ]


def test_sse_respects_since_and_switches_to_new_session(client):
    w1 = SessionWriter(datetime(2026, 1, 1, 10, 0, 0))
    w1.append(0, 1, "me", "old1")
    w1.append(1, 2, "me", "old2")

    def later():
        time.sleep(0.3)
        w2 = SessionWriter(datetime(2026, 1, 1, 11, 0, 0))
        w2.append(0, 1, "them", "fresh")
        w2.close()

    t = threading.Thread(target=later)
    t.start()
    try:
        r = get(client, "/api/stream?since=1")
    finally:
        t.join()
        w1.close()
    events = parse_sse(r.text)
    assert [e for e, _ in events] == ["session", "segment", "session", "segment"]
    assert events[1][1]["text"] == "old2"
    assert events[2][1] == {"id": "2026-01-01_11-00-00"}
    assert events[3][1]["text"] == "fresh"


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_panel_server_real_http_roundtrip():
    port = _free_port()
    srv = PanelServer(StoreReader(), port)
    srv.start()
    try:
        assert srv.url == f"http://127.0.0.1:{port}/?token={srv.token}"
        assert httpx.get(srv.url).status_code == 200
        assert httpx.get(f"http://127.0.0.1:{port}/api/status").status_code == 401
        r = httpx.get(f"http://localhost:{port}/api/status?token={srv.token}")
        # localhost may resolve to ::1 only; if it connects it must be accepted
        assert r.status_code == 200
    except httpx.ConnectError:
        pass
    finally:
        srv.stop()
    with pytest.raises(httpx.TransportError):
        httpx.get(srv.url, timeout=1)


def test_panel_server_port_in_use_raises():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        srv = PanelServer(StoreReader(), s.getsockname()[1])
        with pytest.raises(RuntimeError):
            srv.start()


class FakeController:
    def __init__(self, fail_start=None):
        self.recording = False
        self.paused = False
        self.downloading = False
        self.error = None
        self.starts = self.stops = 0
        self.fail_start = fail_start

    def start(self):
        self.starts += 1
        if self.fail_start:
            self.error = self.fail_start
            raise RuntimeError(self.fail_start)
        self.recording = True

    def stop(self):
        self.stops += 1
        self.recording = self.paused = False

    def pause(self):
        self.paused = self.recording

    def resume(self):
        self.paused = False

    def is_recording(self):
        return self.recording

    def is_paused(self):
        return self.paused

    def last_error(self):
        return self.error

    def is_downloading_model(self):
        return self.downloading


def ctl_client(controller):
    return TestClient(create_app(StoreReader(), TOKEN, port=8765, controller=controller))


def post(client, body, token=TOKEN, headers=HOST):
    url = "/api/recording" + ("" if token is None else f"?token={token}")
    return client.post(url, json=body, headers=headers)


def test_control_unavailable_without_controller(client):
    d = get(client, "/api/control").json()
    assert d["available"] is False and d["reason"]
    r = post(client, {"recording": True})
    assert r.status_code == 409 and r.json()["available"] is False  # not a 500


def test_recording_post_requires_token_and_host():
    c = ctl_client(FakeController())
    assert post(c, {"recording": True}, token=None).status_code == 401
    assert post(c, {"recording": True}, token="wrong").status_code == 401
    assert post(c, {"recording": True}, headers={"Host": "evil.test"}).status_code == 403
    assert c.get("/api/recording?token=" + TOKEN, headers=HOST).status_code == 405


def test_recording_start_stop_roundtrip():
    fc = FakeController()
    c = ctl_client(fc)
    assert get(c, "/api/control").json() == {
        "available": True, "recording": False, "paused": False, "downloading": False, "error": None
    }
    r = post(c, {"recording": True})
    assert r.status_code == 200 and r.json()["recording"] is True and fc.starts == 1
    assert post(c, {"recording": True}).status_code == 200 and fc.starts == 1  # idempotent
    r = post(c, {"recording": False})
    assert r.json()["recording"] is False and fc.stops == 1


def test_recording_actions_pause_resume_stop():
    fc = FakeController()
    c = ctl_client(fc)
    assert post(c, {"action": "start"}).json()["recording"] is True
    r = post(c, {"action": "pause"}).json()
    assert r["recording"] is True and r["paused"] is True
    r = post(c, {"action": "resume"}).json()
    assert r["recording"] is True and r["paused"] is False and fc.starts == 1  # same session
    post(c, {"action": "pause"})
    r = post(c, {"action": "stop"}).json()
    assert r["recording"] is False and r["paused"] is False and fc.stops == 1
    assert post(c, {"action": "rewind"}).status_code == 400


@pytest.mark.parametrize("body", [{}, {"recording": "yes"}, {"action": 1}, [1], "x"])
def test_recording_post_bad_body(body):
    fc = FakeController()
    assert post(ctl_client(fc), body).status_code == 400
    assert fc.starts == 0 and fc.stops == 0


def test_recording_start_failure_reports_error():
    c = ctl_client(FakeController(fail_start="no audio device"))
    r = post(c, {"recording": True})
    assert r.status_code == 500
    assert r.json()["error"] == "no audio device" and r.json()["recording"] is False


def test_index_has_record_buttons_and_logo(client):
    html = get(client, "/").text
    assert 'id="rec-btn"' in html and 'id="pause-btn"' in html and 'id="logo"' in html
