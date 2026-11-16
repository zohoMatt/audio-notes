"""What the tray needs from the recorder. The integration step implements this Protocol."""

from __future__ import annotations

from typing import Protocol


class RecorderController(Protocol):
    def start(self) -> None:
        """Start a new recording session. May block (model load); the tray calls it off its UI thread.
        Raise on failure; the tray shows the error and `last_error()` should then return it."""

    def stop(self) -> None:
        """Stop recording and close the session. Safe to call when not recording."""

    def is_recording(self) -> bool: ...

    def mic_enabled(self) -> bool: ...

    def set_mic_enabled(self, enabled: bool) -> None:
        """Takes effect for the running session if possible, otherwise from the next start."""

    def last_error(self) -> str | None:
        """Short human-readable message for the current failure, or None when healthy."""

    def is_downloading_model(self) -> bool:
        """True while the ASR model is being downloaded (first run). The tray polls this."""
