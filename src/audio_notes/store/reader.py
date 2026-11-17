"""StoreReader: read-only access to sessions and status; safe while the writer appends.

Session files are append-only, so the reader remembers how far it has parsed each file and
only reads the bytes added since. The live panel polls several times a second; this keeps
each poll proportional to the new lines rather than to the whole history.
"""

from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from pathlib import Path

from audio_notes import paths
from audio_notes.store.models import Segment, SessionInfo, Status

# Writer beats every ~2 s; allow a few missed beats (slow disk, antivirus) before "dead".
HEARTBEAT_STALE_AFTER_S = 8.0
_SEGMENT_CACHE_FILES = 8  # sessions whose parsed lines are kept in memory (most recently used)


def fmt_time(seconds: float) -> str:
    s = max(int(seconds), 0)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def fmt_segment(seg: Segment) -> str:
    who = "Me" if seg.speaker == "me" else "Them"
    return f"[{fmt_time(seg.t0)}] {who}: {seg.text}"


def _parse_block(data: bytes) -> list[Segment]:
    segments: list[Segment] = []
    for raw in data.split(b"\n"):
        if not raw.strip():
            continue
        try:
            segments.append(Segment.from_json_line(raw.decode("utf-8")))
        except (ValueError, TypeError, KeyError):
            continue  # a corrupt line: skip
    return segments


def _read_from(path: Path, offset: int) -> tuple[int, list[Segment], bool] | None:
    """Parse the complete lines after byte `offset`.

    Returns (new offset, segments, restarted). A torn last line (no newline yet) is left for
    the next call. `restarted` is True when the file shrank (replaced), so parsing began again
    at 0 and earlier results must be dropped. None when the file cannot be read."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            restarted = size < offset
            if restarted:
                offset = 0
            if size == offset:
                return offset, [], restarted
            f.seek(offset)
            data = f.read(size - offset)
    except OSError:
        return None
    end = data.rfind(b"\n")
    if end < 0:
        return offset, [], restarted
    return offset + end + 1, _parse_block(data[:end]), restarted


class StoreReader:
    """Implements `TranscriptReader`. Thread-safe; one instance can serve many requests."""

    def __init__(self, stale_after: float = HEARTBEAT_STALE_AFTER_S) -> None:
        self._stale_after = stale_after
        self._lock = threading.Lock()
        self._counts: dict[Path, tuple[int, int]] = {}  # path -> (offset, segment count)
        self._segments: OrderedDict[Path, tuple[int, list[Segment]]] = OrderedDict()

    # -- files -------------------------------------------------------------

    def _files(self) -> list[Path]:
        d = paths.sessions_dir()
        if not d.is_dir():
            return []
        return sorted(d.glob("*.jsonl"), key=lambda p: paths.session_sort_key(p.stem), reverse=True)

    def latest_session_id(self) -> str | None:
        d = paths.sessions_dir()
        if not d.is_dir():
            return None
        stems = [p.stem for p in d.glob("*.jsonl")]
        return max(stems, key=paths.session_sort_key) if stems else None

    def _resolve(self, session_id: str | None) -> Path | None:
        if session_id is None:
            session_id = self.latest_session_id()
            if session_id is None:
                return None
        if not paths.is_valid_session_id(session_id):
            return None
        p = paths.sessions_dir() / f"{session_id}.jsonl"
        return p if p.is_file() else None

    # -- cached parsing ----------------------------------------------------

    def _all_segments(self, path: Path) -> list[Segment]:
        """Every segment of `path` so far (internal list: callers must not mutate it)."""
        with self._lock:
            offset, segs = self._segments.pop(path, (0, []))
            r = _read_from(path, offset)
            if r is None:
                return []
            offset, new, restarted = r
            if restarted:
                segs = []
            segs.extend(new)
            self._segments[path] = (offset, segs)
            while len(self._segments) > _SEGMENT_CACHE_FILES:
                self._segments.popitem(last=False)
            return segs

    def _count(self, path: Path) -> int:
        with self._lock:
            offset, n = self._counts.get(path, (0, 0))
            r = _read_from(path, offset)
            if r is None:
                return n
            offset, new, restarted = r
            n = (0 if restarted else n) + len(new)
            self._counts[path] = (offset, n)
            return n

    # -- TranscriptReader --------------------------------------------------

    def list_sessions(self) -> list[SessionInfo]:
        status = self.read_status()
        out = []
        for p in self._files():
            started = paths.session_started_at(p.stem)
            out.append(
                SessionInfo(
                    id=p.stem,
                    path=p,
                    started_at=started.isoformat() if started else "",
                    segment_count=self._count(p),
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
        segs = [s for s in self._all_segments(p) if s.seq > since_cursor]
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
        out: list[Segment] = []
        for f in files:  # one-off scan: deliberately not cached
            r = _read_from(f, 0)
            if r is not None:
                out += [s for s in r[1] if q in s.text.casefold()]
        return out

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
