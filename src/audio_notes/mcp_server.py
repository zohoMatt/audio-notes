"""MCP stdio server exposing the transcript. Imports only store.reader / store.models
(never faster-whisper / PyAudio / pystray), so it starts fast."""

from __future__ import annotations

import time

from audio_notes.store.follow import format_cursor, parse_cursor
from audio_notes.store.models import stream_label
from audio_notes.store.reader import StoreReader, fmt_segment

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore[assignment]

MAX_SEARCH_RESULTS = 50

_INSTRUCTIONS = (
    "Live transcript of the user's meeting/audio. 'Me' = the user's microphone, "
    "'Them' = system audio (other participants). Each recording session has a short name, "
    "Stream001 being the oldest; the user may refer to one by it (e.g. 'Stream007'). Poll "
    "get_transcript with the returned cursor (pass it back unchanged) to get only new lines."
)


def _session_title(reader: StoreReader, session_id: str) -> str:
    name = reader.stream_name(session_id)
    return f"{name} ({session_id})" if name else session_id



def create_server(reader: StoreReader | None = None) -> _Server:
    reader = reader or StoreReader()
    server = _Server("Audio Notes", instructions=_INSTRUCTIONS)

    @server.tool()
    def get_transcript(
        since_cursor: str | int | None = None,
        last_n_minutes: float | None = None,
        session: str | None = None,
    ) -> str:
        """Get transcript lines of the latest session, or of the session named by `session`.

        since_cursor: pass the `cursor` value from the previous call, unchanged, to get only
        newer lines (omit to read from the start). It names the session it belongs to: if a new
        session has started since, you get the rest of the old one, then the new one from its
        first line.
        last_n_minutes: only lines from the last N minutes of the conversation.
        session: a stream name such as "Stream007" (or a session id from list_sessions) to read
        that session instead of the latest one.
        """
        try:
            cur_session, seq = parse_cursor(since_cursor)
        except ValueError as e:
            return str(e)
        if session is not None and str(session).strip():
            sid = reader.resolve_session_id(session)
            if sid is None:
                return f"No session {session!r}. Use list_sessions to see the stream names."
            if cur_session != sid:
                seq = 0  # the cursor belongs to another session
            all_segs, _ = reader.read_segments(sid, 0)
            segs = [s for s in all_segs if s.seq > seq]
            cursor = format_cursor(sid, segs[-1].seq if segs else seq)
            if last_n_minutes is not None and segs:
                horizon = all_segs[-1].t1 - last_n_minutes * 60
                segs = [s for s in segs if s.t1 >= horizon]
            head = f"({_session_title(reader, sid)})"
            if not segs:
                return f"{head}\n(no new transcript)\ncursor: {cursor}"
            return "\n".join([head] + [fmt_segment(s) for s in segs]) + f"\ncursor: {cursor}"
        latest = reader.latest_session_id()
        if latest is None:
            return f"(no new transcript)\ncursor: {format_cursor(None, 0)}"
        out: list[str] = []
        if cur_session is not None and cur_session != latest:
            old, _ = reader.read_segments(cur_session, seq)
            if old:
                out.append(f"(rest of session {_session_title(reader, cur_session)})")
                out += [fmt_segment(s) for s in old]
            out.append(f"(new session {_session_title(reader, latest)} started)")
            seq = 0
        all_segs, _ = reader.read_segments(latest, 0)
        segs = [s for s in all_segs if s.seq > seq]
        cursor = format_cursor(latest, segs[-1].seq if segs else seq)
        if last_n_minutes is not None and segs:
            horizon = all_segs[-1].t1 - last_n_minutes * 60
            segs = [s for s in segs if s.t1 >= horizon]
        out += [fmt_segment(s) for s in segs]
        if not segs and not out:
            return f"(no new transcript)\ncursor: {cursor}"
        return "\n".join(out) + f"\ncursor: {cursor}"

    @server.tool()
    def search_transcript(query: str, session: str | None = None) -> str:
        """Case-insensitive search. Returns matching lines grouped by session (stream name).

        session: a stream name such as "Stream007" (or a session id) to search only that
        session; omit to search all sessions.
        """
        if not query.strip():
            return "Empty query."
        if session is not None and str(session).strip():
            sid = reader.resolve_session_id(session)
            if sid is None:
                return f"No session {session!r}. Use list_sessions to see the stream names."
            sessions = [sid]
        else:
            sessions = [s.id for s in reversed(reader.list_sessions())]  # chronological
        hits = [(sid, seg) for sid in sessions for seg in reader.search(query, sid)]
        if not hits:
            return f"No matches for {query!r}."
        shown = hits[-MAX_SEARCH_RESULTS:]
        out = [f"{len(hits)} match(es)" + (f", showing last {len(shown)}" if len(shown) < len(hits) else "") + ":"]
        current = None
        for sid, seg in shown:
            if sid != current:
                current = sid
                out.append(f"-- {_session_title(reader, sid)}")
            out.append(fmt_segment(seg))
        return "\n".join(out)

    @server.tool()
    def list_sessions() -> str:
        """List recorded sessions, newest first, with their stream names (Stream001 = oldest)."""
        sessions = reader.list_sessions()
        if not sessions:
            return "No sessions."
        return "\n".join(
            f"{stream_label(s.stream)}  {s.id}  {s.segment_count} segments"
            + ("  [paused]" if s.is_paused else "  [recording]" if s.is_active else "")
            for s in sessions
        )

    @server.tool()
    def get_status() -> str:
        """Whether the recorder is running and how fresh the transcript is."""
        st = reader.read_status()
        if not st.alive:
            return "Recorder is not running."
        age = time.time() - (st.last_heartbeat or 0)
        recording = "paused" if st.paused else "yes" if st.recording else "no"
        session = _session_title(reader, st.session_id) if st.session_id else None
        return (
            f"Recorder running; recording={recording}; "
            f"session={session}; segments={st.segments}; heartbeat {age:.0f}s ago."
        )

    return server


def main() -> None:
    create_server().run(transport="stdio")
