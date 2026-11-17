"""Following a transcript as it grows, and session-scoped cursors.

A `seq` cursor only means something inside one session. Readers that "follow the latest
session" (the panel's live view, `show -f`, MCP get_transcript) must notice when a newer
session starts, or they would skip its first lines (those with seq <= the old cursor).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from audio_notes.store.models import TranscriptReader

# ("session", session_id | None) when the followed session changes,
# ("segment", Segment) for each new line.
Event = tuple[str, object]


@dataclass
class Follower:
    """Polls a reader for new lines of one session, or of the latest one (`session_id` None).

    When following the latest session and a newer one appears, the rest of the old session is
    delivered first, then a "session" event, then the new session from its first line."""

    reader: TranscriptReader
    session_id: str | None = None
    cursor: int = 0
    current: str | None = field(init=False)

    def __post_init__(self) -> None:
        self.current = self.session_id if self.session_id is not None else self.reader.latest_session_id()

    def poll(self) -> list[Event]:
        events: list[Event] = []
        if self.session_id is None:
            latest = self.reader.latest_session_id()
            if latest != self.current:
                if self.current is not None:
                    events += self._new_lines()
                self.current, self.cursor = latest, 0
                events.append(("session", latest))
        events += self._new_lines()
        return events

    def _new_lines(self) -> list[Event]:
        if self.current is None:
            return []
        segs, self.cursor = self.reader.read_segments(self.current, self.cursor)
        return [("segment", s) for s in segs]


# -- session-scoped cursor tokens (MCP) ----------------------------------------------------


def format_cursor(session_id: str | None, seq: int) -> str:
    """"<session id>:<seq>", or just the seq when there is no session."""
    return f"{session_id}:{seq}" if session_id else str(seq)


def parse_cursor(token: str | int | None) -> tuple[str | None, int]:
    """Inverse of `format_cursor`. A bare number (older clients) means "in the latest session"."""
    if token is None:
        return None, 0
    text = str(token).strip()
    if not text:
        return None, 0
    session, sep, seq = text.rpartition(":")
    try:
        n = max(int(seq if sep else text), 0)
    except ValueError:
        raise ValueError(f"bad cursor {token!r}: expected '<session>:<seq>' as returned by get_transcript")
    return (session or None) if sep else None, n
