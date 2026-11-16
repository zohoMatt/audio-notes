"""STUB owned by track C: `audio-notes setup claude [--write]`."""

from __future__ import annotations

import typer

from ._todo import not_implemented


def register(app: typer.Typer) -> None:
    setup_app = typer.Typer(help="Configure integrations.", no_args_is_help=True)

    @setup_app.command("claude")
    def setup_claude() -> None:
        """Print (or with --write, install) the Claude MCP configuration."""
        not_implemented("setup claude")

    app.add_typer(setup_app, name="setup")
