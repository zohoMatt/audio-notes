"""STUB owned by track A: `audio-notes devices` (list loopback / microphone devices)."""

from __future__ import annotations

import typer

from ._todo import not_implemented


def register(app: typer.Typer) -> None:
    @app.command()
    def devices() -> None:
        """List audio devices."""
        not_implemented("devices")
