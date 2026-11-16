"""MCP stdio server exposing the transcript. Imports only store.reader / store.models
(never faster-whisper / PyAudio / pystray), so it starts fast."""

from __future__ import annotations

import time

from audio_notes.store.reader import StoreReader, fmt_segment

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore[assignment]

MAX_SEARCH_RESULTS = 50

_INSTRUCTIONS = (
    "Live transcript of the user's meeting/audio. 'Me' = the user's microphone, "
    "'Them' = system audio (other participants). Poll get_transcript with the returned "
    "cursor to get only new lines."
)


def create_server(reader: StoreReader | None = None) -> _Server:
    reader = reader or StoreReader()
    server = _Server("audio-notes", instructions=_INSTRUCTIONS)

    @server.tool()
    def get_transcript(since_cursor: int = 0, last_n_minutes: float | None = None) -> str:
        """Get transcript lines of the latest session.

        since_cursor: return only lines after this cursor (use the cursor from the previous
        call to read incrementally; 0 = from the start).
        last_n_minutes: only lines from the last N minutes of the conversation.
        """
        segs, cursor = reader.read_segments(None, since_cursor)
        if last_n_minutes is not None and segs:
            all_segs, _ = reader.read_segments(None, 0)
            horizon = all_segs[-1].t1 - last_n_minutes * 60
            segs = [s for s in segs if s.t1 >= horizon]
        if not segs:
            return f"(no new transcript)\ncursor: {cursor}"
        return "\n".join(fmt_segment(s) for s in segs) + f"\ncursor: {cursor}"

    @server.tool()
    def search_transcript(query: str) -> str:
        """Case-insensitive search across all sessions. Returns matching lines."""
        if not query.strip():
            return "Empty query."
        hits = reader.search(query)
        if not hits:
            return f"No matches for {query!r}."
        shown = hits[-MAX_SEARCH_RESULTS:]
        head = f"{len(hits)} match(es)" + (
            f", showing last {len(shown)}" if len(shown) < len(hits) else ""
        )
        return head + ":\n" + "\n".join(fmt_segment(s) for s in shown)

    @server.tool()
    def list_sessions() -> str:
        """List recorded sessions, newest first."""
        sessions = reader.list_sessions()
        if not sessions:
            return "No sessions."
        return "\n".join(
            f"{s.id}  {s.segment_count} segments" + ("  [active]" if s.is_active else "")
            for s in sessions
        )

    @server.tool()
    def get_status() -> str:
        """Whether the recorder is running and how fresh the transcript is."""
        st = reader.read_status()
        if not st.alive:
            return "Recorder is not running."
        age = time.time() - (st.last_heartbeat or 0)
        return (
            f"Recorder running; recording={'yes' if st.recording else 'no'}; "
            f"session={st.session_id}; segments={st.segments}; heartbeat {age:.0f}s ago."
        )

    return server


def main() -> None:
    create_server().run(transport="stdio")
