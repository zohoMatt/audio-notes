"""Stand-in for the Swift `audio-notes-capture` helper, speaking the same wire protocol.

Run as `python fake_mac_helper.py <mode>`; FAKE_HELPER_SCENARIO picks the behaviour of tap / mic:
  normal         ready, then 10 ms frames until stdin closes (exit 0)
  permission     exit 12 at once (permission denied), with a stderr line
  unavailable    exit 15 at once: system audio cannot be granted to the launching app ("claude")
  device_change  ready, three frames, exit 10
  garbage        ready, then bytes that are not a frame
  hang           never send anything (exits when stdin closes)
  ignore_stdin   like normal but ignores stdin EOF (needs terminate/kill)
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402

from audio_notes.capture.mac_tap import encode_frame, encode_ready  # noqa: E402

RATE = 48000
N = 480  # 10 ms


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    scenario = os.environ.get("FAKE_HELPER_SCENARIO", "normal")
    out = sys.stdout.buffer
    if mode == "list":
        print(json.dumps({"devices": [
            {"uid": "spk", "name": "MacBook Speakers", "inputs": 0, "outputs": 2, "sample_rate": 48000,
             "default_input": False, "default_output": True},
            {"uid": "mic", "name": "MacBook Microphone", "inputs": 1, "outputs": 0, "sample_rate": 48000,
             "default_input": True, "default_output": False},
            {"uid": "usb", "name": "USB Headset", "inputs": 1, "outputs": 2, "sample_rate": 44100,
             "default_input": False, "default_output": False},
        ]}))
        return 0
    if mode == "permissions":
        print(json.dumps({"microphone": os.environ.get("FAKE_MIC", "authorized"),
                          "system_audio": os.environ.get("FAKE_SYSTEM_AUDIO", "denied"),
                          "responsible": os.environ.get("FAKE_RESPONSIBLE", "Terminal")}))
        return 0
    if mode not in ("tap", "mic"):
        print("usage", file=sys.stderr)
        return 2

    if scenario == "permission":
        print("audio-notes-capture: permission denied", file=sys.stderr, flush=True)
        return 12
    if scenario == "unavailable":
        print("audio-notes-capture: system audio recording (still undetermined after the prompt) "
              "cannot be granted to claude", file=sys.stderr, flush=True)
        return 15

    stop = threading.Event()
    if scenario != "ignore_stdin":
        threading.Thread(target=lambda: (sys.stdin.buffer.read(), stop.set()), daemon=True).start()
    if scenario == "hang":
        stop.wait(30)
        return 0

    out.write(encode_ready(RATE, "Fake Output" if mode == "tap" else "Fake Mic"))
    out.flush()
    print(f"audio-notes-capture: {mode} started", file=sys.stderr, flush=True)
    if scenario == "garbage":
        out.write(b"XXXX" * 8)
        out.flush()
        stop.wait(30)
        return 0
    sent = 0
    value = 0.25 if mode == "tap" else -0.5
    while not stop.is_set():
        now = time.monotonic_ns()
        out.write(encode_frame(np.full(N, value, dtype=np.float32), RATE, host_ns=now - 10_000_000, sent_ns=now))
        out.flush()
        sent += 1
        if scenario == "device_change" and sent == 3:
            return 10
        time.sleep(0.01)
    return 0


if __name__ == "__main__":
    try:
        code = main()
        sys.stdout.flush()
        sys.stderr.flush()
    except (BrokenPipeError, OSError):
        code = 0
    # os._exit: a normal interpreter shutdown can crash on Windows while the daemon thread is
    # still blocked reading stdin.
    os._exit(code)
