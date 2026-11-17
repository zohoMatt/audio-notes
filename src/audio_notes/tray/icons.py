"""App and tray icons drawn with Pillow (no binary assets to package).

The app icon is an indigo rounded square holding a pencil whose body is a row of sound-wave
bars. Tray states other than idle add a round badge in the bottom-right corner: a play triangle
while recording, pause bars while paused, an exclamation mark on error, a down arrow while the
model downloads.
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
    TrayState.PAUSED: (100, 116, 139, 255),  # slate grey
    TrayState.ERROR: (234, 160, 12, 255),  # amber
    TrayState.DOWNLOADING: (56, 189, 248, 255),  # sky blue (readable on the indigo)
}
_SUPERSAMPLE = 8  # draw large, then downscale for smooth edges at tray sizes


def _rounded_square(n: int) -> Image.Image:
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle((0, 0, n - 1, n - 1), radius=n * 0.22, fill=_BG)
    return img


def _pencil(n: int, ink: tuple = _WHITE, eraser_ink: tuple = _ERASER) -> Image.Image:
    """White wave bars forming the pencil body, a white tip and a pink eraser; tip at lower left."""
    cx, cy, length, w = n * 0.52, n * 0.48, n * 0.88, n * 0.27
    layer = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x0, x1 = cx - length / 2, cx + length / 2
    y0, y1 = cy - w / 2, cy + w / 2
    tip, eraser = w, w * 0.45
    d.polygon([(x0, cy), (x0 + tip, y0), (x0 + tip, y1)], fill=ink)
    bars = (0.55, 0.90, 0.62, 1.0, 0.72, 0.50)
    bx0, bx1 = x0 + tip + w * 0.18, x1 - eraser - w * 0.18
    step = (bx1 - bx0) / len(bars)
    bw = step * 0.62
    for i, h in enumerate(bars):
        x = bx0 + i * step + (step - bw) / 2
        d.rounded_rectangle((x, cy - w * h / 2, x + bw, cy + w * h / 2), radius=bw / 2, fill=ink)
    d.rounded_rectangle((x1 - eraser, y0, x1, y1), radius=w * 0.12, fill=eraser_ink)
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
    elif state is TrayState.PAUSED:  # two bars
        u = r * 0.17
        for x in (cx - t * 0.45, cx + t * 0.45):
            d.rectangle((x - u, cy - t * 0.85, x + u, cy + t * 0.85), fill=_WHITE)
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


# ---- macOS menu bar ------------------------------------------------------------------------------
MENUBAR_PT = 18  # menu bar icons are 18x18 pt; rendered at 1x and 2x
_BLACK = (0, 0, 0, 255)
_CLEAR = (0, 0, 0, 0)
_RECORD_RED = (255, 59, 48, 255)  # NSColor.systemRed (light appearance)


def _menubar_badge(img: Image.Image, n: int, state: TrayState, ink: tuple) -> None:
    """Bottom-right badge: a clear ring separates it from the pencil. Recording is a solid red
    dot; the other states are an ink disc with the glyph knocked out (template friendly)."""
    r = n * 0.25
    cx = cy = n - r - n * 0.01
    d = ImageDraw.Draw(img)  # ImageDraw writes RGBA values as-is, so _CLEAR erases
    pad = r + n * 0.08
    d.ellipse((cx - pad, cy - pad, cx + pad, cy + pad), fill=_CLEAR)
    if state is TrayState.RECORDING:
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=_RECORD_RED)
        return
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=ink)
    t, u = r * 0.58, r * 0.17
    if state is TrayState.PAUSED:
        for x in (cx - t * 0.45, cx + t * 0.45):
            d.rectangle((x - u, cy - t * 0.8, x + u, cy + t * 0.8), fill=_CLEAR)
    elif state is TrayState.ERROR:
        d.rectangle((cx - u, cy - t, cx + u, cy + t * 0.25), fill=_CLEAR)
        d.ellipse((cx - u, cy + t * 0.55, cx + u, cy + t * 0.55 + 2 * u), fill=_CLEAR)
    else:  # downloading
        d.rectangle((cx - u, cy - t, cx + u, cy + t * 0.1), fill=_CLEAR)
        d.polygon([(cx - t * 0.8, cy), (cx + t * 0.8, cy), (cx, cy + t * 0.9)], fill=_CLEAR)


def menubar_icon(state: TrayState, scale: int = 1, dark: bool = False) -> tuple[Image.Image, bool]:
    """macOS menu bar icon for `state` at `scale` (1 = 18 px, 2 = 36 px) -> (image, is_template).

    Template images (black + alpha) are tinted by macOS for light, dark and tinted menu bars. The
    recording icon is not a template, so its red dot stays red; its pencil is drawn black or white
    to match the menu bar (`dark`), which the caller reads from the status item's appearance."""
    size = MENUBAR_PT * scale
    n = size * _SUPERSAMPLE
    template = state is not TrayState.RECORDING
    ink = _WHITE if (dark and not template) else _BLACK
    img = Image.new("RGBA", (n, n), _CLEAR)
    img.alpha_composite(_pencil(n, ink, ink))
    if state is not TrayState.IDLE:
        _menubar_badge(img, n, state, ink)
    return img.resize((size, size), Image.LANCZOS), template
