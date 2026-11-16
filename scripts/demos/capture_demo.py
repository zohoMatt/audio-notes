"""Visual demo of audio capture: http://127.0.0.1:8801

Run from the repo: uv run python scripts/demos/capture_demo.py
Shows live levels for loopback ("them") and microphone ("me"); buttons play a test tone
and a FileSource stereo WAV. Windows only.
"""
import json, time, wave, os, sys, threading, tempfile
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import numpy as np, winsound
from audio_notes.capture.win_wasapi import LoopbackSource, MicSource
from audio_notes.capture.file_source import FileSource

origin = time.monotonic()
S = {k: dict(peak=0.0, last=None, n=0, rate=None, name=None, error=None) for k in ("them", "me")}
fchunks = []; fstate = dict(running=False)
lock = threading.Lock()

def mk(sp):
    def cb(c):
        with lock:
            s = S[sp]; s["peak"] = float(np.abs(c.samples).max()) if c.samples.size else 0.0
            s["last"] = time.monotonic(); s["n"] += 1; s["rate"] = c.sample_rate
    return cb

srcs = []
for cls, sp in ((LoopbackSource, "them"), (MicSource, "me")):
    s = cls()
    try:
        s.start(mk(sp), origin); S[sp]["name"] = s.device_name; srcs.append(s)
    except Exception as e:
        S[sp]["error"] = f"{type(e).__name__}: {e}"

d = tempfile.mkdtemp()
tone = os.path.join(d, "tone.wav"); fw = os.path.join(d, "stereo.wav")
def wavw(p, x, ch, rate):
    with wave.open(p, "wb") as w:
        w.setnchannels(ch); w.setsampwidth(2); w.setframerate(rate); w.writeframes((x * 32767).astype("<i2").tobytes())
t = np.arange(88200) / 44100
wavw(tone, 0.3 * np.sin(2 * np.pi * 880 * t), 1, 44100)
t2 = np.arange(32000) / 16000
wavw(fw, np.stack([0.5 * np.sin(2 * np.pi * 440 * t2), 0.1 * np.sin(2 * np.pi * 440 * t2)], 1).reshape(-1), 2, 16000)

def play_file():
    fchunks.clear(); fstate["running"] = True
    fs = FileSource(fw, "me", realtime=True, chunk_ms=100, start_offset=10.0)
    fs.start(lambda c: fchunks.append(dict(t=round(c.t, 3), speaker=c.speaker, n=len(c.samples), rate=c.sample_rate, peak=round(float(np.abs(c.samples).max()), 3))), time.monotonic())
    def w(): fs.join(); fstate["running"] = False
    threading.Thread(target=w, daemon=True).start()

PAGE = """<!doctype html><meta charset=utf-8><title>capture demo</title>
<style>body{font:15px system-ui;max-width:760px;margin:20px auto;padding:0 16px}
.bar{height:22px;background:#eee;border-radius:4px;overflow:hidden}.bar i{display:block;height:100%;background:#2a7;width:0}
.card{border:1px solid #ccc;border-radius:8px;padding:12px;margin:12px 0}small{color:#666}.err{color:#b00;font-weight:600}
button{padding:8px 14px;margin-right:8px}pre{max-height:220px;overflow:auto;background:#f6f6f6;padding:8px;font-size:12px}</style>
<h2>audio-notes capture demo</h2>
<div id=cards></div>
<button onclick="fetch('/tone')">Play 2s test tone (them)</button>
<button onclick="fetch('/file')">Play FileSource (stereo wav, speaker=me, start_offset=10)</button>
<div class=card><b>FileSource chunks</b> <small id=fs></small><pre id=fl></pre></div>
<script>
const names={them:'them (loopback)',me:'me (microphone)'};
async function tick(){const s=await (await fetch('/state')).json();let h='';
for(const k of ['them','me']){const x=s.src[k];h+=`<div class=card><b>${names[k]}</b> <small>${x.name||''} ${x.rate?x.rate+' Hz':''}</small>`;
if(x.error)h+=`<div class=err>NOT AVAILABLE: ${x.error}</div>`;else{
h+=`<div class=bar><i style="width:${Math.min(100,Math.sqrt(x.peak*10)*100)}%"></i></div><small>peak ${x.peak.toFixed(4)} · chunks ${x.n} · last chunk ${x.age==null?'never (no frames yet — normal for loopback in silence)':x.age.toFixed(2)+' s ago'}</small>`}
h+='</div>'}
cards.innerHTML=h;fs.textContent=s.file.running?'(playing)':'(idle)';
fl.textContent=s.file.chunks.map(c=>`t=${c.t.toFixed(3)}  ${c.speaker}  ${c.n} samples @${c.rate}  peak ${c.peak}`).join(String.fromCharCode(10))}
setInterval(tick,100)
</script>"""

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        ct, body = "text/html", PAGE.encode()
        if self.path == "/state":
            now = time.monotonic()
            with lock:
                src = {k: dict(v, age=None if v["last"] is None else now - v["last"], peak=v["peak"] if v["last"] and now - v["last"] < 0.5 else 0.0) for k, v in S.items()}
            for v in src.values(): v.pop("last")
            ct, body = "application/json", json.dumps(dict(src=src, file=dict(running=fstate["running"], chunks=list(fchunks)[-30:]))).encode()
        elif self.path == "/tone":
            winsound.PlaySound(tone, winsound.SND_FILENAME | winsound.SND_ASYNC); body = b"ok"
        elif self.path == "/file":
            play_file(); body = b"ok"
        self.send_response(200); self.send_header("Content-Type", ct); self.end_headers(); self.wfile.write(body)

print("open http://127.0.0.1:8801  (Ctrl+C to stop)", flush=True)
try: ThreadingHTTPServer(("127.0.0.1", 8801), H).serve_forever()
finally:
    for s in srcs: s.stop()
