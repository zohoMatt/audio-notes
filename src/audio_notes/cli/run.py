"""Owned by the integration step (after tracks A-D land): `tray`, `record`. `mcp` is ready."""

from __future__ import annotations

import typer

from ._todo import not_implemented


def register(app: typer.Typer) -> None:
    @app.command()
    def mcp() -> None:
        """Run the MCP server over stdio."""
        from audio_notes.mcp_server import main

        main()

    @app.command()
    def tray() -> None:
        """Start the tray daemon."""
        not_implemented("tray")

    @app.command()
    def record() -> None:
        """Record without UI; Ctrl+C to stop."""
        not_implemented("record")
