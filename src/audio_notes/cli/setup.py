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

SERVER_NAME = "audio-notes"  # Claude Code `claude mcp add` name (letters, digits, - and _ only)
DESKTOP_SERVER_NAME = "Audio Notes"  # key in claude_desktop_config.json, shown in Claude Desktop
CONFIG_ENV = "AUDIO_NOTES_CLAUDE_CONFIG"  # overrides the Claude Desktop config path (tests)


def _store_claude_config_dir() -> Path | None:
    """Microsoft Store builds of Claude Desktop redirect %APPDATA% into their package folder
    (%LOCALAPPDATA%\\Packages\\Claude_*\\LocalCache\\Roaming\\Claude) and ignore the real %APPDATA%."""
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return None
    # Newer builds keep user data in %LOCALAPPDATA%\Claude-Data\claude_<package id>\.
    for d in sorted(Path(local, "Claude-Data").glob("claude_*")):
        if (d / "claude_desktop_config.json").is_file():
            return d
    for pkg in sorted(Path(local, "Packages").glob("Claude_*")):
        d = pkg / "LocalCache" / "Roaming" / "Claude"
        if d.is_dir():
            return d
    return None


def claude_desktop_config_path() -> Path:
    override = os.environ.get(CONFIG_ENV)
    if override:
        return Path(override)
    if sys.platform == "win32":
        store = _store_claude_config_dir()
        if store is not None:
            return store / "claude_desktop_config.json"
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return base / "Claude" / "claude_desktop_config.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


NOT_INSTALLED_EXIT = 3  # `setup claude --write` exit code when Claude Desktop is not installed
CLI_EXE_NAME = "audio-notes.exe"  # console build; the tray exe (windowed) has no `mcp` command


class ClaudeNotInstalled(Exception):
    """Claude Desktop's config directory does not exist, so Claude Desktop is not installed."""


MAC_CLAUDE_BUNDLE_ID = "com.anthropic.claudefordesktop"
# Claude Desktop's main executable, wherever Claude.app is installed. The Claude Code CLI runs as
# "claude" / "node", and the app's helpers live under Contents/Frameworks, so neither matches.
MAC_CLAUDE_EXE_SUFFIX = "/Claude.app/Contents/MacOS/Claude"


def _mac_running_by_bundle_id() -> bool:
    try:
        from AppKit import NSRunningApplication
    except Exception:  # pyobjc missing or broken: fall back to the process list
        return False
    try:
        return len(NSRunningApplication.runningApplicationsWithBundleIdentifier_(MAC_CLAUDE_BUNDLE_ID)) > 0
    except Exception:
        return False


