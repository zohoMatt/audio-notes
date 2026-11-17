"""Regenerate installer/audio-notes.ico from the app icon drawn in audio_notes.tray.icons.

Run from the repo root after changing the icon design, then commit the .ico:
    uv run python installer/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from audio_notes.tray.icons import app_icon

SIZES = (16, 24, 32, 48, 64, 128, 256)
OUT = Path(__file__).with_name("audio-notes.ico")


def main() -> None:
    # Pillow resamples the largest image down to each size; start from a big, clean render.
    app_icon(512).save(OUT, format="ICO", sizes=[(s, s) for s in SIZES])
    print(f"Wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
