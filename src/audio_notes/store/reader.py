"""StoreReader: read-only access to sessions and status; safe while the writer appends."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from audio_notes import paths
from audio_notes.store.models import Segment, SessionInfo, Status

# Writer beats every ~2 s; allow a few missed beats (slow disk, antivirus) before "dead".
HEARTBEAT_STALE_AFTER_S = 8.0


def fmt_time(seconds: float) -> str:
    s = max(int(seconds), 0)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def fmt_segment(seg: Segment) -> str:
    who = "Me" if seg.speaker == "me" else "Them"
    return f"[{fmt_time(seg.t0)}] {who}: {seg.text}"


def _parse_lines(path: Path) -> list[Segment]:
    """All complete, valid segments of a file. A torn/partial last line is ignored."""
    try:
        data = path.read_bytes()
    except OSError:
        return []
    segments: list[Segment] = []
    for raw in data.split(b"\n"):
        if not raw.strip():
            continue
        try:
            segments.append(Segment.from_json_line(raw.decode("utf-8")))
        except (ValueError, TypeError, KeyError):
            continue  # torn tail (or a corrupt line): skip
    return segments


class StoreReader:
    def __init__(self, stale_after: float = HEARTBEAT_STALE_AFTER_S) -> None:
        self._stale_after = stale_after

    def _files(self) -> list[Path]:
        d = paths.sessions_dir()
        if not d.is_dir():
            return []
        return sorted(d.glob("*.jsonl"), key=lambda p: p.stem, reverse=True)

    def _resolve(self, session_id: str | None) -> Path | None:
        if session_id is None:
            files = self._files()
            return files[0] if files else None
        p = paths.sessions_dir() / f"{session_id}.jsonl"
        return p if p.is_file() else None

    def list_sessions(self) -> list[SessionInfo]:
        status = self.read_status()
        out = []
        for p in self._files():
            try:
                started = datetime.strptime(p.stem, "%Y-%m-%d_%H-%M-%S").isoformat()
            except ValueError:
                started = ""
            out.append(
                SessionInfo(
                    id=p.stem,
                    path=p,
                    started_at=started,
                    segment_count=len(_parse_lines(p)),
                    is_active=bool(status.recording and status.alive and status.session_id == p.stem),
                )
            )
        return out

    def read_segments(
        self,
        session_id: str | None = None,
        since_cursor: int = 0,
        limit: int | None = None,
    ) -> tuple[list[Segment], int]:
        p = self._resolve(session_id)
        if p is None:
            return [], since_cursor
        segs = [s for s in _parse_lines(p) if s.seq > since_cursor]
        if limit is not None:
            segs = segs[: max(limit, 0)]
        return segs, (segs[-1].seq if segs else since_cursor)

    def search(self, query: str, session_id: str | None = None) -> list[Segment]:
        q = query.casefold()
        if session_id is None:
            files = list(reversed(self._files()))  # chronological
        else:
            p = self._resolve(session_id)
            files = [p] if p else []
        return [s for f in files for s in _parse_lines(f) if q in s.text.casefold()]

    def read_status(self) -> Status:
        try:
            d = json.loads(paths.status_path().read_text(encoding="utf-8"))
            hb = d.get("last_heartbeat")
            hb = float(hb) if hb is not None else None
            alive = hb is not None and (time.time() - hb) <= self._stale_after
            return Status(
                recording=bool(d.get("recording", False)) and alive,
                session_id=d.get("session_id"),
                segments=int(d.get("segments", 0)),
                alive=alive,
                last_heartbeat=hb,
                pid=d.get("pid"),
            )
        except (OSError, ValueError, TypeError):
            return Status(False, None, 0, False, None, None)
