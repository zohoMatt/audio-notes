(() => {
  "use strict";
  const token = new URLSearchParams(location.search).get("token") || "";
  const q = (params) => new URLSearchParams({ ...params, token }).toString();
  const $ = (id) => document.getElementById(id);
  const box = $("transcript");
  let sessions = [], selected = null, es = null, lastSeq = 0;
  let titleFor = null;  // {prefix, id}: the transcript title, re-rendered once the stream name is known

  const fmt = (s) => {
    s = Math.max(0, Math.floor(s));
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    const mm = String(m).padStart(2, "0"), ss = String(sec).padStart(2, "0");
    return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
  };
  const nearBottom = () => box.scrollHeight - box.scrollTop - box.clientHeight < 60;
  const toBottom = () => { box.scrollTop = box.scrollHeight; $("jump").hidden = true; };

  function addSegment(seg) {
    if (seg.seq <= lastSeq) return;
    lastSeq = seg.seq;
    const stick = nearBottom();
    const empty = box.querySelector(".empty");
    if (empty) empty.remove();
    const row = document.createElement("div");
    row.className = "row " + seg.speaker;
    const b = document.createElement("div");
    b.className = "bubble";
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = `${seg.speaker === "me" ? "Me" : "Them"} · ${fmt(seg.t0)}`;
    const text = document.createElement("div");
    text.textContent = seg.text;
    b.append(meta, text);
    row.append(b);
    box.append(row);
    if (stick) toBottom(); else $("jump").hidden = false;
  }

  const when = (id) => id.replace(/_(\d\d)-(\d\d)-(\d\d)/, " $1:$2:$3");
  const streamOf = (id) => (sessions.find((s) => s.id === id) || {}).stream;

  function renderTitle() {
    if (!titleFor) return;
    const { prefix, id, fallback } = titleFor;
    if (!id) { $("title").textContent = fallback; return; }
    const name = streamOf(id);
    $("title").textContent = `${prefix}${name ? name + " · " : ""}${when(id)}`;
  }

  function reset(title, emptyText) {
    box.replaceChildren();
    lastSeq = 0;
    titleFor = typeof title === "string" ? { fallback: title } : title;
    renderTitle();
    const e = document.createElement("div");
    e.className = "empty";
    e.textContent = emptyText || "No lines yet.";
    box.append(e);
  }

  function closeStream() { if (es) { es.close(); es = null; } }

  function openLive() {
    closeStream();
    selected = "live";
    reset("Live: following the latest session");
    es = new EventSource("/api/stream?" + q({ since: 0 }));
    es.addEventListener("session", (ev) => {
      const id = JSON.parse(ev.data).id;
      reset(id ? { prefix: "Live: ", id } : "Live: waiting for a session");
    });
    es.addEventListener("segment", (ev) => addSegment(JSON.parse(ev.data)));
    renderSessions();
  }

  async function openHistory(id) {
    closeStream();
    selected = id;
    reset({ prefix: "", id }, "This session is empty.");
    renderSessions();
    const r = await fetch("/api/segments?" + q({ session: id }));
    if (!r.ok || selected !== id) return;
    const data = await r.json();
    data.segments.forEach(addSegment);
    toBottom();
  }

  function renderSessions() {
    const ul = $("sessions");
    ul.replaceChildren();
    sessions.forEach((s, i) => {
      const li = document.createElement("li");
      const key = i === 0 ? "live" : s.id;
      if (selected === key) li.className = "sel";
      const top = document.createElement("div");
      top.className = "top";
      const tag = document.createElement("span");
      tag.className = "stream";
      tag.textContent = s.stream;
      tag.title = "Click to copy, then ask Claude about " + s.stream;
      tag.onclick = (ev) => { ev.stopPropagation(); copyName(tag, s.stream); };
      top.append(tag);
      if (s.is_active) {
        const l = document.createElement("span");
        l.className = s.is_paused ? "live paused" : "live";
        l.textContent = s.is_paused ? "❚❚ PAUSED" : "● REC";
        top.append(l);
      }
      const n = document.createElement("div");
      n.className = "n";
      n.textContent = `${when(s.id)} · ${s.segment_count} lines`;
      li.append(top, n);
      li.onclick = () => (i === 0 ? openLive() : openHistory(s.id));
      ul.append(li);
    });
    renderTitle();
  }

  async function copyName(tag, name) {
    try {
      await navigator.clipboard.writeText(name);
      tag.textContent = "Copied";
      setTimeout(() => { tag.textContent = name; }, 900);
    } catch (e) { /* clipboard unavailable: the name is still readable */ }
  }

  let failures = 0, ctl = { available: false }, busy = null;  // busy: the action in flight

  function setMsg(text, isErr) {
    const msg = $("ctl-msg");
    msg.textContent = text || "";
    msg.title = text || "";
    msg.className = "ctl-msg" + (isErr ? " err" : "");
    msg.hidden = !text;
  }

  function renderControl() {
    // Idle: [Start]. Recording: [Pause] [Stop]. Paused: [Continue] [Stop].
    const btn = $("rec-btn"), pb = $("pause-btn");
    const rec = !!ctl.recording, paused = rec && !!ctl.paused;
    btn.className = "rec-btn" + (rec ? " rec" : "");
    btn.textContent = busy === "stop" ? "Stopping…"
      : busy === "start" ? (ctl.downloading ? "Downloading model…" : "Starting…")
      : rec ? "■ Stop recording" : "● Start recording";
    btn.disabled = !!busy || !ctl.available;
    btn.title = ctl.available ? "" : (ctl.reason || "Recording control is unavailable.");
    pb.hidden = !rec;
    pb.className = "rec-btn" + (paused ? " resume" : "");
    pb.textContent = busy === "pause" ? "Pausing…" : busy === "resume" ? "Continuing…"
      : paused ? "▶ Continue" : "❚❚ Pause";
    pb.title = paused ? "Continue recording into the same session" : "Pause; Continue resumes the same session";
    pb.disabled = !!busy || !ctl.available;
    if (busy) return;
    if (!ctl.available) setMsg(ctl.reason ? "No recorder attached" : "", false);
    else setMsg(ctl.error, true);
  }

  async function act(action) {
    if (busy || !ctl.available) return;
    busy = action;
    setMsg("", false);
    renderControl();
    let err = null;
    try {
      const r = await fetch("/api/recording?" + q({}), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      let data = null;
      try { data = await r.json(); } catch (e) { /* plain-text error body */ }
      if (data) ctl = { ...ctl, ...data };
      if (!r.ok) err = (data && (data.error || data.reason)) || `Request failed (${r.status})`;
    } catch (e) {
      err = "Could not reach the panel server.";
    }
    busy = null;
    renderControl();
    if (err) setMsg(err, true);
    poll();
  }

  async function getJson(path) {
    const r = await fetch(path + "?" + q({}));
    if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
    return r.json();
  }

  async function poll() {
    try {
      const [st, ss, c] = await Promise.all([getJson("/api/status"), getJson("/api/sessions"), getJson("/api/control")]);
      failures = 0;
      const pill = $("status");
      pill.className = "pill " + (st.paused ? "paused" : st.recording ? "rec" : st.alive ? "idle" : "off");
      pill.textContent = st.paused ? `paused · ${st.segments} lines`
        : st.recording ? `recording · ${st.segments} lines` : st.alive ? "idle" : "recorder offline";
      sessions = ss;
      renderSessions();
      if (!busy) { ctl = c; renderControl(); }
    } catch (e) {
      // A single failed poll (slow response, wake from sleep) is not an outage: report after two in a row.
      if (++failures >= 2) {
        $("status").className = "pill off";
        $("status").textContent = "panel unreachable";
      }
    }
  }

  $("rec-btn").onclick = () => act(ctl.recording ? "stop" : "start");
  $("pause-btn").onclick = () => act(ctl.paused ? "resume" : "pause");
  const icon = document.querySelector('link[rel="icon"]');
  if (icon) $("logo").src = icon.href;  // the app icon, embedded once in the page head

  $("jump").onclick = toBottom;
  box.addEventListener("scroll", () => { if (nearBottom()) $("jump").hidden = true; });
  openLive();
  poll();
  setInterval(poll, 2000);
})();
