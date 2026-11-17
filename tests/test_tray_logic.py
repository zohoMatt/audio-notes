from pathlib import Path

import pytest

from audio_notes.tray import first_run
from audio_notes.tray.app import TrayApp
from audio_notes.tray.icons import make_icon
from audio_notes.tray.state import TrayState, compute_state, describe


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIO_NOTES_DATA_DIR", str(tmp_path))
    return tmp_path


# ---- state machine -----------------------------------------------------------
@pytest.mark.parametrize(
    "recording,error,downloading,expected",
    [
        (False, None, False, TrayState.IDLE),
        (True, None, False, TrayState.RECORDING),
        (False, "boom", False, TrayState.ERROR),
        (True, "boom", False, TrayState.ERROR),
        (False, None, True, TrayState.DOWNLOADING),
        (False, "boom", True, TrayState.ERROR),
    ],
)
def test_compute_state(recording, error, downloading, expected):
    assert compute_state(recording, error, downloading) is expected


def test_compute_state_paused():
    assert compute_state(True, None, False, paused=True) is TrayState.PAUSED
    assert compute_state(True, "boom", False, paused=True) is TrayState.ERROR
    assert compute_state(False, None, False, paused=True) is TrayState.IDLE


def test_describe_menu_availability():
    idle = describe(TrayState.IDLE)
    assert idle.toggle_label == "Start recording" and idle.toggle_enabled
    assert not idle.stop_visible
    rec = describe(TrayState.RECORDING)
    assert rec.toggle_label == "Pause recording" and rec.toggle_enabled and rec.stop_visible
    paused = describe(TrayState.PAUSED)
    assert paused.toggle_label == "Continue recording" and paused.stop_visible and not paused.mic_enabled
    assert "paused" in paused.tooltip
    dl = describe(TrayState.DOWNLOADING)
    assert not dl.toggle_enabled and not dl.mic_enabled and "download" in dl.tooltip
    err = describe(TrayState.ERROR, "no device")
    assert err.toggle_enabled and "no device" in err.tooltip


def test_tooltip_truncated_to_windows_limit():
    assert len(describe(TrayState.ERROR, "x" * 500).tooltip) <= 127


# ---- icons -------------------------------------------------------------------
def test_icons_distinct_per_state():
    imgs = {s: make_icon(s) for s in TrayState}
    for img in imgs.values():
        assert img.size == (64, 64) and img.mode == "RGBA"
        assert img.getbbox() is not None
    assert len({img.tobytes() for img in imgs.values()}) == len(TrayState)
    assert make_icon(TrayState.IDLE, 32).size == (32, 32)


def test_idle_icon_is_the_plain_app_icon_and_states_add_a_corner_badge():
    from audio_notes.tray.icons import app_icon

    assert make_icon(TrayState.IDLE, 64).tobytes() == app_icon(64).tobytes()
    plain = app_icon(64)
    # the badge sits bottom-right; the top-left corner is identical in every state
    for s in (TrayState.RECORDING, TrayState.ERROR, TrayState.DOWNLOADING):
        img = make_icon(s, 64)
        assert img.crop((0, 0, 24, 24)).tobytes() == plain.crop((0, 0, 24, 24)).tobytes()
        assert img.crop((40, 40, 64, 64)).tobytes() != plain.crop((40, 40, 64, 64)).tobytes()


def test_shipped_ico_has_the_expected_sizes():
    from pathlib import Path

    from PIL import Image

    ico = Path(__file__).resolve().parents[1] / "installer" / "audio-notes.ico"
    with Image.open(ico) as im:
        assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= set(im.info["sizes"])


# ---- first run ---------------------------------------------------------------
def test_first_run_accept_writes_flag_and_stops_asking():
    calls = []
    assert first_run.ensure_acknowledged(lambda t, m: calls.append(m) or True) is True
    assert first_run.is_acknowledged() and first_run.flag_path().parent == first_run.paths.data_dir()
    assert first_run.ensure_acknowledged(lambda t, m: pytest.fail("asked twice")) is True
    assert len(calls) == 1


def test_first_run_decline_writes_nothing():
    assert first_run.ensure_acknowledged(lambda t, m: False) is False
    assert not first_run.is_acknowledged()
    # asks again next time
    assert first_run.ensure_acknowledged(lambda t, m: True) is True


