"""Dependency collection shared by installer/audio-notes.spec (Windows) and audio-notes-mac.spec.

Imported by the spec files (PyInstaller runs them with this folder on sys.path, see the specs).
Keep everything platform-specific in the `if` branches below so the two bundles cannot drift.
"""

from __future__ import annotations

import sys

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)

EXCLUDES = ["torch", "tensorflow", "matplotlib", "tkinter", "IPython", "pytest"]


def collect() -> tuple[list, list, list]:
    """(datas, binaries, hiddenimports) for the current platform."""
    datas, binaries, hiddenimports = [], [], []

    # Our own package: submodules (cli modules are imported via register(), tray/web lazily)
    # plus package data (audio_notes/web/static).
    hiddenimports += collect_submodules("audio_notes")
    datas += collect_data_files("audio_notes")

    # faster-whisper ships the Silero VAD ONNX under faster_whisper/assets/ (used by processing/vad.py).
    pkgs = ["faster_whisper", "ctranslate2", "onnxruntime", "av", "soxr", "tokenizers"]
    if sys.platform == "win32":
        pkgs.append("pystray")
    for pkg in pkgs:
        datas += collect_data_files(pkg)
        binaries += collect_dynamic_libs(pkg)
    hiddenimports += ["uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
                      "uvicorn.lifespan.on"]
    hiddenimports += collect_submodules("mcp")

    if sys.platform == "win32":
        hiddenimports += collect_submodules("pystray")  # backend is picked at runtime (_win32)
        hiddenimports += ["pyaudiowpatch"]
    elif sys.platform == "darwin":
        # The menu bar (tray/mac_statusbar.py) imports these lazily inside functions.
        hiddenimports += ["objc", "AppKit", "Foundation", "PyObjCTools.AppHelper"]

    # `audio-notes --version` reads importlib.metadata, so ship the dist-info.
    datas += copy_metadata("audio-notes")
    for dist in ("mcp", "faster-whisper", "ctranslate2", "onnxruntime"):
        try:
            datas += copy_metadata(dist)
        except Exception:
            pass
    return datas, binaries, hiddenimports
