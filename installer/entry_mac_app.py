"""Entry point for `Audio Notes.app/Contents/MacOS/Audio Notes` (the bundle's main executable).

- No arguments (Finder, Dock, `open`): the menu bar app, i.e. `audio-notes tray`.
- Any arguments: the regular CLI. This keeps `"Audio Notes" mcp` working if something (an older
  `server_command()`, a hand-written Claude config) points at the main executable instead of its
  CLI sibling `Contents/MacOS/audio-notes` (installer/entry_cli.py).
"""

import multiprocessing
import os
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    if sys.stdin is None:
        sys.stdin = open(os.devnull, encoding="utf-8")
    # Older macOS versions pass a `-psn_0_12345` process serial number when launched from Finder.
    args = [a for a in sys.argv[1:] if not a.startswith("-psn_")]
    from audio_notes.cli import app

    sys.argv = [sys.argv[0], *(args or ["tray"])]
    app()
