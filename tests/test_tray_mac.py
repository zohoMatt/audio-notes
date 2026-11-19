"""macOS menu bar logic without AppKit: the menu model, template icons, the permission
explanation, the backend seam, and the darwin branches of paths / CLI. Runs on any platform."""

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from audio_notes import paths
from audio_notes.capture.mac_tap import (
    MICROPHONE_PERMISSION_HINT,
    SYSTEM_AUDIO_PERMISSION_HINT,
    Permissions,
)
from audio_notes.tray import first_run, mac_menu
from audio_notes.tray.app import TrayApp
from audio_notes.tray.icons import MENUBAR_PT, menubar_icon
from audio_notes.tray.state import TrayState, describe


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIO_NOTES_DATA_DIR", str(tmp_path))
    return tmp_path


def _actions(log=None):
    log = [] if log is None else log

    def rec(name):
        return lambda *a: log.append((name, *a))

    return mac_menu.MenuActions(
        toggle_recording=rec("toggle"), stop_recording=rec("stop"), toggle_mic=rec("mic"),
        open_panel=rec("panel"), open_transcripts=rec("folder"), connect_to_claude=rec("claude"),
        open_url=rec("url"), check_for_updates=rec("updates"), about=rec("about"), quit=rec("quit"),
    )


def _titles(entries):
    return [e.title if not e.separator else "---" for e in entries]


# ---- menu model --------------------------------------------------------------------------------
def test_idle_menu_matches_the_design():
    entries = mac_menu.build_menu(describe(TrayState.IDLE), mic_on=True, error=None, perms=None, actions=_actions())
    assert _titles(entries) == [
        "Not Recording", "---",
        "Start Recording", "Include Microphone", "---",
        "Open Panel…", "Show Transcripts in Finder", "Connect to Claude…", "---",
        "Check for Updates…", "About Audio Notes", "Quit Audio Notes",
    ]
    status = entries[0]
    assert status.action is None  # grey, not clickable
    mic = entries[3]
    assert mic.checked and mic.enabled
    quit_item = entries[-1]
    assert quit_item.key == "q"


def test_no_open_at_login_item_anywhere():
    for state in TrayState:
        for recording in (False, True):
            entries = mac_menu.build_menu(describe(state, "x", recording=recording), mic_on=True, error="x",
                                          perms=Permissions("denied", "denied"), actions=_actions())
            assert not any("login" in e.title.lower() for e in entries)


def test_recording_menu_offers_pause_and_stop_and_locks_the_microphone():
    entries = mac_menu.build_menu(describe(TrayState.RECORDING), mic_on=False, error=None, perms=None,
                                  actions=_actions())
    titles = _titles(entries)
    assert titles[0] == "● Recording"
    assert titles[2:5] == ["Pause Recording", "Stop Recording", "Include Microphone"]
    mic = entries[4]
    assert not mic.enabled and not mic.checked
    paused = mac_menu.build_menu(describe(TrayState.PAUSED), mic_on=True, error=None, perms=None, actions=_actions())
    assert _titles(paused)[:4] == ["Paused", "---", "Continue Recording", "Stop Recording"]


def test_downloading_disables_the_toggle_and_error_shows_the_reason():
    dl = mac_menu.build_menu(describe(TrayState.DOWNLOADING), mic_on=True, error=None, perms=None, actions=_actions())
    assert dl[0].title == "Downloading Speech Model…" and not dl[2].enabled
    long_error = "Cannot capture audio: " + "x" * 200
    err = mac_menu.build_menu(describe(TrayState.ERROR, long_error), mic_on=True, error=long_error, perms=None,
                              actions=_actions())
    assert err[0].title.startswith("⚠ Cannot capture audio") and len(err[0].title) <= mac_menu.MAX_STATUS + 2


def test_menu_actions_are_wired():
    log = []
    entries = mac_menu.build_menu(describe(TrayState.RECORDING), mic_on=True, error=None, perms=None,
                                  actions=_actions(log))
    for e in entries:
        if e.action is not None:
            e.action()
    assert [name for name, *_ in log] == ["toggle", "stop", "mic", "panel", "folder", "claude", "updates",
                                         "about", "quit"]


