"""App and tray icons drawn with Pillow (no binary assets to package).

The app icon is an indigo rounded square holding a pencil whose body is a row of sound-wave
bars. Tray states other than idle add a round badge in the bottom-right corner: a play triangle
while recording, an exclamation mark on error, a down arrow while the model downloads.
`installer/make_icon.py` renders `app_icon` into the .ico used by the exe and the installer.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from audio_notes.tray.state import TrayState

_BG = (49, 46, 129, 255)  # indigo
_WHITE = (255, 255, 255, 255)
_ERASER = (244, 114, 182, 255)  # pink
_BADGE = {
    TrayState.RECORDING: (220, 38, 38, 255),  # red
    TrayState.ERROR: (234, 160, 12, 255),  # amber
    TrayState.DOWNLOADING: (56, 189, 248, 255),  # sky blue (readable on the indigo)
}
_SUPERSAMPLE = 8  # draw large, then downscale for smooth edges at tray sizes


def _rounded_square(n: int) -> Image.Image:
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle((0, 0, n - 1, n - 1), radius=n * 0.22, fill=_BG)
    return img


def _pencil(n: int) -> Image.Image:
    """White wave bars forming the pencil body, a white tip and a pink eraser; tip at lower left."""
    cx, cy, length, w = n * 0.52, n * 0.48, n * 0.88, n * 0.27
    layer = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x0, x1 = cx - length / 2, cx + length / 2
    y0, y1 = cy - w / 2, cy + w / 2
    tip, eraser = w, w * 0.45
    d.polygon([(x0, cy), (x0 + tip, y0), (x0 + tip, y1)], fill=_WHITE)
    bars = (0.55, 0.90, 0.62, 1.0, 0.72, 0.50)
    bx0, bx1 = x0 + tip + w * 0.18, x1 - eraser - w * 0.18
    step = (bx1 - bx0) / len(bars)
    bw = step * 0.62
    for i, h in enumerate(bars):
        x = bx0 + i * step + (step - bw) / 2
        d.rounded_rectangle((x, cy - w * h / 2, x + bw, cy + w * h / 2), radius=bw / 2, fill=_WHITE)
    d.rounded_rectangle((x1 - eraser, y0, x1, y1), radius=w * 0.12, fill=_ERASER)
    return layer.rotate(45, resample=Image.BICUBIC, center=(cx, cy))


def _badge(img: Image.Image, n: int, state: TrayState) -> None:
    r = n * 0.27
    cx = cy = n - r - n * 0.02
    # a ring in the background colour separates the badge from the pencil; keep it inside the square
    ring = Image.new("L", (n, n), 0)
    pad = r + n * 0.04
    ImageDraw.Draw(ring).ellipse((cx - pad, cy - pad, cx + pad, cy + pad), fill=255)
    square = _rounded_square(n).getchannel("A")
    img.paste(Image.new("RGBA", (n, n), _BG), (0, 0), Image.composite(ring, Image.new("L", (n, n), 0), square))
    d = ImageDraw.Draw(img)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=_BADGE[state])
    t = r * 0.55
    if state is TrayState.RECORDING:  # play triangle
        d.polygon([(cx - t * 0.7, cy - t), (cx - t * 0.7, cy + t), (cx + t, cy)], fill=_WHITE)
    elif state is TrayState.ERROR:  # exclamation mark
        u = r * 0.16
        d.rectangle((cx - u, cy - t, cx + u, cy + t * 0.25), fill=_WHITE)
        d.ellipse((cx - u, cy + t * 0.55, cx + u, cy + t * 0.55 + 2 * u), fill=_WHITE)
    else:  # downloading: down arrow
        u = r * 0.16
        d.rectangle((cx - u, cy - t, cx + u, cy + t * 0.1), fill=_WHITE)
        d.polygon([(cx - t * 0.8, cy), (cx + t * 0.8, cy), (cx, cy + t * 0.9)], fill=_WHITE)


def _render(size: int, state: TrayState | None) -> Image.Image:
    n = size * _SUPERSAMPLE
    img = _rounded_square(n)
    img.alpha_composite(_pencil(n))
    if state in _BADGE:
        _badge(img, n, state)
    return img.resize((size, size), Image.LANCZOS)


def app_icon(size: int = 256) -> Image.Image:
    """The plain app icon (no state badge): exe, installer and Start Menu."""
    return _render(size, None)


def make_icon(state: TrayState, size: int = 64) -> Image.Image:
    """Tray icon for `state`; idle is the plain app icon."""
    return _render(size, state)
