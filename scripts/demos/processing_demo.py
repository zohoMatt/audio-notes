"""Visual demo of the processing + ASR pipeline: http://127.0.0.1:8802

Run from the repo: uv run python scripts/demos/processing_demo.py
Click Start; uses tests/fixtures by default, or your own WAV paths (16-bit PCM).
"""
import json, os, tempfile, threading, time, wave, logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
FIX = os.path.join(REPO, "tests", "fixtures")
OUT = tempfile.mkdtemp(prefix="audio-notes-processing-demo-")  # generated WAVs live here, not in the repo
from audio_notes.asr.faster_whisper_engine import FasterWhisperTranscriber
from audio_notes.asr.base import Transcriber
from audio_notes.capture.file_source import FileSource
from audio_notes.config import Config
from audio_notes.processing.runner import PipelineRunner

logging.basicConfig(level=logging.INFO)


def readwav(p):
    with wave.open(p) as w:
        ch, raw, sr = w.getnchannels(), w.readframes(w.getnframes()), w.getframerate()
    x = np.frombuffer(raw, "<i2").astype(np.float32) / 32768
    return (x.reshape(-1, ch).mean(1) if ch > 1 else x), sr


def writewav(p, x, sr=16000):
    with wave.open(p, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())


def make_default(name, parts):
    sil = lambda s: np.zeros(int(16000 * s), np.float32)
    out = [sil(1.0)]
    for f in parts:
        out += [readwav(os.path.join(FIX, f))[0], sil(2.0)]
    p = os.path.join(OUT, name)
    writewav(p, np.concatenate(out))
    return p


DEF_ME = make_default("me.wav", ["me_followup.wav", "me_question.wav"])
DEF_THEM = make_default("them.wav", ["them_budget.wav", "them_release.wav"])


def peaks(p, n_per_s=50):
    x, sr = readwav(p)
    b = sr // n_per_s
    k = len(x) // b
    return {"dur": len(x) / sr, "peaks": np.abs(x[: k * b]).reshape(k, b).max(1).round(3).tolist(), "n_per_s": n_per_s}


class Timed(Transcriber):
    def __init__(self, inner, st):
        self.i, self.st = inner, st

    def transcribe(self, s):
        t = time.perf_counter()
        r = self.i.transcribe(s)
        w = time.perf_counter() - t
        self.st["asr_audio"] += len(s) / 16000
        self.st["asr_wall"] += w
        return r


class Sink:
    def __init__(self, st):
        self.st = st

    def append(self, t0, t1, speaker, text):
        self.st["segments"].append({"t0": t0, "t1": t1, "speaker": speaker, "text": text,
                                    "at": time.monotonic() - self.st["t_start"]})

    def close(self):
        pass


cur_files = {}
models = {}
state = {"running": False, "segments": [], "error": None}
lock = threading.Lock()


def run_job(me, them, model):
    st = state
    try:
        if model not in models:
            st["status"] = f"loading {model} (first use downloads it)..."
            m = FasterWhisperTranscriber(Config(model=model))
            m.load()
            models[model] = m
        st.update(status="running", asr_audio=0.0, asr_wall=0.0, t_start=time.monotonic())
        srcs = [FileSource(me, "me", realtime=True), FileSource(them, "them", realtime=True)]
        r = PipelineRunner(srcs, Timed(models[model], st), Sink(st))
        r.start()
        for s in srcs:
            s.join()
        st["status"] = "draining ASR queue..."
        r.stop()
        st["elapsed"] = time.monotonic() - st["t_start"]
        st["done"] = True
        st["status"] = "done"
    except Exception as e:
        logging.exception("job failed")
        st["error"] = repr(e)
        st["status"] = "error"
        st["done"] = True
    finally:
        st["running"] = False


PAGE = open(os.path.join(HERE, "processing_demo.html"), encoding="utf-8").read()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, body, ctype="application/json"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(200)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/":
            return self.send(PAGE, "text/html")
        if self.path == "/state":
            s = dict(state)
            if s.get("t_start") and not s.get("done"):
                s["elapsed"] = time.monotonic() - s["t_start"]
            s.pop("t_start", None)
            return self.send(json.dumps(s))
        path = self.path.split("?")[0]
        if path in ("/audio/me", "/audio/them"):
            p = cur_files.get(path[7:])
            if p and os.path.exists(p):
                return self.send(open(p, "rb").read(), "audio/wav")
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(n) or b"{}")
        with lock:
            if state["running"]:
                return self.send(json.dumps({"error": "already running"}))
            me = req.get("me") or DEF_ME
            them = req.get("them") or DEF_THEM
            try:
                wf = {"me": peaks(me), "them": peaks(them)}
            except Exception as e:
                return self.send(json.dumps({"error": f"cannot read WAV: {e}"}))
            cur_files.update(me=me, them=them)
            state.clear()
            state.update(running=True, segments=[], wave=wf, status="starting", error=None, done=False)
        threading.Thread(target=run_job, args=(me, them, req.get("model", "tiny.en")), daemon=True).start()
        self.send(json.dumps({"ok": True}))


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", 8802), H)
    print("open http://127.0.0.1:8802", flush=True)
    srv.serve_forever()