def test_permission_items_appear_only_when_needed():
    def allow_items(error=None, perms=None, mic_on=True):
        entries = mac_menu.build_menu(describe(TrayState.ERROR if error else TrayState.IDLE, error),
                                      mic_on=mic_on, error=error, perms=perms, actions=_actions(log))
        return [e for e in entries if e.title.startswith("⚠ Allow")]

    log = []
    assert allow_items() == []
    assert allow_items(perms=Permissions("authorized", "authorized")) == []
    assert allow_items(perms=Permissions("authorized", "unknown")) == []  # SPI missing: do not guess
    (item,) = allow_items(perms=Permissions("authorized", "denied"))
    assert item.title == "⚠ Allow System Audio Recording…"
    item.action()
    assert log[-1] == ("url", mac_menu.SETTINGS_SYSTEM_AUDIO_URL)
    # the capture error alone is enough (e.g. the TCC check is unavailable)
    (item,) = allow_items(error=f"Cannot capture audio: {SYSTEM_AUDIO_PERMISSION_HINT} is off ...")
    assert "System Audio" in item.title
    both = allow_items(perms=Permissions("denied", "denied"))
    assert [i.title for i in both] == ["⚠ Allow System Audio Recording…",
                                       "⚠ Allow Microphone Access…"]
    both[1].action()
    assert log[-1] == ("url", mac_menu.SETTINGS_MICROPHONE_URL)
    # a denied microphone does not matter while the microphone is not used
    assert allow_items(perms=Permissions("denied", "authorized"), mic_on=False) == []
    assert len(allow_items(error=f"{MICROPHONE_PERMISSION_HINT} is off")) == 1


def test_update_and_about_texts_mention_the_version():
    assert "uv tool upgrade audio-notes" in mac_menu.updates_message("1.2.3")
    assert "1.2.3" in mac_menu.updates_message("1.2.3") and "1.2.3" in mac_menu.about_message("1.2.3")
    assert "Matt Zuo" in mac_menu.about_message("1.2.3")


# ---- icons -------------------------------------------------------------------------------------
@pytest.mark.parametrize("scale", [1, 2])
def test_menubar_icons_are_monochrome_templates_except_recording(scale):
    size = MENUBAR_PT * scale
    images = {}
    for state in TrayState:
        img, template = menubar_icon(state, scale)
        assert img.size == (size, size) and img.mode == "RGBA" and img.getbbox() is not None
        assert template is (state is not TrayState.RECORDING)
        if template:
            # template images: only black, the shape lives in the alpha channel
            px = np.asarray(img)
            assert not px[px[..., 3] > 0][:, :3].any()
        images[state] = img.tobytes()
    assert len(set(images.values())) == len(TrayState)


def test_recording_icon_has_a_red_dot_and_follows_the_menu_bar_appearance():
    light, _ = menubar_icon(TrayState.RECORDING, 2, dark=False)
    dark, _ = menubar_icon(TrayState.RECORDING, 2, dark=True)
    r, g, b, a = light.getpixel((28, 28))  # inside the bottom-right badge
    assert a > 200 and r > 200 and g < 100 and b < 100
    lp, dp = np.asarray(light), np.asarray(dark)
    assert ((lp[..., 3] > 250) & (lp[..., :3].max(axis=-1) < 10)).any(), "the light variant draws a black pencil"
    assert ((dp[..., 3] > 250) & (dp[..., :3].min(axis=-1) > 245)).any(), "the dark variant draws a white pencil"
    # dark only changes the recording icon (template images are tinted by macOS itself)
    assert menubar_icon(TrayState.IDLE, 1, dark=True)[0].tobytes() == menubar_icon(TrayState.IDLE, 1)[0].tobytes()


# ---- first run ---------------------------------------------------------------------------------
def test_permission_explanation_shows_once_and_requests():
    shown, requested = [], []
    assert first_run.ensure_permissions_explained(lambda t, m: shown.append(m) or True,
                                                  lambda: requested.append(1)) is True
    assert requested == [1] and "System Audio Recording" in shown[0] and "terminal" in shown[0]
    assert first_run.ensure_permissions_explained(lambda t, m: pytest.fail("asked twice"),
                                                  lambda: pytest.fail("requested twice")) is False


