import json
from datetime import datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from audio_notes.cli import app
from audio_notes.store.writer import SessionWriter

runner = CliRunner()


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIO_NOTES_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AUDIO_NOTES_CLAUDE_CONFIG", str(tmp_path / "claude" / "cfg.json"))
    return tmp_path


def _session(n=3, at=datetime(2026, 1, 1, 10)):
    w = SessionWriter(at)
    for i in range(n):
        w.append(i * 65, i * 65 + 1, "me" if i % 2 == 0 else "them", f"line {i}")
    return w


def test_sessions_empty_and_listed():
    assert "No sessions" in runner.invoke(app, ["sessions"]).output
    w = _session()
    out = runner.invoke(app, ["sessions"]).output
    assert "2026-01-01_10-00-00" in out and "3 segments" in out and "[active]" in out
    w.close()
    assert "[active]" not in runner.invoke(app, ["sessions"]).output


def test_show_latest_and_n():
    _session(5).close()
    r = runner.invoke(app, ["show", "-n", "2"])
    assert r.exit_code == 0
    assert "[04:20] Me: line 4" in r.output and "[03:15] Them: line 3" in r.output
    assert "line 2" not in r.output


def test_show_named_session_and_missing():
    _session(2, datetime(2026, 1, 1, 9)).close()
    _session(1, datetime(2026, 1, 1, 10)).close()
    out = runner.invoke(app, ["show", "2026-01-01_09-00-00"]).output
    assert "line 1" in out
    assert runner.invoke(app, ["show", "nope"]).exit_code == 1


def test_show_follow(monkeypatch):
    w = _session(1)
    calls = {"n": 0}

    def fake_sleep(_):
        calls["n"] += 1
        if calls["n"] == 1:
            w.append(100, 101, "them", "late arrival")
        else:
            raise KeyboardInterrupt

    monkeypatch.setattr("audio_notes.cli.inspect.time.sleep", fake_sleep)
    r = runner.invoke(app, ["show", "-f"])
    assert "line 0" in r.output and "late arrival" in r.output
    w.close()


def test_status():
    assert "not running" in runner.invoke(app, ["status"]).output
    w = _session()
    out = runner.invoke(app, ["status"]).output
    assert "recording=yes" in out and "segments=3" in out
    w.close()


def test_setup_claude_print_only(tmp_path):
    r = runner.invoke(app, ["setup", "claude"])
    assert r.exit_code == 0
    assert '"mcpServers"' in r.output and "claude mcp add audio-notes" in r.output
    assert not (tmp_path / "claude").exists()


def test_setup_write_requires_confirmation(tmp_path):
    cfg = tmp_path / "claude" / "cfg.json"
    r = runner.invoke(app, ["setup", "claude", "--write"], input="n\n")
    assert r.exit_code == 1 and not cfg.exists()


def test_setup_write_merges_and_backs_up(tmp_path):
    cfg = tmp_path / "claude" / "cfg.json"
    cfg.parent.mkdir()
    cfg.write_text(json.dumps({"theme": "x", "mcpServers": {"other": {"command": "o"}}}))
    r = runner.invoke(app, ["setup", "claude", "--write"], input="y\n")
    assert r.exit_code == 0, r.output
    data = json.loads(cfg.read_text())
    assert data["theme"] == "x" and data["mcpServers"]["other"] == {"command": "o"}
    entry = data["mcpServers"]["audio-notes"]
    assert entry["args"][-1] == "mcp" and Path(entry["command"]).is_absolute()
    backups = list(cfg.parent.glob("cfg.json.bak-*"))
    assert len(backups) == 1 and "other" in backups[0].read_text()


def test_setup_write_bad_json_leaves_file(tmp_path):
    cfg = tmp_path / "claude" / "cfg.json"
    cfg.parent.mkdir()
    cfg.write_text("{ not json")
    r = runner.invoke(app, ["setup", "claude", "--write"], input="y\n")
    assert r.exit_code == 1 and cfg.read_text() == "{ not json"
