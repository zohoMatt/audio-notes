import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from audio_notes.cli import app
from audio_notes.cli import clean as clean_cli
from audio_notes.cli import setup as setup_cli

runner = CliRunner()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIO_NOTES_DATA_DIR", str(tmp_path / "data"))
    desktop = tmp_path / "claude" / "claude_desktop_config.json"
    desktop.parent.mkdir()
    monkeypatch.setenv(setup_cli.CONFIG_ENV, str(desktop))
    code = tmp_path / ".claude.json"
    monkeypatch.setenv(clean_cli.CLAUDE_CODE_CONFIG_ENV, str(code))
    monkeypatch.setattr(setup_cli, "claude_desktop_running", lambda: False)
    monkeypatch.setattr(clean_cli, "find_uninstaller", lambda: None)
    return tmp_path, desktop, code


def _populate(tmp_path, desktop, code):
    desktop.write_text(json.dumps({"mcpServers": {"Audio Notes": {"command": "x"}, "other": {"command": "y"}},
                                   "keep": 1}), encoding="utf-8")
    for name in ("claude_desktop_config.json.bak-20261116-220453", "claude_desktop_config.json.bak-audio-notes",
                 "claude_desktop_config.json.bak"):
        (desktop.parent / name).write_text("{}", encoding="utf-8")
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".mcp.json").write_text(json.dumps({"mcpServers": {"audio-notes": {}, "keep": {}}}), encoding="utf-8")
    code.write_text(json.dumps({
        "mcpServers": {"audio-notes": {}, "vibe": {}},
        "projects": {str(proj): {"mcpServers": {"audio-notes": {}}}, "/gone": {"mcpServers": {"Audio Notes": {}}},
                     "/other": {"mcpServers": {"x": {}}}},
    }), encoding="utf-8")
    return proj


def test_dry_run_lists_and_changes_nothing(env):
    tmp_path, desktop, code = env
    _populate(tmp_path, desktop, code)
    before = desktop.read_text(encoding="utf-8"), code.read_text(encoding="utf-8")
    r = runner.invoke(app, ["clean", "--dry-run"])
    assert r.exit_code == 0, r.output
    assert "Audio Notes" in r.output and "bak-audio-notes" in r.output and "user scope" in r.output
    assert "claude_desktop_config.json.bak\n" not in r.output  # Claude's own backup is not ours
    assert (desktop.read_text(encoding="utf-8"), code.read_text(encoding="utf-8")) == before


def test_clean_removes_only_our_entries(env):
    tmp_path, desktop, code = env
    proj = _populate(tmp_path, desktop, code)
    r = runner.invoke(app, ["clean", "--yes"])
    assert r.exit_code == 0, r.output
    d = json.loads(desktop.read_text(encoding="utf-8"))
    assert d == {"mcpServers": {"other": {"command": "y"}}, "keep": 1}
    assert sorted(p.name for p in desktop.parent.iterdir()) == ["claude_desktop_config.json",
                                                                 "claude_desktop_config.json.bak"]
    c = json.loads(code.read_text(encoding="utf-8"))
    assert c["mcpServers"] == {"vibe": {}}
    assert c["projects"][str(proj)]["mcpServers"] == {}
    assert c["projects"]["/gone"]["mcpServers"] == {}
    assert c["projects"]["/other"]["mcpServers"] == {"x": {}}
    assert json.loads((proj / ".mcp.json").read_text(encoding="utf-8")) == {"mcpServers": {"keep": {}}}
    assert "Nothing to clean" in runner.invoke(app, ["clean", "--yes"]).output


def test_clean_asks_first(env):
    tmp_path, desktop, code = env
    _populate(tmp_path, desktop, code)
    before = desktop.read_text(encoding="utf-8")
    r = runner.invoke(app, ["clean"], input="n\n")
    assert r.exit_code == 1 and desktop.read_text(encoding="utf-8") == before


def test_keep_backups(env):
    tmp_path, desktop, code = env
    _populate(tmp_path, desktop, code)
    assert runner.invoke(app, ["clean", "--yes", "--keep-backups"]).exit_code == 0
    assert (desktop.parent / "claude_desktop_config.json.bak-audio-notes").exists()


def test_desktop_running_skips_desktop_but_cleans_rest(env, monkeypatch):
    tmp_path, desktop, code = env
    _populate(tmp_path, desktop, code)
    monkeypatch.setattr(setup_cli, "claude_desktop_running", lambda: True)
    r = runner.invoke(app, ["clean", "--yes"])
    assert r.exit_code == 1 and "SKIP" in r.output
    assert "Audio Notes" in json.loads(desktop.read_text(encoding="utf-8"))["mcpServers"]
    assert json.loads(code.read_text(encoding="utf-8"))["mcpServers"] == {"vibe": {}}


def test_uninstall_and_purge(env, monkeypatch):
    tmp_path, desktop, code = env
    app_dir = tmp_path / "Audio Notes"
    (app_dir / "data" / "sessions").mkdir(parents=True)
    unins = app_dir / "unins000.exe"
    unins.write_text("", encoding="utf-8")
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(clean_cli, "find_uninstaller", lambda: unins)
    calls = []

    class R:
        returncode = 0

    monkeypatch.setattr(clean_cli.subprocess, "run", lambda args, **kw: calls.append(args) or R())
    r = runner.invoke(app, ["clean", "--yes", "--uninstall", "--purge-data"])
    assert r.exit_code == 0, r.output
    assert calls == [[str(unins), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]]
    assert not (app_dir / "data").exists() and not (tmp_path / "data").exists()


def test_uninstall_not_installed(env):
    r = runner.invoke(app, ["clean", "--uninstall", "--yes"])
    hint = "uv tool uninstall audio-notes" if sys.platform == "darwin" else "No installed Audio Notes"
    assert r.exit_code == 0 and hint in r.output and "Nothing to clean" in r.output


def test_purge_data_on_macos_removes_app_support_and_logs(env, monkeypatch):
    tmp_path, _, _ = env
    home = tmp_path / "home"
    support = home / "Library" / "Application Support" / "Audio Notes"
    logs = home / "Library" / "Logs" / "Audio Notes"
    (support / "sessions").mkdir(parents=True)
    (support / "sessions" / "2026-11-18_10-00-00.jsonl").write_text("{}\n", encoding="utf-8")
    logs.mkdir(parents=True)
    (logs / "audio-notes.log").write_text("x\n", encoding="utf-8")
    monkeypatch.delenv("AUDIO_NOTES_DATA_DIR")
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(sys, "platform", "darwin")

    r = runner.invoke(app, ["clean", "--purge-data", "--uninstall", "--dry-run"])
    assert r.exit_code == 0, r.output
    assert "uv tool uninstall audio-notes" in r.output
    assert f"transcripts     {support}" in r.output and f"logs            {logs}" in r.output

    r = runner.invoke(app, ["clean", "--purge-data", "--yes"])
    assert r.exit_code == 0, r.output
    assert not support.exists() and not logs.exists()
    assert (home / "Library" / "Logs").is_dir()  # only our folders go


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_clean_keeps_the_desktop_config_mode(env):
    import os
    import stat

    tmp_path, desktop, code = env
    _populate(tmp_path, desktop, code)
    os.chmod(desktop, 0o600)
    r = runner.invoke(app, ["clean", "--yes"])
    assert r.exit_code == 0, r.output
    assert stat.S_IMODE(desktop.stat().st_mode) == 0o600
    assert "Audio Notes" not in json.loads(desktop.read_text(encoding="utf-8"))["mcpServers"]
