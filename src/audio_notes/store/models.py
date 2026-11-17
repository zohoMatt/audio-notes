"""Shared data model and store contracts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from audio_notes.capture.base import Speaker


@dataclass(frozen=True)
class Segment:
    seq: int  # 1-based, increasing within a session; doubles as the read cursor
    t0: float  # seconds since session start
    t1: float
    speaker: Speaker
    text: str

    def to_json_line(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json_line(cls, line: str) -> "Segment":
        return cls(**json.loads(line))


def stream_label(number: int) -> str:
    """Short name of the n-th session (1 = oldest), e.g. "Stream007"; easy to say in a chat."""
    return f"Stream{number:03d}"


@dataclass(frozen=True)
class SessionInfo:
    id: str  # JSONL file stem, e.g. "2026-11-16_14-30-00"
    path: Path
    started_at: str  # ISO 8601
    segment_count: int
    is_active: bool  # the recorder has this session open (recording or paused)
    stream: int = 0  # 1-based position in chronological order: see `stream_label`
    is_paused: bool = False  # open, but capture is paused


@dataclass(frozen=True)
class Status:
    recording: bool
    session_id: str | None
    segments: int
    alive: bool  # writer heartbeat is fresh (computed by the reader)
    last_heartbeat: float | None  # epoch seconds
    pid: int | None
    paused: bool = False  # the open session's capture is paused (`recording` stays True)


class TranscriptSink(Protocol):
    """What the processing layer writes to. Implemented by `store.writer.SessionWriter`."""

    def append(self, t0: float, t1: float, speaker: Speaker, text: str) -> Segment: ...

    def close(self) -> None: ...


class TranscriptReader(Protocol):
    """What CLI / MCP / Web read from. Implemented by `store.reader.StoreReader`."""

    def list_sessions(self) -> list[SessionInfo]:
        """Newest first."""

    def latest_session_id(self) -> str | None:
        """Id of the newest session (cheap: no file is parsed), or None when there is none."""

    def read_segments(
        self,
        session_id: str | None = None,  # None = latest session
        since_cursor: int = 0,
        limit: int | None = None,
    ) -> tuple[list[Segment], int]:
        """Segments with seq > since_cursor, plus the new cursor (last seq returned,
        or since_cursor if nothing new). A torn final line must be ignored."""

    def search(self, query: str, session_id: str | None = None) -> list[Segment]:
        """Case-insensitive substring search; session_id None = all sessions."""

    def read_status(self) -> Status: ...
