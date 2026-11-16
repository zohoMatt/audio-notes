"""Windowed entry point for audio-notes-tray.exe: runs `audio-notes tray` without a console."""

import multiprocessing
import os
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    # A windowed exe has no stdio; give libraries something harmless to write to.
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    if sys.stdin is None:
        sys.stdin = open(os.devnull, encoding="utf-8")
    from audio_notes.cli import app

    sys.argv = [sys.argv[0], "tray"]
    app()
