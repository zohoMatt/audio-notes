"""Hatch build hook: on macOS, compile the Swift capture helper and ship it inside the wheel.

- Windows / Linux: does nothing; the wheel stays pure Python (`py3-none-any`).
- macOS, regular wheel (`uv build`, `uv tool install <path or git URL>`, pip from the sdist):
  runs `swift build -c release` in macos/capture, puts the binary at
  `audio_notes/capture/bin/audio-notes-capture` and tags the wheel for macOS 14+ on this CPU.
- macOS, editable install (`uv sync` in a checkout): builds the helper but does not copy it;
  `capture/mac_tap.py` finds it in macos/capture/.build/release/ (rebuild after Swift edits with
  `swift build -c release --package-path macos/capture`).

Needs Xcode or the Command Line Tools (`xcode-select --install`). Set AUDIO_NOTES_SKIP_HELPER_BUILD=1
to build without it (the app then cannot record on macOS until a helper is provided, e.g. via
AUDIO_NOTES_CAPTURE_HELPER).
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

HELPER = "audio-notes-capture"
SKIP_ENV = "AUDIO_NOTES_SKIP_HELPER_BUILD"
MACOS_MIN = "14_0"  # Package.swift platforms; the process tap itself needs 14.2 (checked at run time)


class CustomBuildHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict) -> None:
        if self.target_name != "wheel" or sys.platform != "darwin":
            return
        if os.environ.get(SKIP_ENV):
            self.app.display_warning(f"{SKIP_ENV} is set: building without the macOS capture helper")
            return
        package = Path(self.root) / "macos" / "capture"
        if not (package / "Package.swift").is_file():
            self.app.display_warning("macos/capture not found: building without the macOS capture helper")
            return
        swift = shutil.which("swift")
        if swift is None:
            raise RuntimeError(
                "Building audio-notes on macOS compiles its Swift capture helper, but `swift` was not found. "
                f"Install the Command Line Tools (xcode-select --install), or set {SKIP_ENV}=1 to skip it."
            )
        cmd = [swift, "build", "-c", "release", "--package-path", str(package)]
        self.app.display_info("Building the macOS capture helper: " + " ".join(cmd))
        subprocess.run(cmd, check=True)
        bin_dir = subprocess.run(cmd + ["--show-bin-path"], check=True, capture_output=True, text=True).stdout.strip()
        binary = Path(bin_dir) / HELPER
        if not binary.is_file():
            raise RuntimeError(f"swift build did not produce {binary}")
        if version == "editable":
            return  # mac_tap.py looks in macos/capture/.build/release/ for source-tree installs
        build_data["force_include"][str(binary)] = f"audio_notes/capture/bin/{HELPER}"
        build_data["pure_python"] = False
        arch = "arm64" if platform.machine() == "arm64" else "x86_64"
        build_data["tag"] = f"py3-none-macosx_{MACOS_MIN}_{arch}"
