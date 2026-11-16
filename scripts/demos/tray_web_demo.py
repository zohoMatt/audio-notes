"""Demo of the tray icon + local web panel.

Run from the repo: uv run python scripts/demos/tray_web_demo.py
Starts the real TrayApp (fake recorder) and the real PanelServer on the default port (8765).
Right-click the tray icon: "Start recording" begins feeding a canned two-speaker conversation
through SessionWriter into a temporary data dir; "Pause recording" stops it. Double-click the
icon (or "Open panel") to open the browser with the token URL. The URL is also printed here.
Never touches the real %APPDATA% data or Claude config; "Connect to Claude" writes to a temp file.
Set DEMO_PORT to use another port; DEMO_NO_TRAY=1 runs only the panel (feeder starts at once).
"""
import os
import sys
import tempfile
import threading
import time

DATA = tempfile.mkdtemp(prefix="audio-notes-demo-")
os.environ["AUDIO_NOTES_DATA_DIR"] = DATA
os.environ["AUDIO_NOTES_CLAUDE_CONFIG"] = os.path.join(DATA, "claude_desktop_config.json")

from audio_notes.config import Config  # noqa: E402
from audio_notes.store.reader import StoreReader  # noqa: E402
from audio_notes.store.writer import SessionWriter  # noqa: E402
from audio_notes.tray import first_run  # noqa: E402
from audio_notes.tray.app import TrayApp  # noqa: E402
from audio_notes.web.server import PanelServer  # noqa: E402

SCRIPT = [
    ("them", "Okay, let's start with the Q3 budget review."),
    ("me", "Sure. I think the marketing line is over by about ten percent."),
    ("them", "That's the campaign we launched in August."),
    ("me", "Right, can we move some of the travel budget to cover it?"),
    ("them", "Travel is already tight. What about the contractor budget?"),
    ("me", "Contractors finish in September, so there should be room."),
    ("them", "Good. Let's also schedule a follow-up meeting next Tuesday."),
    ("me", "Works for me. I'll send the invite after this call."),
]


class FakeController:
    """Implements RecorderController; 'recording' feeds the canned conversation."""

    def __init__(self):
        self._mic = True
        self._stop = threading.Event()
        self._thread = None
        self._writer = None

    def start(self):
        self._stop.clear()
        self._writer = SessionWriter()
        self._thread = threading.Thread(target=self._feed, args=(self._writer,), daemon=True)
        self._thread.start()

    def _feed(self, w):
        t0 = time.monotonic()
        for who, text in SCRIPT:
            if self._stop.wait(2.5):
                break
            if who == "me" and not self._mic:
                continue
            a = time.monotonic() - t0
            w.append(a - 2.0, a, who, text)
        # canned script finished: keep the session open (heartbeat) until paused

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        if self._writer:
            self._writer.close()
        self._writer = self._thread = None

    def is_recording(self):
        return self._writer is not None

    def mic_enabled(self):
        return self._mic

    def set_mic_enabled(self, enabled):
        self._mic = enabled

    def last_error(self):
        return None

    def is_downloading_model(self):
        return False


def main():
    port = int(os.environ.get("DEMO_PORT", Config.from_env().web_port))
    panel = PanelServer(StoreReader(), port)
    panel.start()
    print(f"data dir : {DATA}")
    print(f"panel    : {panel.url}")
    ctrl = FakeController()
    try:
        if os.environ.get("DEMO_NO_TRAY"):
            ctrl.start()
            print("panel only; Ctrl+C to stop")
            while True:
                time.sleep(1)
        # the demo has its own first-run flag (temp dir), so the legal notice shows once per run
        app = TrayApp(ctrl, panel.url)
        print("tray running; right-click the icon. Quit from its menu.")
        app.run()
    except KeyboardInterrupt:
        pass
    finally:
        ctrl.stop()
        panel.stop()


if __name__ == "__main__":
    sys.exit(main())
