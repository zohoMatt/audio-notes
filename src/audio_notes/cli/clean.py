"""`audio-notes clean`: undo everything an install / "Connect to Claude" left behind.

Meant for repeated local testing. Removes, after one confirmation:
- the Audio Notes entry from every Claude Desktop config found (Store and classic installs),
- the `claude_desktop_config.json.bak-*` backups our connect step made,
- Claude Code registrations (user scope, every project's local scope, project `.mcp.json` files),
- with --uninstall: the installed app, by running its Inno Setup uninstaller silently (Windows;
  on macOS the app is a uv tool: `uv tool uninstall audio-notes`),
- with --purge-data: the transcripts folders as well (and the log folder on macOS).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import typer

from . import setup as setup_cli

OUR_NAMES = (setup_cli.SERVER_NAME, setup_cli.DESKTOP_SERVER_NAME)
APP_ID = "{6B0F7A52-3B1D-4C55-9A4E-0A0D10A07E51}"  # installer/audio-notes.iss AppId
CLAUDE_CODE_CONFIG_ENV = "AUDIO_NOTES_CLAUDE_CODE_CONFIG"  # overrides ~/.claude.json (tests)
# Backups written by setup.merge_config and scripts/connect_claude_desktop.ps1 (not Claude's own *.bak).
_OUR_BACKUP = re.compile(r"^claude_desktop_config\.json\.bak-(\d{8}-\d{6}|audio-notes)$")


# ---- discovery --------------------------------------------------------------
def desktop_config_paths() -> list[Path]:
    """Every Claude Desktop config location that exists on this machine (not just the active one)."""
    override = os.environ.get(setup_cli.CONFIG_ENV)
    if override:
        return [Path(override)]
    dirs: list[Path] = []
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs += sorted(Path(local, "Claude-Data").glob("claude_*"))
            dirs += [p / "LocalCache" / "Roaming" / "Claude" for p in sorted(Path(local, "Packages").glob("Claude_*"))]
        dirs.append(Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "Claude")
    else:
        dirs.append(setup_cli.claude_desktop_config_path().parent)
    return [d / "claude_desktop_config.json" for d in dirs if d.is_dir()]


def claude_code_config_path() -> Path:
    override = os.environ.get(CLAUDE_CODE_CONFIG_ENV)
    return Path(override) if override else Path.home() / ".claude.json"


@dataclass
class Plan:
    desktop: list[tuple[Path, list[str]]] = field(default_factory=list)  # config, our keys in it
    backups: list[Path] = field(default_factory=list)
    code_user: list[str] = field(default_factory=list)
    code_local: list[tuple[str, list[str]]] = field(default_factory=list)  # project path, names
    mcp_json: list[tuple[Path, list[str]]] = field(default_factory=list)
    uninstaller: Optional[Path] = None
    data_dirs: list[Path] = field(default_factory=list)

    def empty(self) -> bool:
        return not (self.desktop or self.backups or self.code_user or self.code_local
                    or self.mcp_json or self.uninstaller or self.data_dirs)


def _read_json(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw) if raw.strip() else {}
    return data if isinstance(data, dict) else {}


def _ours(servers) -> list[str]:
    return [n for n in OUR_NAMES if isinstance(servers, dict) and n in servers]


def find_uninstaller() -> Path | None:
    if sys.platform != "win32":
        return None
    import winreg

    sub = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}_is1"
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(root, sub, 0, winreg.KEY_READ | view) as k:
                    cmd, _ = winreg.QueryValueEx(k, "UninstallString")
            except OSError:
                continue
            exe = Path(cmd.strip().strip('"'))
            if exe.is_file():
                return exe
    return None


def build_plan(*, keep_backups: bool, uninstall: bool, purge_data: bool,
               uninstaller_finder: Callable[[], Path | None] | None = None) -> Plan:
    plan = Plan()
    for cfg in desktop_config_paths():
        if cfg.is_file():
            try:
                names = _ours(_read_json(cfg).get("mcpServers"))
            except (ValueError, OSError):
                names = []
            if names:
                plan.desktop.append((cfg, names))
        if not keep_backups:
            plan.backups += sorted(p for p in cfg.parent.glob("claude_desktop_config.json.bak-*")
                                   if _OUR_BACKUP.match(p.name))

    code = claude_code_config_path()
    if code.is_file():
        try:
            data = _read_json(code)
        except (ValueError, OSError):
            data = {}
        plan.code_user = _ours(data.get("mcpServers"))
        projects = data.get("projects") if isinstance(data.get("projects"), dict) else {}
        for proj, cfg in projects.items():
            names = _ours(cfg.get("mcpServers")) if isinstance(cfg, dict) else []
            if names:
                plan.code_local.append((proj, names))
            mcp_json = Path(proj) / ".mcp.json"
            if mcp_json.is_file():
                try:
                    names = _ours(_read_json(mcp_json).get("mcpServers"))
                except (ValueError, OSError):
                    names = []
                if names:
                    plan.mcp_json.append((mcp_json, names))

    if uninstall:
        plan.uninstaller = (uninstaller_finder or find_uninstaller)()
    if purge_data:
        from audio_notes import paths

        candidates = [paths.data_dir()]
        if sys.platform == "darwin":
            candidates.append(paths.log_dir())  # ~/Library/Logs/Audio Notes
        if plan.uninstaller is not None:
            candidates.append(plan.uninstaller.parent / "data")
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(Path(appdata) / "audio-notes")
        for d in candidates:
            if d.is_dir() and d not in plan.data_dirs:
                plan.data_dirs.append(d)
    return plan


def _is_log_dir(d: Path) -> bool:
    from audio_notes import paths

    return sys.platform == "darwin" and d == paths.log_dir() and d != paths.data_dir()


# ---- actions ----------------------------------------------------------------
def _write_json(path: Path, data: dict) -> None:
    setup_cli.write_json_atomic(path, data)


def remove_servers(path: Path, names: list[str], *, project: str | None = None) -> None:
    """Drop `names` from mcpServers (of `projects[project]` when given), re-reading the file first."""
    data = _read_json(path)
    holder = data.get("projects", {}).get(project, {}) if project is not None else data
    servers = holder.get("mcpServers")
    if isinstance(servers, dict):
        for n in names:
            servers.pop(n, None)
    _write_json(path, data)


def _claude_cli() -> str | None:
    return shutil.which("claude")


def remove_claude_code(scope: str, name: str, cwd: str | None, cfg: Path, project: str | None) -> str:
    """Prefer `claude mcp remove` (it owns ~/.claude.json); fall back to editing the file."""
    cli = _claude_cli()
    if cli and not os.environ.get(CLAUDE_CODE_CONFIG_ENV) and (cwd is None or Path(cwd).is_dir()):
        r = subprocess.run([cli, "mcp", "remove", "-s", scope, name], cwd=cwd,
                           capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            return "claude mcp remove"
    remove_servers(cfg, [name], project=project)
    return "edited file"


def register(app: typer.Typer) -> None:
    @app.command("clean")
    def clean(
        uninstall: bool = typer.Option(False, "--uninstall", help="Also run the installed app's uninstaller (silent)."),
        purge_data: bool = typer.Option(False, "--purge-data", help="Also delete the transcripts folders."),
        keep_backups: bool = typer.Option(False, "--keep-backups", help="Keep the claude_desktop_config.json.bak-* files we made."),
        dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Only show what would be removed."),
        yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask for confirmation."),
    ) -> None:
        """Remove Audio Notes from Claude Desktop / Claude Code (and optionally uninstall it)."""
        plan = build_plan(keep_backups=keep_backups, uninstall=uninstall, purge_data=purge_data)
        if uninstall and plan.uninstaller is None:
            if sys.platform == "darwin":
                typer.echo("On macOS Audio Notes is a uv tool; remove it with: uv tool uninstall audio-notes")
            else:
                typer.echo("No installed Audio Notes found (no uninstaller in the registry).")
        if plan.empty():
            typer.echo("Nothing to clean.")
            return

        typer.echo("Will remove:")
        for cfg, names in plan.desktop:
            typer.echo(f"  Claude Desktop  {', '.join(names)}  in {cfg}")
        for b in plan.backups:
            typer.echo(f"  backup file     {b}")
        for n in plan.code_user:
            typer.echo(f"  Claude Code     {n}  (user scope)")
        for proj, names in plan.code_local:
            typer.echo(f"  Claude Code     {', '.join(names)}  (local scope, {proj})")
        for p, names in plan.mcp_json:
            typer.echo(f"  .mcp.json       {', '.join(names)}  in {p}")
        if plan.uninstaller:
            typer.echo(f"  installed app   via {plan.uninstaller}")
        for d in plan.data_dirs:
            label = "logs" if _is_log_dir(d) else "transcripts"
            typer.echo(f"  {label:<15} {d}  (deleted permanently)")
        if dry_run:
            return
        if not yes and not typer.confirm("Proceed?"):
            typer.echo("Aborted; nothing changed.")
            raise typer.Exit(1)

        failures = 0

        def attempt(label: str, fn: Callable[[], object]) -> None:
            nonlocal failures
            try:
                how = fn()
                typer.echo(f"OK    {label}" + (f" ({how})" if isinstance(how, str) else ""))
            except Exception as e:  # keep going: clean as much as possible
                failures += 1
                typer.echo(f"FAIL  {label}: {e}", err=True)

        if plan.desktop and setup_cli.claude_desktop_running():
            failures += 1
            where = "Cmd+Q" if sys.platform == "darwin" else "also from the tray"
            typer.echo("SKIP  Claude Desktop configs: Claude Desktop is running and rewrites its config when it "
                       f"exits. Quit it completely ({where}) and run this again.", err=True)
        else:
            for cfg, names in plan.desktop:
                attempt(f"Claude Desktop {cfg}", lambda cfg=cfg, names=names: remove_servers(cfg, names))
        for b in plan.backups:
            attempt(f"delete {b.name}", b.unlink)

        code = claude_code_config_path()
        for n in plan.code_user:
            attempt(f"Claude Code {n} (user)", lambda n=n: remove_claude_code("user", n, None, code, None))
        for proj, names in plan.code_local:
            for n in names:
                attempt(f"Claude Code {n} ({proj})",
                        lambda n=n, proj=proj: remove_claude_code("local", n, proj, code, proj))
        for p, names in plan.mcp_json:
            attempt(f"{p}", lambda p=p, names=names: remove_servers(p, names))

        if plan.uninstaller:
            me = Path(sys.executable).resolve()
            if getattr(sys, "frozen", False) and me.parent == plan.uninstaller.parent:
                failures += 1
                typer.echo("SKIP  uninstall: this command is running from the installed app itself. "
                           "Use Windows Settings > Apps, or run it from the source tree.", err=True)
            else:
                def run_uninstaller() -> None:
                    r = subprocess.run([str(plan.uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                                       timeout=300)
                    if r.returncode != 0:
                        raise RuntimeError(f"uninstaller exited with {r.returncode}")
                attempt("uninstall Audio Notes", run_uninstaller)
        for d in plan.data_dirs:
            attempt(f"delete {d}", lambda d=d: shutil.rmtree(d))

        if failures:
            raise typer.Exit(1)
        if plan.desktop or plan.code_user or plan.code_local or plan.mcp_json:
            typer.echo("Restart Claude Desktop / Claude Code sessions to drop the server.")
