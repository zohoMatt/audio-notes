(() => {
  "use strict";
  const token = new URLSearchParams(location.search).get("token") || "";
  const q = (params) => new URLSearchParams({ ...params, token }).toString();
  const $ = (id) => document.getElementById(id);
  const box = $("transcript");
  let sessions = [], selected = null, es = null, lastSeq = 0;

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

  function reset(title, emptyText) {
    box.replaceChildren();
    lastSeq = 0;
    $("title").textContent = title;
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
      reset(id ? `Live: ${id}` : "Live: waiting for a session");
    });
    es.addEventListener("segment", (ev) => addSegment(JSON.parse(ev.data)));
    renderSessions();
  }

  async function openHistory(id) {
    closeStream();
    selected = id;
    reset(`Session ${id}`, "This session is empty.");
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
      li.textContent = s.id.replace("_", " ").replace(/-(\d\d)-(\d\d)$/, ":$1:$2");
      if (s.is_active) {
        const l = document.createElement("span");
        l.className = "live";
        l.textContent = "● REC";
        li.append(l);
      }
      const n = document.createElement("div");
      n.className = "n";
      n.textContent = `${s.segment_count} lines`;
      li.append(n);
      li.onclick = () => (i === 0 ? openLive() : openHistory(s.id));
      ul.append(li);
    });
  }

  async function poll() {
    try {
      const [st, ss] = await Promise.all([
        fetch("/api/status?" + q({})).then((r) => r.json()),
        fetch("/api/sessions?" + q({})).then((r) => r.json()),
      ]);
      const pill = $("status");
      pill.className = "pill " + (st.recording ? "rec" : st.alive ? "idle" : "off");
      pill.textContent = st.recording ? `recording · ${st.segments} lines` : st.alive ? "idle" : "recorder offline";
      sessions = ss;
      renderSessions();
    } catch (e) {
      $("status").className = "pill off";
      $("status").textContent = "panel unreachable";
    }
  }

  $("jump").onclick = toBottom;
  box.addEventListener("scroll", () => { if (nearBottom()) $("jump").hidden = true; });
  openLive();
  poll();
  setInterval(poll, 2000);
})();
