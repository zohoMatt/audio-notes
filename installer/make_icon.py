"""Regenerate the packaged app icons from the design drawn in audio_notes.tray.icons.

- installer/audio-notes.ico    Windows exe and installer (any OS)
- installer/AudioNotes.icns    macOS .app (needs macOS: uses `iconutil`)

Run from the repo root after changing the icon design, then commit both files:
    uv run python installer/make_icon.py            # both (.icns only on macOS)
    uv run python installer/make_icon.py --ico      # only the .ico
    uv run python installer/make_icon.py --icns     # only the .icns
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageFilter

from audio_notes.tray.icons import app_icon

HERE = Path(__file__).resolve().parent
ICO = HERE / "audio-notes.ico"
ICNS = HERE / "AudioNotes.icns"
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)

# Apple's macOS icon grid (Big Sur and later): a 1024 canvas holding an 824x824 rounded square
# centred with 100 px margins, plus a soft drop shadow. Our rounded square already uses a ~22%
# corner radius, close to Apple's (185/824).
MAC_CANVAS, MAC_BODY = 1024, 824
# name in the .iconset -> pixel size (iconutil requires exactly these names)
ICONSET = {
    "icon_16x16.png": 16, "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32, "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128, "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256, "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512, "icon_512x512@2x.png": 1024,
}


def write_ico() -> None:
    # Pillow resamples the largest image down to each size; start from a big, clean render.
    app_icon(512).save(ICO, format="ICO", sizes=[(s, s) for s in ICO_SIZES])
    print(f"Wrote {ICO} ({ICO.stat().st_size} bytes)")


def mac_master() -> Image.Image:
    """The 1024x1024 macOS icon: the app icon on Apple's grid with a drop shadow."""
    body = app_icon(MAC_BODY)
    margin = (MAC_CANVAS - MAC_BODY) // 2
    shadow = Image.new("RGBA", (MAC_CANVAS, MAC_CANVAS), (0, 0, 0, 0))
    alpha = body.getchannel("A").point(lambda a: a * 0.35)
    shadow.paste((0, 0, 0, 255), (margin, margin + 12), alpha)
    img = shadow.filter(ImageFilter.GaussianBlur(14))
    img.alpha_composite(body, (margin, margin))
    return img


def write_icns() -> None:
    iconutil = shutil.which("iconutil")
    if sys.platform != "darwin" or iconutil is None:
        raise SystemExit("The .icns needs macOS (iconutil); run with --ico elsewhere.")
    master = mac_master()
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "AudioNotes.iconset"
        iconset.mkdir()
        for name, px in ICONSET.items():
            master.resize((px, px), Image.LANCZOS).save(iconset / name, format="PNG")
        subprocess.run([iconutil, "-c", "icns", str(iconset), "-o", str(ICNS)], check=True)
    print(f"Wrote {ICNS} ({ICNS.stat().st_size} bytes)")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--ico", action="store_true", help="only the Windows .ico")
    p.add_argument("--icns", action="store_true", help="only the macOS .icns")
    a = p.parse_args()
    both = not (a.ico or a.icns)
    if a.ico or both:
        write_ico()
    if a.icns or (both and sys.platform == "darwin"):
        write_icns()


if __name__ == "__main__":
    main()
