"""`sessions`, `show [SESSION] -n N -f`, `status`. Read-only via store.reader."""

from __future__ import annotations

import time
from typing import Optional

import typer

from audio_notes.store.follow import Follower
from audio_notes.store.reader import StoreReader, fmt_segment


def register(app: typer.Typer) -> None:
    @app.command()
    def sessions() -> None:
        """List recorded sessions (newest first)."""
        items = StoreReader().list_sessions()
        if not items:
            typer.echo("No sessions.")
            return
        for s in items:
            typer.echo(f"{s.id}  {s.segment_count:>5} segments" + ("  [active]" if s.is_active else ""))

    @app.command()
    def show(
        session: Optional[str] = typer.Argument(None, help="Session id; default: latest."),
        n: int = typer.Option(20, "-n", help="Show the last N lines (0 = all)."),
        follow: bool = typer.Option(False, "-f", "--follow", help="Keep printing new lines."),
    ) -> None:
        """Show a transcript."""
        reader = StoreReader()
        if session and not any(s.id == session for s in reader.list_sessions()) and not follow:
            typer.echo(f"No such session: {session}", err=True)
            raise typer.Exit(1)
        follower = Follower(reader, session)  # session None: follow the latest, switching to newer ones
        segs = [v for kind, v in follower.poll() if kind == "segment"]
        if n > 0:
            segs = segs[-n:]
        for s in segs:
            typer.echo(fmt_segment(s))
        if not follow:
            return
        try:
            while True:
                time.sleep(0.5)
                for kind, value in follower.poll():
                    if kind == "session":
                        typer.echo(f"--- new session {value} ---")
                    else:
                        typer.echo(fmt_segment(value))
        except KeyboardInterrupt:
            pass

    @app.command()
    def status() -> None:
        """Show recorder status."""
        st = StoreReader().read_status()
        if not st.alive:
            typer.echo("Recorder is not running.")
            return
        age = time.time() - (st.last_heartbeat or 0)
        typer.echo(
            f"running  recording={'yes' if st.recording else 'no'}  session={st.session_id}  "
            f"segments={st.segments}  pid={st.pid}  heartbeat={age:.0f}s ago"
        )
