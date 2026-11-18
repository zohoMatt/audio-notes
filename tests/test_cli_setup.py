import subprocess
import sys

import pytest

from audio_notes.cli import setup as setup_cli


@pytest.fixture
def mac(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=fake_run.stdout, stderr="")

    fake_run.stdout = ""
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(setup_cli, "_mac_running_by_bundle_id", lambda: False)
    return fake_run, calls


PS_RUNNING = (
    "/usr/libexec/logd\n"
    "/Applications/Claude.app/Contents/MacOS/Claude\n"
    "/Applications/Claude.app/Contents/Frameworks/Claude Helper.app/Contents/MacOS/Claude Helper\n"
)


def test_claude_desktop_running_on_macos_from_the_process_list(mac):
    fake_run, calls = mac
    fake_run.stdout = PS_RUNNING
    assert setup_cli.claude_desktop_running() is True
    assert calls[0] == ["ps", "-axo", "comm="]


def test_claude_desktop_running_on_macos_in_another_folder(mac):
    fake_run, _ = mac
    fake_run.stdout = "/Users/me/Applications/Claude.app/Contents/MacOS/Claude\n"
    assert setup_cli.claude_desktop_running() is True


@pytest.mark.parametrize("ps", [
    "",
    # Claude Code (CLI) and the desktop app's helpers alone are not Claude Desktop.
    "/opt/homebrew/bin/claude\nnode\n",
    "/Applications/Claude.app/Contents/Frameworks/Claude Helper.app/Contents/MacOS/Claude Helper\n",
])
def test_claude_desktop_not_running_on_macos(mac, ps):
    fake_run, _ = mac
    fake_run.stdout = ps
    assert setup_cli.claude_desktop_running() is False


def test_claude_desktop_running_on_macos_by_bundle_id(mac, monkeypatch):
    _, calls = mac
    monkeypatch.setattr(setup_cli, "_mac_running_by_bundle_id", lambda: True)
    assert setup_cli.claude_desktop_running() is True
    assert calls == []  # no need to list processes


def test_claude_desktop_running_on_macos_ps_failure(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(setup_cli, "_mac_running_by_bundle_id", lambda: False)

    def boom(cmd, **kw):
        raise OSError("no ps")

    monkeypatch.setattr(subprocess, "run", boom)
    assert setup_cli.claude_desktop_running() is False


@pytest.mark.skipif(sys.platform != "darwin", reason="needs AppKit")
def test_bundle_id_lookup_does_not_raise():
    assert setup_cli._mac_running_by_bundle_id() in (True, False)


def _venv(root):
    (root / "bin").mkdir(parents=True)
    (root / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    site = root / "lib" / "python3.12" / "site-packages"
    site.mkdir(parents=True)
    (site / "_editable_impl_audio_notes.pth").write_text("/src\n", encoding="utf-8")
    exe = root / "bin" / "audio-notes"
    exe.write_text("", encoding="utf-8")
    return exe, site


@pytest.fixture
def mac_home(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    return tmp_path


def test_no_warning_for_a_uv_tool(mac_home):
    exe, _ = _venv(mac_home / ".local" / "share" / "uv" / "tools" / "audio-notes")
    assert setup_cli.hidden_venv_warning(str(exe)) is None


def test_no_warning_without_a_venv(mac_home):
    assert setup_cli.hidden_venv_warning(str(mac_home / "audio-notes")) is None


def test_no_warning_off_macos(mac_home, monkeypatch):
    exe, _ = _venv(mac_home / "Documents" / "repo" / ".venv")
    monkeypatch.setattr(sys, "platform", "win32")
    assert setup_cli.hidden_venv_warning(str(exe)) is None


def test_warns_for_a_dot_venv_under_documents(mac_home):
    exe, _ = _venv(mac_home / "Documents" / "repos" / "audio-notes" / ".venv")
    w = setup_cli.hidden_venv_warning(str(exe))
    assert w and "may mark it hidden" in w and "uv tool install" in w


@pytest.mark.skipif(not hasattr(__import__("os"), "chflags"), reason="needs BSD file flags")
def test_warns_when_pth_files_are_hidden(mac_home):
    import os
    import stat

    exe, site = _venv(mac_home / "work" / "venv")
    assert setup_cli.hidden_venv_warning(str(exe)) is None
    pth = site / "_editable_impl_audio_notes.pth"
    os.chflags(pth, stat.UF_HIDDEN)
    w = setup_cli.hidden_venv_warning(str(exe))
    assert w and "marked hidden" in w


def test_setup_claude_prints_the_warning(mac_home, monkeypatch):
    from typer.testing import CliRunner

    from audio_notes.cli import app

    exe, _ = _venv(mac_home / "Documents" / "repo" / ".venv")
    monkeypatch.setattr(setup_cli, "server_command", lambda: (str(exe), ["mcp"]))
    r = CliRunner().invoke(app, ["setup", "claude"])
    assert r.exit_code == 0 and "WARNING" in r.output and "No module named" in r.output
