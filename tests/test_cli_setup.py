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
