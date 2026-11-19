"""`sessions`, `show [SESSION] -n N -f`, `status`. Read-only via store.reader."""

from __future__ import annotations

import time
from typing import Optional

import typer

from audio_notes.store.follow import Follower
from audio_notes.store.models import stream_label
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
            state = "  [paused]" if s.is_paused else "  [recording]" if s.is_active else ""
            typer.echo(f"{stream_label(s.stream)}  {s.id}  {s.segment_count:>5} segments{state}")

    @app.command()
    def show(
        session: Optional[str] = typer.Argument(None, help="Stream name (Stream007) or session id; default: latest."),
        n: int = typer.Option(20, "-n", help="Show the last N lines (0 = all)."),
        follow: bool = typer.Option(False, "-f", "--follow", help="Keep printing new lines."),
    ) -> None:
        """Show a transcript."""
        reader = StoreReader()
        if session:
            resolved = reader.resolve_session_id(session)
            if resolved is None and not follow:
                typer.echo(f"No such session: {session}", err=True)
                raise typer.Exit(1)
            session = resolved or session
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
                        name = reader.stream_name(value)
                        typer.echo(f"--- new session {f'{name} ({value})' if name else value} ---")
                    else:
                        typer.echo(fmt_segment(value))
        except KeyboardInterrupt:
            pass

    @app.command()
    def status() -> None:
        """Show recorder status."""
        reader = StoreReader()
        st = reader.read_status()
        if not st.alive:
            typer.echo("Recorder is not running.")
            return
        age = time.time() - (st.last_heartbeat or 0)
        name = reader.stream_name(st.session_id)
        session = f"{name} ({st.session_id})" if name else st.session_id
        typer.echo(
            f"running  recording={'paused' if st.paused else 'yes' if st.recording else 'no'}  session={session}  "
            f"segments={st.segments}  pid={st.pid}  heartbeat={age:.0f}s ago"
        )
