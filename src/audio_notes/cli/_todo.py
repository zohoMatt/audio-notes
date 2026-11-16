from __future__ import annotations

from typing import NoReturn

import typer


def not_implemented(name: str) -> NoReturn:
    typer.echo(f"audio-notes {name}: not implemented yet", err=True)
    raise typer.Exit(1)
