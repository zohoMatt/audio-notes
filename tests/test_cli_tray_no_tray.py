import socket

import httpx
from typer.testing import CliRunner

from audio_notes.cli import app
from audio_notes.cli import run as run_cli

runner = CliRunner()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_no_tray_serves_panel_without_tray(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIO_NOTES_DATA_DIR", str(tmp_path))
    port = _free_port()
    monkeypatch.setenv("AUDIO_NOTES_WEB_PORT", str(port))

    import audio_notes.tray.app as tray_app

    def no_tray_app(*a, **kw):
        raise AssertionError("TrayApp must not be created with --no-tray")

    monkeypatch.setattr(tray_app, "TrayApp", no_tray_app)
    seen = {}

    def fake_wait():  # stands in for "until Ctrl+C": hit the live panel, then return
        r = httpx.get(f"http://127.0.0.1:{port}/api/status", headers={"x-audio-notes-token": seen["token"]})
        seen["status"] = r.status_code
        seen["unauth"] = httpx.get(f"http://127.0.0.1:{port}/api/status").status_code

    monkeypatch.setattr(run_cli, "_wait_until_interrupted", fake_wait)

    import audio_notes.web.server as server

    real_new_token = server.new_token

    def remember_token():
        seen["token"] = real_new_token()
        return seen["token"]

    monkeypatch.setattr(server, "new_token", remember_token)

    r = runner.invoke(app, ["tray", "--no-tray"])
    assert r.exit_code == 0, r.output
    assert f"http://127.0.0.1:{port}/?token={seen['token']}" in r.output
    assert seen["status"] == 200 and seen["unauth"] == 401
    assert not (tmp_path / "first_run_ack").exists()  # no notice in developer mode
