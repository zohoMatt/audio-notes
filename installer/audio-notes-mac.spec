# PyInstaller spec for macOS: `Audio Notes.app` holding TWO executables that share one set of
# libraries (same idea as the Windows spec, which uses MERGE; BUNDLE does not support MERGE, so
# the two analyses are simply collected together and duplicates are dropped):
#   Contents/MacOS/Audio Notes          menu bar app (CFBundleExecutable); with arguments = CLI
#   Contents/MacOS/audio-notes          CLI and `mcp` over stdio (what Claude's config points at)
#   Contents/MacOS/audio-notes-capture  Swift capture helper (macos/capture), found by capture/mac_tap.py
#
# Normally run through installer/build_mac.sh, which builds the helper first and signs the result.
# By hand, from the repo root:
#   swift build -c release --package-path macos/capture
#   pyinstaller installer/audio-notes-mac.spec --noconfirm
# Environment (all optional):
#   AUDIO_NOTES_VERSION        version string (default: audio_notes.__version__)
#   AUDIO_NOTES_BUILD_NUMBER   CFBundleVersion (default: the numeric short version)
#   AUDIO_NOTES_CAPTURE_BIN    path of the built helper (default: macos/capture/.build/release/...)
import os
import re
import sys
from pathlib import Path

HERE = Path(SPECPATH)  # noqa: F821 (injected by PyInstaller)
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from spec_common import EXCLUDES, collect  # noqa: E402  (shared with audio-notes.spec)

APP_NAME = "Audio Notes"
BUNDLE_ID = "io.github.zohomatt.audionotes"  # never change: TCC permissions are keyed on it
ICON = str(HERE / "AudioNotes.icns")  # regenerate with installer/make_icon.py
HELPER = Path(os.environ.get("AUDIO_NOTES_CAPTURE_BIN")
              or ROOT / "macos" / "capture" / ".build" / "release" / "audio-notes-capture")
if not HELPER.is_file():
    raise SystemExit(f"Capture helper not found at {HELPER}; run "
                     "`swift build -c release --package-path macos/capture` first.")


def _version() -> str:
    v = os.environ.get("AUDIO_NOTES_VERSION")
    if v:
        return v
    sys.path.insert(0, str(ROOT / "src"))
    from audio_notes import __version__

    return __version__


VERSION = _version()
# CFBundleShortVersionString must be 1-3 dot-separated integers: 0.2.1rc2.dev13+g1234 -> 0.2.1
m = re.match(r"\d+(\.\d+){0,2}", VERSION)
SHORT_VERSION = m.group(0) if m else "0.0.0"
BUILD_NUMBER = os.environ.get("AUDIO_NOTES_BUILD_NUMBER") or SHORT_VERSION

datas, binaries, hiddenimports = collect()


def analysis(script):
    return Analysis(  # noqa: F821
        [str(HERE / script)],
        pathex=[str(ROOT / "src")],
        binaries=binaries,
        datas=datas,
        hiddenimports=hiddenimports,
        excludes=EXCLUDES,
        noarchive=False,
    )


a_app = analysis("entry_mac_app.py")
a_cli = analysis("entry_cli.py")

# Signing happens afterwards in build_mac.sh (inside-out, with entitlements), not here.
exe_app = EXE(  # noqa: F821
    PYZ(a_app.pure), a_app.scripts, [], exclude_binaries=True, name=APP_NAME,  # noqa: F821
    console=False, argv_emulation=False, upx=False, strip=False, target_arch="arm64",
)
exe_cli = EXE(  # noqa: F821
    PYZ(a_cli.pure), a_cli.scripts, [], exclude_binaries=True, name="audio-notes",  # noqa: F821
    console=True, argv_emulation=False, upx=False, strip=False, target_arch="arm64",
)

coll = COLLECT(  # noqa: F821
    exe_app, a_app.binaries, a_app.datas,
    exe_cli, a_cli.binaries, a_cli.datas,
    # EXECUTABLE entries land in Contents/MacOS untouched (no rpath rewriting, unlike BINARY).
    [("audio-notes-capture", str(HELPER), "EXECUTABLE")],
    strip=False, upx=False, name="audio-notes-mac",
)

app = BUNDLE(  # noqa: F821
    coll,
    name=f"{APP_NAME}.app",
    icon=ICON,
    bundle_identifier=BUNDLE_ID,
    version=SHORT_VERSION,
    info_plist={
        "CFBundleExecutable": APP_NAME,
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleShortVersionString": SHORT_VERSION,
        "CFBundleVersion": BUILD_NUMBER,
        "LSMinimumSystemVersion": "14.2",
        "LSUIElement": True,  # menu bar only, no Dock icon
        # BUNDLE sets LSBackgroundOnly=True when the last EXE is a console one (the CLI here);
        # that would forbid any UI, including the menu bar item.
        "LSBackgroundOnly": False,
        "LSApplicationCategoryType": "public.app-category.productivity",
        "NSHumanReadableCopyright": "MIT License",
        "NSMicrophoneUsageDescription":
            "Audio Notes transcribes your side of the conversation locally.",
        "NSAudioCaptureUsageDescription":
            "Audio Notes transcribes what other participants say, on this Mac only.",
    },
)
