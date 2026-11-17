"""Local web panel (Starlette) and the background server that hosts it.

Security (REQUIREMENTS F31): loopback bind only, Host header allow-list, no CORS,
a random per-run token on every route, and `Cache-Control: no-store` on everything.
Transcript data comes only through a `TranscriptReader`; this module must not import the
capture, asr or processing layers. The one write path, start/stop recording, goes through an
optional duck-typed controller (the same `RecorderController` the tray uses) and is reported
as unavailable when the panel runs without one.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import secrets
import threading
import time
from dataclasses import asdict
from importlib import resources
from typing import AsyncIterator, Protocol
from urllib.parse import parse_qs

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from audio_notes.store.models import TranscriptReader

TOKEN_HEADER = "x-audio-notes-token"
ALLOWED_HOSTNAMES = ("127.0.0.1", "localhost")
SSE_POLL_INTERVAL_S = 0.4
SSE_KEEPALIVE_S = 15.0

_STATIC_TYPES = {"app.js": "text/javascript; charset=utf-8", "style.css": "text/css; charset=utf-8"}


class RecordingControl(Protocol):
    """The subset of `tray.controller.RecorderController` the panel needs."""

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def is_recording(self) -> bool: ...
    def last_error(self) -> str | None: ...
    def is_downloading_model(self) -> bool: ...


NO_CONTROLLER = "This panel is not attached to a recorder (start it with `audio-notes tray`)."


def new_token() -> str:
    return secrets.token_urlsafe(24)


def _static_text(name: str) -> str:
    # importlib.resources works from a source tree, an installed wheel and a PyInstaller bundle
    # (the latter needs the package data collected, see the hand-over notes).
    return (resources.files("audio_notes.web") / "static" / name).read_text(encoding="utf-8")


class _GuardMiddleware:
    """Host check, token check and no-store headers, for every HTTP request."""

    def __init__(self, app: ASGIApp, token: str, port: int | None) -> None:
        self.app = app
        self.token = token.encode()
        self.port = port

    def _host_ok(self, host: str) -> bool:
        host = host.strip().lower()
        if self.port is not None:
            return host in {f"{h}:{self.port}" for h in ALLOWED_HOSTNAMES}
        name, sep, port = host.rpartition(":")
        return bool(sep) and name in ALLOWED_HOSTNAMES and port.isdigit()

    def _token_ok(self, scope: Scope) -> bool:
        supplied = ""
        for k, v in scope.get("headers", []):
            if k == TOKEN_HEADER.encode():
                supplied = v.decode("latin-1")
        if not supplied:
            q = parse_qs(scope.get("query_string", b"").decode("latin-1"))
            supplied = (q.get("token") or [""])[0]
        return hmac.compare_digest(supplied.encode(), self.token)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                await self.app(scope, receive, send)
            return
        host = next((v.decode("latin-1") for k, v in scope["headers"] if k == b"host"), "")
        resp: Response | None
        if not self._host_ok(host):
            resp = PlainTextResponse("Forbidden host", status_code=403)
        elif not self._token_ok(scope):
            resp = PlainTextResponse("Missing or invalid token", status_code=401)
        else:
            resp = None

        async def send_nostore(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"cache-control"]
                headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
            await send(message)

        if resp is not None:
            await resp(scope, receive, send_nostore)
            return
        await self.app(scope, receive, send_nostore)


def create_app(
    reader: TranscriptReader,
    token: str,
    *,
    port: int | None = None,
    sse_poll_interval: float = SSE_POLL_INTERVAL_S,
    sse_max_seconds: float | None = None,
    controller: RecordingControl | None = None,
) -> Starlette:
    """Build the panel app. `port` pins the accepted Host header port (None = any port, tests).
    `sse_max_seconds` ends each event stream after that long (tests only)."""

    async def index(request: Request) -> Response:
        html = _static_text("index.html").replace("__TOKEN__", token)
        return Response(html, media_type="text/html; charset=utf-8")

    async def static(request: Request) -> Response:
        name = request.path_params["name"]
        if name not in _STATIC_TYPES:
            return PlainTextResponse("Not found", status_code=404)
        return Response(_static_text(name), media_type=_STATIC_TYPES[name])

    async def api_status(request: Request) -> Response:
        st = await asyncio.to_thread(reader.read_status)
        return JSONResponse(asdict(st))

    def control_state() -> dict:
        if controller is None:
            return {"available": False, "reason": NO_CONTROLLER}
        return {
            "available": True,
            "recording": controller.is_recording(),
            "downloading": controller.is_downloading_model(),
            "error": controller.last_error(),
        }

    async def api_control(request: Request) -> Response:
        return JSONResponse(await asyncio.to_thread(control_state))

    async def api_recording(request: Request) -> Response:
        """POST {"recording": true|false}: idempotent start/stop through the shared controller."""
        if controller is None:
            return JSONResponse({"available": False, "reason": NO_CONTROLLER, "error": NO_CONTROLLER}, status_code=409)
        try:
            want = (await request.json())["recording"]
        except (ValueError, KeyError, TypeError):
            return PlainTextResponse('expected JSON {"recording": true|false}', status_code=400)
        if not isinstance(want, bool):
            return PlainTextResponse("'recording' must be a boolean", status_code=400)
        try:
            if want:
                if not await asyncio.to_thread(controller.is_recording):
                    await asyncio.to_thread(controller.start)  # may block on model load
            else:
                await asyncio.to_thread(controller.stop)
        except Exception as e:
            state = await asyncio.to_thread(control_state)
            state["error"] = controller.last_error() or str(e) or type(e).__name__
            return JSONResponse(state, status_code=500)
        return JSONResponse(await asyncio.to_thread(control_state))

    async def api_sessions(request: Request) -> Response:
        infos = await asyncio.to_thread(reader.list_sessions)
        return JSONResponse(
            [
                {
                    "id": s.id,
                    "started_at": s.started_at,
                    "segment_count": s.segment_count,
                    "is_active": s.is_active,
                }
                for s in infos
            ]
        )

    async def api_segments(request: Request) -> Response:
        session = request.query_params.get("session") or None
        try:
            since = int(request.query_params.get("since", "0"))
        except ValueError:
            return PlainTextResponse("bad 'since'", status_code=400)
        segs, cursor = await asyncio.to_thread(reader.read_segments, session, since)
        return JSONResponse({"segments": [asdict(s) for s in segs], "cursor": cursor})

    async def api_stream(request: Request) -> Response:
        session = request.query_params.get("session") or None  # None = follow the latest session
        try:
            cursor = int(request.query_params.get("since", "0"))
        except ValueError:
            return PlainTextResponse("bad 'since'", status_code=400)

        def sse(event: str, data: dict) -> str:
            return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        async def gen() -> AsyncIterator[str]:
            nonlocal cursor
            current = session
            if session is None:
                infos = await asyncio.to_thread(reader.list_sessions)
                current = infos[0].id if infos else None
            yield sse("session", {"id": current})
            started = last_sent = time.monotonic()
            while True:
                if await request.is_disconnected():
                    return
                if session is None:  # follow-latest: switch when a newer session appears
                    infos = await asyncio.to_thread(reader.list_sessions)
                    latest = infos[0].id if infos else None
                    if latest != current:
                        current, cursor = latest, 0
                        yield sse("session", {"id": current})
                if current is not None:
                    segs, new_cursor = await asyncio.to_thread(reader.read_segments, current, cursor)
                    for seg in segs:
                        yield sse("segment", asdict(seg))
                    if segs:
                        cursor = new_cursor
                        last_sent = time.monotonic()
                if time.monotonic() - last_sent > SSE_KEEPALIVE_S:
                    yield ": keepalive\n\n"
                    last_sent = time.monotonic()
                if sse_max_seconds is not None and time.monotonic() - started >= sse_max_seconds:
                    return
                await asyncio.sleep(sse_poll_interval)

        return StreamingResponse(gen(), media_type="text/event-stream")

    app = Starlette(
        routes=[
            Route("/", index),
            Route("/static/{name}", static),
            Route("/api/status", api_status),
            Route("/api/control", api_control),
            Route("/api/recording", api_recording, methods=["POST"]),
            Route("/api/sessions", api_sessions),
            Route("/api/segments", api_segments),
            Route("/api/stream", api_stream),
        ]
    )
    app.add_middleware(_GuardMiddleware, token=token, port=port)  # no CORS middleware, on purpose
    return app


class PanelServer:
    """Runs the panel with uvicorn in a background thread, bound to 127.0.0.1 only."""

    def __init__(
        self,
        reader: TranscriptReader,
        port: int,
        token: str | None = None,
        controller: RecordingControl | None = None,
    ) -> None:
        self.port = port
        self.token = token or new_token()
        self._app = create_app(reader, self.token, port=port, controller=controller)
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._error: BaseException | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/?token={self.token}"

    def start(self, timeout: float = 10.0) -> None:
        if self._thread is not None:
            return
        cfg = uvicorn.Config(
            self._app, host="127.0.0.1", port=self.port, log_level="warning", lifespan="off", access_log=False
        )
        server = uvicorn.Server(cfg)
        self._server = server
        self._error = None

        def run() -> None:
            try:
                server.run()
            except BaseException as e:  # uvicorn exits with SystemExit when the port is taken
                self._error = e

        thread = threading.Thread(target=run, name="panel-server", daemon=True)
        self._thread = thread
        thread.start()
        deadline = time.monotonic() + timeout
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                server.should_exit = True
                self._thread = None
                self._server = None
                raise RuntimeError(f"web panel failed to start on 127.0.0.1:{self.port} ({self._error!r})")
            time.sleep(0.02)

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._thread = None
        self._server = None