def test_permission_explanation_declined_is_not_repeated_and_request_errors_are_swallowed():
    assert first_run.ensure_permissions_explained(lambda t, m: False, lambda: pytest.fail("no request")) is True
    assert first_run.permissions_flag_path().is_file()
    first_run.permissions_flag_path().unlink()

    def boom():
        raise RuntimeError("helper missing")

    assert first_run.ensure_permissions_explained(lambda t, m: True, boom) is True


def test_legal_notice_unchanged_by_the_permission_flag():
    first_run.ensure_permissions_explained(lambda t, m: True, lambda: None)
    assert not first_run.is_acknowledged()


# ---- backend seam ------------------------------------------------------------------------------
class FakeController:
    def __init__(self):
        self.recording = self.paused = False
        self.mic = True
        self.error = None

    def start(self):
        self.recording = True

    def stop(self):
        self.recording = self.paused = False

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def is_recording(self):
        return self.recording

    def is_paused(self):
        return self.paused

    def mic_enabled(self):
        return self.mic

    def set_mic_enabled(self, enabled):
        self.mic = enabled

    def last_error(self):
        return self.error

    def is_downloading_model(self):
        return False


class FakeBackend:
    def __init__(self):
        self.updates, self.notes, self.stopped, self.key = [], [], False, None

    def run(self, app, on_ready):
        self.ran_with = app
        app.toggle_recording()  # a menu click while the loop runs
        app.quit()

    def update(self, view, mic_on):
        self.updates.append((view.state, mic_on))

    def notify(self, message, title):
        self.notes.append(message)

    def stop(self):
        self.stopped = True

    def refresh_key(self):
        return self.key


def test_tray_app_drives_any_backend():
    ctrl, backend = FakeController(), FakeBackend()
    app = TrayApp(ctrl, "http://x", first_run_dialog=lambda t, m: True, backend=backend)
    assert app.run() is True
    assert backend.ran_with is app and backend.stopped
    assert backend.updates[0] == (TrayState.RECORDING, True)
    assert not ctrl.recording  # quit stopped the session


def test_refresh_key_from_the_backend_forces_an_update():
    backend = FakeBackend()
    app = TrayApp(FakeController(), "http://x", backend=backend)
    app._backend = backend
    app.refresh()
    app.refresh()
    assert len(backend.updates) == 1
    backend.key = "dark"
    app.refresh()
    assert len(backend.updates) == 2


def test_notifications_go_to_the_backend_and_failures_fall_back_to_the_log():
    backend = FakeBackend()
    app = TrayApp(FakeController(), "http://x", backend=backend)
    app._backend = backend
    app._notify("hello")
    assert backend.notes == ["hello"]

    def boom(message, title):
        raise RuntimeError("no notification center")

    backend.notify = boom
    app._notify("still fine")  # must not raise


def test_default_backend_per_platform(monkeypatch):
    from audio_notes.tray import backend as backend_mod
    from audio_notes.tray.mac_statusbar import MacStatusBarBackend
    from audio_notes.tray.pystray_backend import PystrayBackend

    monkeypatch.setattr(sys, "platform", "darwin")
    assert isinstance(backend_mod.default_backend(), MacStatusBarBackend)
    monkeypatch.setattr(sys, "platform", "win32")
    assert isinstance(backend_mod.default_backend(), PystrayBackend)


def test_mac_backend_menu_without_appkit():
    """The backend's menu glue (minus NSMenu) works with plain Python: actions and permissions."""
    from audio_notes.tray.mac_statusbar import MacStatusBarBackend

    opened = []
    ctrl = FakeController()
    backend = MacStatusBarBackend(open_url=opened.append)
    app = TrayApp(ctrl, "http://x", backend=backend)
    backend._app = app
    backend._perms = Permissions("authorized", "denied")
    entries = backend.menu_entries()
    allow = [e for e in entries if "Allow System Audio" in e.title][0]
    allow.action()
    assert opened == [mac_menu.SETTINGS_SYSTEM_AUDIO_URL]
    backend._actions = [e.action for e in entries if not e.separator]
    toggle_index = [e.title for e in entries if not e.separator].index("Start Recording")
    backend.clicked(toggle_index)
    import time

    deadline = time.monotonic() + 5
    while not ctrl.recording and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ctrl.recording
    backend.clicked(999)  # out of range: ignored


