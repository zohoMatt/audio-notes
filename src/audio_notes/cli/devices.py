"""`audio-notes devices`: list loopback and microphone devices."""

from __future__ import annotations

import sys

import typer


def register(app: typer.Typer) -> None:
    @app.command()
    def devices() -> None:
        """List audio devices (WASAPI loopback and microphones)."""
        if sys.platform != "win32":
            typer.echo("audio-notes devices is only supported on Windows (WASAPI).", err=True)
            raise typer.Exit(1)
        from audio_notes.capture.win_wasapi import list_devices

        try:
            found = list_devices()
        except Exception as e:  # noqa: BLE001
            typer.echo(f"Could not enumerate audio devices: {e}", err=True)
            raise typer.Exit(1)
        for title, key in (("Loopback (speaker -> 'them')", "loopback"), ("Microphone ('me')", "microphone")):
            typer.echo(f"{title}:")
            if not found[key]:
                typer.echo("  (none)")
            for d in found[key]:
                mark = "*" if d["default"] else " "
                typer.echo(f" {mark} [{d['index']}] {d['name']}  ({d['sample_rate']} Hz, {d['channels']} ch)")
        typer.echo("(* = default)")
