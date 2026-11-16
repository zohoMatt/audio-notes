"""`audio-notes setup claude [--write]`: print / install the Claude MCP configuration."""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer

SERVER_NAME = "audio-notes"
CONFIG_ENV = "AUDIO_NOTES_CLAUDE_CONFIG"  # overrides the Claude Desktop config path (tests)


def claude_desktop_config_path() -> Path:
    override = os.environ.get(CONFIG_ENV)
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return base / "Claude" / "claude_desktop_config.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def server_command() -> tuple[str, list[str]]:
    """Absolute command + args that start the MCP server (Claude Desktop may lack PATH)."""
    if getattr(sys, "frozen", False):  # packaged exe
        return str(Path(sys.executable).resolve()), ["mcp"]
    exe = shutil.which("audio-notes")
    if exe:
        return str(Path(exe).resolve()), ["mcp"]
    argv0 = Path(sys.argv[0]) if sys.argv and sys.argv[0] else None
    if argv0 and argv0.name.lower().startswith("audio-notes") and argv0.exists():
        return str(argv0.resolve()), ["mcp"]
    return str(Path(sys.executable).resolve()), ["-m", "audio_notes", "mcp"]


def build_entry() -> dict:
    command, args = server_command()
    return {"command": command, "args": args}


def _quote(s: str) -> str:
    return f'"{s}"' if " " in s else s


def claude_mcp_add_command() -> str:
    command, args = server_command()
    return " ".join(["claude", "mcp", "add", SERVER_NAME, "--", _quote(command), *map(_quote, args)])


def merge_config(config_path: Path) -> Path | None:
    """Merge our entry into the config file. Returns the backup path (None if file was new)."""
    data: dict = {}
    backup: Path | None = None
    if config_path.exists():
        raw = config_path.read_text(encoding="utf-8")
        data = json.loads(raw) if raw.strip() else {}
        if not isinstance(data, dict):
            raise ValueError("config root is not a JSON object")
        backup = config_path.with_name(
            f"{config_path.name}.bak-{datetime.now():%Y%m%d-%H%M%S}"
        )
        shutil.copy2(config_path, backup)
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError("'mcpServers' is not a JSON object")
    servers[SERVER_NAME] = build_entry()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = config_path.with_name(config_path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, config_path)
    return backup


def register(app: typer.Typer) -> None:
    setup_app = typer.Typer(help="Configure integrations.", no_args_is_help=True)

    @setup_app.command("claude")
    def setup_claude(
        write: bool = typer.Option(False, "--write", help="Merge into the Claude Desktop config (asks first)."),
        config: Optional[Path] = typer.Option(None, "--config", help="Claude Desktop config path override."),
    ) -> None:
        """Print (or with --write, install) the Claude MCP configuration."""
        snippet = {"mcpServers": {SERVER_NAME: build_entry()}}
        typer.echo("Claude Desktop (claude_desktop_config.json):")
        typer.echo(json.dumps(snippet, indent=2))
        typer.echo("")
        typer.echo("Claude Code:")
        typer.echo(claude_mcp_add_command())
        if not write:
            typer.echo("")
            typer.echo("Run with --write to merge the entry into the Claude Desktop config.")
            return
        path = config or claude_desktop_config_path()
        typer.echo("")
        if not typer.confirm(f"Merge the '{SERVER_NAME}' entry into {path}? A backup is made first."):
            typer.echo("Aborted; nothing written.")
            raise typer.Exit(1)
        try:
            backup = merge_config(path)
        except (ValueError, OSError) as e:
            typer.echo(f"Could not update {path}: {e}", err=True)
            raise typer.Exit(1)
        if backup:
            typer.echo(f"Backup: {backup}")
        typer.echo(f"Updated {path}. Restart Claude Desktop to load it.")

    app.add_typer(setup_app, name="setup")