def test_mac_modules_import_without_pyobjc():
    import importlib

    for name in ("audio_notes.tray.mac_statusbar", "audio_notes.tray.mac_menu", "audio_notes.capture.mac_tap"):
        importlib.import_module(name)
    if sys.platform != "darwin":
        with pytest.raises(ImportError):
            importlib.import_module("AppKit")


def test_open_folder_uses_open_on_macos(monkeypatch, tmp_path):
    from audio_notes.tray import app as app_mod

    calls = []
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(app_mod.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    app_mod._open_folder(tmp_path / "sessions")
    assert calls == [["open", str(tmp_path / "sessions")]] and (tmp_path / "sessions").is_dir()


# ---- darwin branches ---------------------------------------------------------------------------
def test_mac_data_and_log_dirs(monkeypatch, tmp_path):
    monkeypatch.delenv("AUDIO_NOTES_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    support = tmp_path / "Library" / "Application Support" / "Audio Notes"
    assert paths.data_dir() == support and paths.sessions_dir() == support / "sessions"
    assert paths.log_dir() == tmp_path / "Library" / "Logs" / "Audio Notes"
    # a packaged (frozen) build on macOS still keeps data out of the .app bundle
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Audio Notes.app" / "Contents" / "MacOS" / "x"))
    assert paths.data_dir() == support
    monkeypatch.setenv("AUDIO_NOTES_DATA_DIR", str(tmp_path / "custom"))
    assert paths.data_dir() == paths.log_dir() == tmp_path / "custom"


def test_log_dir_is_the_data_dir_elsewhere(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    assert paths.log_dir() == paths.data_dir() == tmp_path


# claude_desktop_running() on macOS: see tests/test_cli_setup.py.


def test_devices_command_on_macos(monkeypatch):
    from audio_notes.capture import mac_tap
    from audio_notes.cli import app

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(mac_tap, "list_devices", lambda: {
        "output": [{"name": "Speakers", "uid": "s", "channels": 2, "sample_rate": 48000, "default": True}],
        "input": [],
    })
    monkeypatch.setattr(mac_tap, "permissions", lambda: Permissions("authorized", "denied"))
    r = CliRunner().invoke(app, ["devices"])
    assert r.exit_code == 0, r.output
    assert "* Speakers  (48000 Hz, 2 ch)" in r.output and "(none)" in r.output
    assert "system audio recording denied" in r.output


def test_devices_command_reports_a_missing_helper(monkeypatch):
    from audio_notes.capture import mac_tap
    from audio_notes.cli import app

    def missing():
        raise mac_tap.HelperMissing("not installed")

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(mac_tap, "list_devices", missing)
    r = CliRunner().invoke(app, ["devices"])
    assert r.exit_code == 1 and "not installed" in r.output


def test_clean_on_macos_points_to_uv_and_purges_the_log_dir(monkeypatch, tmp_path):
    from audio_notes.cli import app
    from audio_notes.cli import clean as clean_cli
    from audio_notes.cli import setup as setup_cli

    logs = tmp_path / "Library" / "Logs" / "Audio Notes"
    logs.mkdir(parents=True)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(paths, "log_dir", lambda: logs)
    monkeypatch.setenv(setup_cli.CONFIG_ENV, str(tmp_path / "claude" / "claude_desktop_config.json"))
    monkeypatch.setenv(clean_cli.CLAUDE_CODE_CONFIG_ENV, str(tmp_path / ".claude.json"))
    monkeypatch.setattr(setup_cli, "claude_desktop_running", lambda: False)
    plan = clean_cli.build_plan(keep_backups=False, uninstall=True, purge_data=True)
    assert plan.uninstaller is None and logs in plan.data_dirs
    r = CliRunner().invoke(app, ["clean", "--uninstall", "--dry-run"])
    assert "uv tool uninstall audio-notes" in r.output
