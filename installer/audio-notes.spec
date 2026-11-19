# PyInstaller spec: ONE onedir bundle, TWO executables sharing the same libraries.
#   audio-notes.exe        console subsystem  (CLI and `mcp` over stdio)
#   audio-notes-tray.exe   windowed subsystem (tray, no console window)
# Run from the repo root:  pyinstaller installer/audio-notes.spec --noconfirm
import sys
from pathlib import Path

HERE = Path(SPECPATH)  # noqa: F821 (injected by PyInstaller)
sys.path.insert(0, str(HERE))
from spec_common import EXCLUDES, collect  # noqa: E402  (shared with audio-notes-mac.spec)

ICON = str(HERE / "audio-notes.ico")  # regenerate with installer/make_icon.py

datas, binaries, hiddenimports = collect()


def analysis(script):
    return Analysis(  # noqa: F821
        [str(HERE / script)],
        pathex=[str(HERE.parent / "src")],
        binaries=binaries,
        datas=datas,
        hiddenimports=hiddenimports,
        excludes=EXCLUDES,
        noarchive=False,
    )


a_cli = analysis("entry_cli.py")
a_tray = analysis("entry_tray.py")
MERGE((a_cli, "audio-notes", "audio-notes"), (a_tray, "audio-notes-tray", "audio-notes-tray"))  # noqa: F821

pyz_cli = PYZ(a_cli.pure)  # noqa: F821
pyz_tray = PYZ(a_tray.pure)  # noqa: F821

exe_cli = EXE(  # noqa: F821
    pyz_cli, a_cli.scripts, [], exclude_binaries=True, name="audio-notes",
    console=True, upx=False, icon=ICON,
)
exe_tray = EXE(  # noqa: F821
    pyz_tray, a_tray.scripts, [], exclude_binaries=True, name="audio-notes-tray",
    console=False, upx=False, icon=ICON,
)

COLLECT(  # noqa: F821
    exe_cli, a_cli.binaries, a_cli.datas,
    exe_tray, a_tray.binaries, a_tray.datas,
    strip=False, upx=False, name="audio-notes",
)
