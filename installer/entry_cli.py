"""Console entry point for audio-notes.exe (CLI and `mcp` over stdio)."""

import multiprocessing

from audio_notes.cli import app

if __name__ == "__main__":
    multiprocessing.freeze_support()
    app()
