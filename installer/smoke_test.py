"""OPTIONAL smoke test for the built bundle. Safe to delete together with the
`smoke` step in release.yml (and `installer/smoke_test.ps1` is not needed).

  python installer/smoke_test.py [path\to\audio-notes.exe]

Checks `--version`, then one MCP stdio handshake (initialize + tools/list).
Uses only the standard library.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

exe = Path(sys.argv[1] if len(sys.argv) > 1 else "dist/audio-notes/audio-notes.exe").resolve()
env = dict(os.environ, AUDIO_NOTES_DATA_DIR=tempfile.mkdtemp(prefix="audio-notes-smoke-"))

out = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=60, env=env)
assert out.returncode == 0, f"--version failed: {out.stderr}"
print("version:", out.stdout.strip())

proc = subprocess.Popen([str(exe), "mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, text=True, env=env)


def rpc(msg):
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()


def read_response(want_id):
    while True:
        line = proc.stdout.readline()
        if not line:
            raise SystemExit(f"MCP server closed stdout. stderr:\n{proc.stderr.read()}")
        msg = json.loads(line)
        if msg.get("id") == want_id:
            return msg


try:
    rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2024-11-05", "capabilities": {},
        "clientInfo": {"name": "smoke", "version": "0"}}})
    init = read_response(1)
    assert "result" in init, init
    rpc({"jsonrpc": "2.0", "method": "notifications/initialized"})
    rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tools = read_response(2)["result"]["tools"]
    names = [t["name"] for t in tools]
    assert names, "tools/list returned no tools"
    print("mcp tools:", ", ".join(names))
finally:
    proc.stdin.close()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
print("smoke test OK")
