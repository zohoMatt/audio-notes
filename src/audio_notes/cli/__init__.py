"""CLI entry point. Each command module exposes `register(app)` and owns its own commands,
so parallel work never edits this file. Heavy imports stay inside command bodies."""

from __future__ import annotations

import typer

from audio_notes import __version__

app = typer.Typer(
    name="audio-notes",
    help="Capture system audio, transcribe locally, expose the transcript to Claude via MCP.",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True, help="Show version and exit."
    ),
) -> None:
    pass


from . import clean, devices, inspect, run, setup  # noqa: E402

for _module in (clean, devices, inspect, run, setup):
    _module.register(app)
