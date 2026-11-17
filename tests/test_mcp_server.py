import asyncio
import json
import os
import subprocess
import sys
import textwrap
from datetime import datetime

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from audio_notes.store.writer import SessionWriter


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIO_NOTES_DATA_DIR", str(tmp_path))
    return tmp_path


def _env(data_dir):
    return {
        "AUDIO_NOTES_DATA_DIR": str(data_dir),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
    }


def _call(data_dir, tool, args=None):
    async def go():
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "audio_notes", "mcp"], env=_env(data_dir)
        )
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                names = {t.name for t in (await s.list_tools()).tools}
                res = await s.call_tool(tool, args or {})
                return names, res.content[0].text

    return asyncio.run(asyncio.wait_for(go(), 60))


def _fill(at=datetime(2026, 1, 1, 10)):
    w = SessionWriter(at)
    w.append(5, 6, "me", "hello there")
    w.append(65, 66, "them", "Budget numbers")
    w.append(125, 126, "me", "ok")
    return w


def test_tools_listed_and_get_transcript(data_dir):
    w = _fill()
    names, text = _call(data_dir, "get_transcript")
    assert names == {"get_transcript", "search_transcript", "list_sessions", "get_status"}
    assert text.splitlines() == [
        "[00:05] Me: hello there",
        "[01:05] Them: Budget numbers",
        "[02:05] Me: ok",
        "cursor: 2026-01-01_10-00-00:3",
    ]
    _, text = _call(data_dir, "get_transcript", {"since_cursor": "2026-01-01_10-00-00:3"})
    assert text == "(no new transcript)\ncursor: 2026-01-01_10-00-00:3"
    _, text = _call(data_dir, "get_transcript", {"since_cursor": "2026-01-01_10-00-00:1"})
    assert "hello there" not in text and text.endswith("cursor: 2026-01-01_10-00-00:3")
    _, text = _call(data_dir, "get_transcript", {"since_cursor": 1})  # bare seq from older clients
    assert "hello there" not in text and "Budget" in text
    _, text = _call(data_dir, "get_transcript", {"last_n_minutes": 1.5})
    assert "hello there" not in text and "Budget" in text
    w.close()


def test_get_transcript_cursor_survives_a_new_session(data_dir):
    w = _fill()
    w.close()
    w2 = SessionWriter(datetime(2026, 1, 1, 11))
    w2.append(1, 2, "them", "new one")
    w2.append(3, 4, "me", "new two")
    # A cursor in the middle of the old session: its rest comes first, then the whole new session
    # (with a bare seq cursor of 2, the new session's first two lines would have been skipped).
    _, text = _call(data_dir, "get_transcript", {"since_cursor": "2026-01-01_10-00-00:2"})
    lines = text.splitlines()
    assert lines == [
        "(rest of session 2026-01-01_10-00-00)",
        "[02:05] Me: ok",
        "(new session 2026-01-01_11-00-00 started)",
        "[00:01] Them: new one",
        "[00:03] Me: new two",
        "cursor: 2026-01-01_11-00-00:2",
    ]
    _, text = _call(data_dir, "get_transcript", {"since_cursor": "garbage:x"})
    assert "bad cursor" in text
    w2.close()


def test_search_sessions_status(data_dir):
    w = _fill()
    _, text = _call(data_dir, "search_transcript", {"query": "budget"})
    assert "[01:05] Them: Budget numbers" in text
    _, text = _call(data_dir, "search_transcript", {"query": "zzz"})
    assert "No matches" in text
    _, text = _call(data_dir, "list_sessions")
    assert "2026-01-01_10-00-00" in text and "3 segments" in text and "[active]" in text
    _, text = _call(data_dir, "get_status")
    assert "recording=yes" in text and "segments=3" in text
    w.close()


def test_empty_store(data_dir):
    _, text = _call(data_dir, "get_transcript")
    assert text == "(no new transcript)\ncursor: 0"
    _, text = _call(data_dir, "get_status")
    assert "not running" in text


def test_status_with_an_idle_daemon(data_dir):
    from audio_notes.store.status import StatusPublisher

    with StatusPublisher().start():  # the tray: alive, no session yet
        _, text = _call(data_dir, "get_status")
    assert "Recorder running; recording=no" in text


def test_real_stdio_process_does_not_import_heavy_deps(data_dir, tmp_path):
    """Run the real `audio-notes mcp` command path in a subprocess; at exit it reports
    which heavy modules ended up imported."""
    report = tmp_path / "modules.json"
    script = textwrap.dedent(
        f"""
        import atexit, json, sys
        def dump():
            heavy = [m for m in sys.modules if m.split('.')[0] in
                     ('faster_whisper', 'pyaudio', 'pyaudiowpatch', 'pystray', 'torch', 'ctranslate2')]
            open({str(report)!r}, 'w').write(json.dumps(heavy))
        atexit.register(dump)
        sys.argv = ['audio-notes', 'mcp']
        from audio_notes.cli import app
        app()
        """
    )
    w = _fill()
    init = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"},
            },
        }
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        input=init + "\n",
        capture_output=True,
        text=True,
        timeout=60,
        env=_env(data_dir),
    )
    w.close()
    assert '"result"' in proc.stdout, proc.stderr
    assert report.exists(), proc.stderr
    assert json.loads(report.read_text()) == []
