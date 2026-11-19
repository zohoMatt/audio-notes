"""`audio-notes devices`: list the audio devices capture would use."""

from __future__ import annotations

import sys

import typer


def _windows() -> None:
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


def _macos() -> None:
    from audio_notes.capture import mac_tap

    try:
        found = mac_tap.list_devices()
    except Exception as e:  # noqa: BLE001
        typer.echo(f"Could not enumerate audio devices: {e}", err=True)
        raise typer.Exit(1)
    for title, key in (
        ("Output (system audio is tapped from the default one -> 'them')", "output"),
        ("Microphone (the default one -> 'me')", "input"),
    ):
        typer.echo(f"{title}:")
        if not found[key]:
            typer.echo("  (none)")
        for d in found[key]:
            mark = "*" if d["default"] else " "
            typer.echo(f" {mark} {d['name']}  ({d['sample_rate']} Hz, {d['channels']} ch)")
    typer.echo("(* = default)")
    try:
        perms = mac_tap.permissions()
    except Exception as e:  # noqa: BLE001
        typer.echo(f"Permissions: unknown ({e})")
        return
    typer.echo(f"Permissions: microphone {perms.microphone}, system audio recording {perms.system_audio}"
               + (f" (granted to: {perms.responsible})" if perms.responsible else ""))


def register(app: typer.Typer) -> None:
    @app.command()
    def devices() -> None:
        """List audio devices (Windows: WASAPI loopback and microphones; macOS: outputs and inputs)."""
        if sys.platform == "win32":
            _windows()
        elif sys.platform == "darwin":
            _macos()
        else:
            typer.echo("audio-notes devices is only supported on Windows and macOS.", err=True)
            raise typer.Exit(1)
