# PyInstaller spec: ONE onedir bundle, TWO executables sharing the same libraries.
#   audio-notes.exe        console subsystem  (CLI and `mcp` over stdio)
#   audio-notes-tray.exe   windowed subsystem (tray, no console window)
# Run from the repo root:  pyinstaller installer/audio-notes.spec --noconfirm
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)

HERE = Path(SPECPATH)  # noqa: F821 (injected by PyInstaller)

datas, binaries, hiddenimports = [], [], []

# Our own package: submodules (cli modules are imported via register(), tray/web lazily)
# plus package data, e.g. audio_notes/web/static once the web panel lands.
hiddenimports += collect_submodules("audio_notes")
datas += collect_data_files("audio_notes")

# faster-whisper ships the Silero VAD ONNX under faster_whisper/assets/ (used by processing/vad.py).
for pkg in ("faster_whisper", "ctranslate2", "onnxruntime", "av", "soxr", "pystray", "tokenizers"):
    datas += collect_data_files(pkg)
    binaries += collect_dynamic_libs(pkg)
hiddenimports += collect_submodules("pystray")  # backend is picked at runtime (_win32)
hiddenimports += ["uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
                  "uvicorn.lifespan.on"]
hiddenimports += collect_submodules("mcp")
hiddenimports += ["pyaudiowpatch"]

# `audio-notes --version` reads importlib.metadata, so ship the dist-info.
datas += copy_metadata("audio-notes")
for dist in ("mcp", "faster-whisper", "ctranslate2", "onnxruntime"):
    try:
        datas += copy_metadata(dist)
    except Exception:
        pass

EXCLUDES = ["torch", "tensorflow", "matplotlib", "tkinter", "IPython", "pytest"]


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
    console=True, upx=False,
)
exe_tray = EXE(  # noqa: F821
    pyz_tray, a_tray.scripts, [], exclude_binaries=True, name="audio-notes-tray",
    console=False, upx=False,
)

COLLECT(  # noqa: F821
    exe_cli, a_cli.binaries, a_cli.datas,
    exe_tray, a_tray.binaries, a_tray.datas,
    strip=False, upx=False, name="audio-notes",
)
