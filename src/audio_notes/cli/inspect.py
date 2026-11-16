"""STUB owned by track C: `sessions`, `show [SESSION] -n N -f`, `status`. Read-only via store.reader."""

from __future__ import annotations

import typer

from ._todo import not_implemented


def register(app: typer.Typer) -> None:
    @app.command()
    def sessions() -> None:
        """List recorded sessions."""
        not_implemented("sessions")

    @app.command()
    def show() -> None:
        """Show a transcript."""
        not_implemented("show")

    @app.command()
    def status() -> None:
        """Show recorder status."""
        not_implemented("status")