def _mac_running_by_process_list() -> bool:
    # Not `pgrep -x Claude`: BSD pgrep never matches its own ancestors, and when Claude Code in
    # the desktop app runs us, Claude Desktop is one. Match the executable path in ps instead.
    # This also covers a process without a run loop, where NSRunningApplication can be stale.
    import subprocess

    try:
        out = subprocess.run(["ps", "-axo", "comm="], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return any(line.strip().endswith(MAC_CLAUDE_EXE_SUFFIX) for line in out.splitlines())


def claude_desktop_running() -> bool:
    import subprocess

    if sys.platform == "darwin":
        return _mac_running_by_bundle_id() or _mac_running_by_process_list()
    if sys.platform != "win32":
        return False
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq claude.exe", "/NH"],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "claude.exe" in out.lower()


def claude_desktop_installed(config_path: Path) -> bool:
    return config_path.parent.is_dir()


def server_command() -> tuple[str, list[str]]:
    """Absolute command + args that start the MCP server (Claude Desktop may lack PATH)."""
    if getattr(sys, "frozen", False):  # packaged exe
        me = Path(sys.executable).resolve()
        # The tray runs as audio-notes-tray.exe, which cannot serve MCP: point at its console sibling.
        cli = me.with_name(CLI_EXE_NAME)
        return str(cli if cli.exists() else me), ["mcp"]
    exe = shutil.which("audio-notes")
    if exe:
        return str(Path(exe).resolve()), ["mcp"]
    argv0 = Path(sys.argv[0]) if sys.argv and sys.argv[0] else None
    if argv0 and argv0.name.lower().startswith("audio-notes") and argv0.exists():
        return str(argv0.resolve()), ["mcp"]
    return str(Path(sys.executable).resolve()), ["-m", "audio_notes", "mcp"]


def _venv_root(command: Path) -> Path | None:
    for d in command.parents:
        if (d / "pyvenv.cfg").is_file():
            return d
    return None


def _is_hidden(p: Path) -> bool:
    import stat

    try:
        return bool(getattr(os.stat(p), "st_flags", 0) & stat.UF_HIDDEN)
    except OSError:
        return False


def hidden_venv_warning(command: str) -> str | None:
    """Why `command` may not start under Claude Desktop on macOS, or None.

    iCloud Drive ("Desktop & Documents") sets the hidden flag on dot-folders such as `.venv` a few
    seconds after they appear, and Python (3.12.14+, 3.13+) then skips their `.pth` files, so the
    editable install vanishes: `No module named 'audio_notes'`. `uv run` re-syncs the venv first,
    which hides the problem when testing from a terminal, but Claude Desktop starts the command
    directly."""
    if sys.platform != "darwin" or getattr(sys, "frozen", False):
        return None
    venv = _venv_root(Path(command))
    if venv is None:
        return None
    pth = list(venv.glob("lib/python*/site-packages/*.pth"))
    hidden = _is_hidden(venv) or any(_is_hidden(p) for p in pth)
    try:
        rel = venv.relative_to(Path.home()).parts
    except ValueError:
        rel = ()
    synced = bool(rel) and rel[0] in ("Documents", "Desktop") and any(p.startswith(".") for p in rel[1:])
    if not (hidden or synced):
        return None
    why = ("its .pth files are marked hidden, so Python skips them"
           if hidden else "iCloud Drive may mark it hidden, and Python then skips its .pth files")
    return (f"WARNING: {command} runs from the virtualenv {venv}; {why} and the MCP server fails with "
            "\"No module named 'audio_notes'\" when Claude starts it. Install it as a tool instead "
            "(`uv tool install .`), then run `audio-notes setup claude` from there.")


def build_entry() -> dict:
    command, args = server_command()
    return {"command": command, "args": args}


def _quote(s: str) -> str:
    return f'"{s}"' if " " in s else s


def claude_mcp_add_command() -> str:
    command, args = server_command()
    return " ".join(["claude", "mcp", "add", SERVER_NAME, "--", _quote(command), *map(_quote, args)])


def write_json_atomic(path: Path, data: dict) -> None:
    """Replace `path` with `data` in one step, keeping the file's permissions.

    Claude Desktop keeps its config owner-only (0600); a plain write + replace would leave it
    world-readable (umask 022). A new file gets 0600."""
    import stat

    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        mode = 0o600
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def merge_config(config_path: Path) -> Path | None:
    """Merge our entry into the config file. Returns the backup path (None if file was new).

    Never creates Claude's own config directory: raises ClaudeNotInstalled if it is missing."""
    if not claude_desktop_installed(config_path):
        raise ClaudeNotInstalled(f"Claude Desktop does not seem to be installed ({config_path.parent} not found)")
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
    servers.pop(SERVER_NAME, None)  # entry written by older versions under the command name
    servers[DESKTOP_SERVER_NAME] = build_entry()
    write_json_atomic(config_path, data)
    return backup


def register(app: typer.Typer) -> None:
    setup_app = typer.Typer(help="Configure integrations.", no_args_is_help=True)

    @setup_app.command("claude")
    def setup_claude(
        write: bool = typer.Option(False, "--write", help="Merge into the Claude Desktop config (asks first)."),
        yes: bool = typer.Option(False, "--yes", "-y", help="With --write: do not ask for confirmation."),
        config: Optional[Path] = typer.Option(None, "--config", help="Claude Desktop config path override."),
    ) -> None:
        """Print (or with --write, install) the Claude MCP configuration."""
        snippet = {"mcpServers": {DESKTOP_SERVER_NAME: build_entry()}}
        typer.echo("Claude Desktop (claude_desktop_config.json):")
        typer.echo(json.dumps(snippet, indent=2))
        typer.echo("")
        typer.echo("Claude Code:")
        typer.echo(claude_mcp_add_command())
        warning = hidden_venv_warning(snippet["mcpServers"][DESKTOP_SERVER_NAME]["command"])
        if warning:
            typer.echo("")
            typer.echo(warning, err=True)
        if not write:
            typer.echo("")
            typer.echo("Run with --write to merge the entry into the Claude Desktop config.")
            return
        path = config or claude_desktop_config_path()
        typer.echo("")
        if not claude_desktop_installed(path):
            typer.echo(f"Claude Desktop does not seem to be installed ({path.parent} not found); nothing written.", err=True)
            raise typer.Exit(NOT_INSTALLED_EXIT)
        if not yes and not typer.confirm(f"Merge the '{DESKTOP_SERVER_NAME}' entry into {path}? A backup is made first."):
            typer.echo("Aborted; nothing written.")
            raise typer.Exit(1)
        try:
            backup = merge_config(path)
        except ClaudeNotInstalled as e:
            typer.echo(str(e), err=True)
            raise typer.Exit(NOT_INSTALLED_EXIT)
        except (ValueError, OSError) as e:
            typer.echo(f"Could not update {path}: {e}", err=True)
            raise typer.Exit(1)
        if backup:
            typer.echo(f"Backup: {backup}")
        typer.echo(f"Updated {path}.")
        if claude_desktop_running():
            typer.echo(
                "WARNING: Claude Desktop is running and rewrites this file when it exits, which can "
                "erase the change. Quit it completely (also from the tray), run this command again, "
                "then start Claude Desktop.",
                err=True,
            )
        else:
            typer.echo("Start Claude Desktop to load it.")

    app.add_typer(setup_app, name="setup")
