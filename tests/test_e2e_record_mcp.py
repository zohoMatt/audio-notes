"""The whole chain without audio hardware, as a user would run it:

    audio-notes record --them-file ... --me-file ...   (real VAD + real tiny.en ASR)
        -> JSONL in the data dir
        -> audio-notes mcp (real stdio subprocess) -> MCP client reads the transcript
"""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from typer.testing import CliRunner

from audio_notes.cli import app

FIX = Path(__file__).parent / "fixtures"

pytestmark = [pytest.mark.e2e]


def _env(data_dir):
    env = dict(os.environ)
    env["AUDIO_NOTES_DATA_DIR"] = str(data_dir)
    env["AUDIO_NOTES_MODEL"] = "tiny.en"
    return env


def _mcp_call(data_dir, tool, args=None):
    async def go():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "audio_notes", "mcp"],
            env={"AUDIO_NOTES_DATA_DIR": str(data_dir), "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")},
        )
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = await s.call_tool(tool, args or {})
                return res.content[0].text

    return asyncio.run(asyncio.wait_for(go(), 60))


@pytest.mark.slow
def test_record_files_then_read_through_mcp(tmp_path):
    proc = subprocess.run(
        [
            sys.executable, "-m", "audio_notes", "record", "--fast",
            "--them-file", str(FIX / "them_budget.wav"),
            "--me-file", str(FIX / "me_followup.wav"),
        ],
        env=_env(tmp_path), capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Done:" in proc.stdout

    text = _mcp_call(tmp_path, "get_transcript").lower()
    assert "them:" in text and "me:" in text
    assert any(w in text for w in ("budget", "review", "thursday")), text  # them_budget.wav
    assert any(w in text for w in ("proposal", "team", "tomorrow")), text  # me_followup.wav

    status = _mcp_call(tmp_path, "get_status")
    # The session was closed. Right after a stop the heartbeat is still fresh, so the recorder
    # may read as "running", but it must not claim to be recording.
    assert "recording=no" in status.lower() or "not running" in status.lower(), status


def test_record_rejects_a_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIO_NOTES_DATA_DIR", str(tmp_path))
    result = CliRunner().invoke(app, ["record", "--them-file", str(tmp_path / "nope.wav")])
    assert result.exit_code == 1
    assert "No such file" in result.output
