"""Tray icons drawn with Pillow at runtime (no binary assets to package)."""

from __future__ import annotations

from PIL import Image, ImageDraw

from audio_notes.tray.state import TrayState

_COLORS = {
    TrayState.IDLE: (110, 118, 135, 255),  # grey
    TrayState.RECORDING: (220, 38, 38, 255),  # red
    TrayState.ERROR: (234, 160, 12, 255),  # amber
    TrayState.DOWNLOADING: (37, 99, 235, 255),  # blue
}
_WHITE = (255, 255, 255, 255)


def make_icon(state: TrayState, size: int = 64) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = size // 16
    d.ellipse((pad, pad, size - pad - 1, size - pad - 1), fill=_COLORS[state])
    c, u = size / 2, size / 16  # centre and a sixteenth-unit for the glyph
    if state is TrayState.RECORDING:
        d.ellipse((c - 3 * u, c - 3 * u, c + 3 * u, c + 3 * u), fill=_WHITE)
    elif state is TrayState.IDLE:  # pause-like bars read as "stopped/idle"
        d.rectangle((c - 3.5 * u, c - 3 * u, c - 1 * u, c + 3 * u), fill=_WHITE)
        d.rectangle((c + 1 * u, c - 3 * u, c + 3.5 * u, c + 3 * u), fill=_WHITE)
    elif state is TrayState.ERROR:  # exclamation mark
        d.rectangle((c - u, c - 5 * u, c + u, c + 1 * u), fill=_WHITE)
        d.ellipse((c - u, c + 2.5 * u, c + u, c + 4.5 * u), fill=_WHITE)
    else:  # downloading: down arrow
        d.rectangle((c - u, c - 5 * u, c + u, c + 1 * u), fill=_WHITE)
        d.polygon([(c - 4 * u, c), (c + 4 * u, c), (c, c + 5 * u)], fill=_WHITE)
    return img