# ---- TrayApp actions (no pystray) ----------------------------------------------
class FakeController:
    def __init__(self):
        self.recording = False
        self.paused = False
        self.mic = True
        self.error = None
        self.downloading = False
        self.fail_start = False

    def start(self):
        if self.fail_start:
            raise RuntimeError("no device")
        self.recording = True

    def stop(self):
        self.recording = self.paused = False

    def pause(self):
        self.paused = self.recording

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
        return self.downloading


def make_app(ctrl=None, **kw):
    return TrayApp(ctrl or FakeController(), "http://127.0.0.1:1/?token=t", **kw)


def test_run_declined_never_records_or_shows_icon():
    ctrl = FakeController()
    app = make_app(ctrl, first_run_dialog=lambda t, m: False)
    assert app.run() is False
    assert ctrl.recording is False and app._icon is None


def test_toggle_actions():
    ctrl = FakeController()
    app = make_app(ctrl)
    app.toggle_recording()
    assert ctrl.recording and app.view().state is TrayState.RECORDING
    app.toggle_recording()  # pause: the session stays open
    assert ctrl.recording and ctrl.paused and app.view().state is TrayState.PAUSED
    assert app.view().toggle_label == "Continue recording"
    app.toggle_recording()  # continue
    assert ctrl.recording and not ctrl.paused
    app.toggle_recording()
    app.stop_recording()  # stop works while paused
    assert not ctrl.recording and not ctrl.paused
    app.toggle_mic()
    assert ctrl.mic is False
    ctrl.fail_start = True
    app.toggle_recording()  # must not raise
    assert not ctrl.recording


def test_open_panel_and_folder(tmp_path):
    opened, folders = [], []
    app = make_app(open_url=opened.append, open_folder=folders.append)
    app.open_panel()
    app.open_transcripts()
    assert opened == ["http://127.0.0.1:1/?token=t"]
    assert folders == [tmp_path / "sessions"]


def test_connect_to_claude_confirm_then_merge(tmp_path):
    cfg = tmp_path / "claude.json"
    merged = []
    app = make_app(
        confirm=lambda t, m: str(cfg) in m,
        merge_config=lambda p: merged.append(p),
        claude_config_path=lambda: cfg,
    )
    app.connect_to_claude()
    assert merged == [cfg]


def test_connect_to_claude_declined_and_failure(tmp_path):
    merged = []
    app = make_app(confirm=lambda t, m: False, merge_config=merged.append, claude_config_path=lambda: Path("x"))
    app.connect_to_claude()
    assert merged == []

    def boom(p):
        raise ValueError("bad json")

    app = make_app(confirm=lambda t, m: True, merge_config=boom, claude_config_path=lambda: Path("x"))
    app.connect_to_claude()  # reports via notification/log, must not raise


def test_connect_to_claude_not_installed_skips_prompt_and_merge(tmp_path):
    merged, asked = [], []
    app = make_app(
        confirm=lambda t, m: asked.append(m) or True,
        merge_config=merged.append,
        claude_config_path=lambda: tmp_path / "no-claude" / "cfg.json",
    )
    app.connect_to_claude()
    assert merged == [] and asked == []


def test_quit_stops_recording():
    ctrl = FakeController()
    ctrl.recording = True
    quit_called = []
    app = make_app(ctrl, on_quit=lambda: quit_called.append(1))
    app.quit()
    assert not ctrl.recording and quit_called == [1]


def test_microphone_cannot_be_switched_while_recording():
    rec = describe(TrayState.RECORDING)
    assert not rec.mic_enabled and "after stopping" in rec.mic_label
    assert describe(TrayState.IDLE).mic_enabled and describe(TrayState.IDLE).mic_label == "Microphone"
    ctrl = FakeController()
    app = make_app(ctrl)
    app.toggle_recording()
    app.toggle_mic()  # ignored while recording
    assert ctrl.mic is True and not app.view().mic_enabled
    app.toggle_recording()
    app.toggle_mic()  # still ignored while paused
    assert ctrl.mic is True
    app.stop_recording()
    app.toggle_mic()
    assert ctrl.mic is False


def test_error_while_recording_still_offers_stop():
    v = describe(TrayState.ERROR, "device lost (retrying)", recording=True)
    assert v.toggle_label == "Pause recording" and not v.mic_enabled
    ctrl = FakeController()
    ctrl.recording, ctrl.error = True, "device lost (retrying)"
    app = make_app(ctrl)
    assert app.view().state is TrayState.ERROR and app.view().toggle_label == "Pause recording"
    assert app.view().stop_visible
    app.toggle_recording()
    assert ctrl.paused and app.view().toggle_label == "Continue recording"
    app.stop_recording()
    assert ctrl.recording is False
