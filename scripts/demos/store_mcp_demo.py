"""Visual demo of the store + MCP server + read-side CLI: http://127.0.0.1:8803

Run from the repo: uv run python scripts/demos/store_mcp_demo.py
Feeds a canned two-speaker conversation through SessionWriter into a temporary data dir
(AUDIO_NOTES_DATA_DIR), and shows StoreReader output plus raw MCP tool results over stdio.
Never touches the real %APPDATA% data or the real Claude Desktop config.
"""
import asyncio, json, os, sys, tempfile, threading, time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DATA = tempfile.mkdtemp(prefix="audio-notes-demo-")
os.environ["AUDIO_NOTES_DATA_DIR"] = DATA
os.environ["AUDIO_NOTES_CLAUDE_CONFIG"] = os.path.join(DATA, "never-written.json")

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

from audio_notes.store.reader import StoreReader  # noqa: E402
from audio_notes.store.writer import SessionWriter  # noqa: E402

PORT = 8803
SCRIPT = [
    ("them", "Okay, let's start with the Q3 budget review."),
    ("me", "Sure. I think the marketing line is over by about ten percent."),
    ("them", "That's the campaign we launched in August."),
    ("me", "Right, can we move some of the travel budget to cover it?"),
    ("them", "Travel is already tight. What about the contractor budget?"),
    ("me", "Contractors finish in September, so there should be room."),
    ("them", "Good. Let's also schedule a follow-up meeting next Tuesday."),
    ("me", "Works for me. I'll send the invite after this call."),
]
reader = StoreReader()
feeder_state = {"done": False}


def feeder():
    w = SessionWriter()
    t0 = time.monotonic()
    for who, text in SCRIPT:
        time.sleep(3)
        a = time.monotonic() - t0
        w.append(a - 2.5, a, who, text)
    time.sleep(8)  # let the page show a live heartbeat, then stop recording
    w.close()
    feeder_state["done"] = True


def mcp_call(tool, args):
    async def go():
        p = StdioServerParameters(command=sys.executable, args=["-m", "audio_notes", "mcp"],
                                  env={"AUDIO_NOTES_DATA_DIR": DATA, "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")})
        async with stdio_client(p) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                return (await s.call_tool(tool, args)).content[0].text
    return asyncio.run(asyncio.wait_for(go(), 60))


def state():
    segs, cur = reader.read_segments()
    st = reader.read_status()
    return {
        "segments": [{"seq": s.seq, "t0": round(s.t0, 1), "speaker": s.speaker, "text": s.text} for s in segs],
        "cursor": cur,
        "status": {"recording": st.recording, "alive": st.alive, "session": st.session_id,
                   "segments": st.segments, "pid": st.pid,
                   "hb_age": None if st.last_heartbeat is None else round(time.time() - st.last_heartbeat, 1)},
        "sessions": [{"id": s.id, "n": s.segment_count, "active": s.is_active} for s in reader.list_sessions()],
    }


HTML = """<!doctype html><meta charset=utf-8><title>Audio Notes store and MCP demo</title>
<style>body{font:14px system-ui;margin:20px;max-width:1100px}h2{margin:.2em 0}
.cols{display:flex;gap:20px;flex-wrap:wrap}.col{flex:1;min-width:420px}
pre{background:#111;color:#ddd;padding:10px;border-radius:6px;white-space:pre-wrap;min-height:60px}
.me{color:#2a7}.them{color:#c60}.ok{color:#2a2}.bad{color:#c22}button,input{font:inherit;margin:2px}
code{background:#eee;padding:2px 4px;border-radius:3px}</style>
<h1>audio-notes — store / MCP / CLI demo</h1>
<p>Data dir: <code id=dd></code></p>
<div class=cols><div class=col>
<h2>StoreReader (live)</h2>
<div id=status></div><div id=sess></div><pre id=live></pre></div>
<div class=col><h2>Real MCP server (stdio subprocess)</h2>
<button onclick="gt()">get_transcript (since cursor)</button> cursor=<b id=cur>0</b>
<button onclick="gt(true)">reset cursor</button><br>
<input id=q value=budget size=12><button onclick="call('search_transcript',{query:q.value})">search_transcript</button>
<button onclick="call('list_sessions',{})">list_sessions</button>
<button onclick="call('get_status',{})">get_status</button>
<pre id=out>(click a tool)</pre></div></div>
<h2>Second terminal (same temp dir; run from D:\\Coding\\audio-notes, PowerShell)</h2><pre id=cmds></pre>
<script>
let cursor=0;const $=id=>document.getElementById(id);
async function call(tool,args){$('out').textContent='…';
 const r=await fetch('/api/mcp',{method:'POST',body:JSON.stringify({tool,args})});const t=await r.text();
 $('out').textContent='> '+tool+' '+JSON.stringify(args)+'\\n'+t;return t}
async function gt(reset){if(reset){cursor=0;$('cur').textContent=0;return}
 const t=await call('get_transcript',{since_cursor:cursor});const m=t.match(/cursor: (\\d+)$/);
 if(m){cursor=+m[1];$('cur').textContent=cursor}}
async function tick(){try{const s=await (await fetch('/api/state')).json();const st=s.status;
 $('status').innerHTML='alive: <b class='+(st.alive?'ok':'bad')+'>'+st.alive+'</b> recording: <b>'+st.recording+
  '</b> segments: '+st.segments+' heartbeat age: '+st.hb_age+'s pid: '+st.pid;
 $('sess').textContent='sessions: '+s.sessions.map(x=>x.id+' ('+x.n+')'+(x.active?' [active]':'')).join(', ');
 $('live').innerHTML=s.segments.map(x=>'<span class='+x.speaker+'>#'+x.seq+' ['+x.t0+'s] '+(x.speaker=='me'?'Me':'Them')+': '+x.text+'</span>').join('\\n')+'\\n\\nreader cursor: '+s.cursor;
 }catch(e){$('status').textContent='server unreachable'}}
fetch('/api/info').then(r=>r.json()).then(i=>{$('dd').textContent=i.data;$('cmds').textContent=i.cmds});
setInterval(tick,700);tick();
</script>"""

PS = f"$env:AUDIO_NOTES_DATA_DIR='{DATA}'; "
CMDS = "\n".join(PS + "uv run audio-notes " + c for c in ["show -f", "sessions", "status", "setup claude"])


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype="application/json"):
        b = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/api/state":
            self._send(json.dumps(state()))
        elif self.path == "/api/info":
            self._send(json.dumps({"data": DATA, "cmds": CMDS}))
        else:
            self._send(HTML, "text/html")

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        try:
            self._send(mcp_call(req["tool"], req["args"]), "text/plain")
        except Exception as e:  # noqa: BLE001
            self._send(f"ERROR: {e!r}", "text/plain")


if __name__ == "__main__":
    threading.Thread(target=feeder, daemon=True).start()
    print(f"Data dir: {DATA}\nOpen http://127.0.0.1:{PORT}/\n\nSecond-terminal commands:\n{CMDS}\n", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
