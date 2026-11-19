# audio-notes Requirements (MVP)

## 1. Goal

A lightweight Windows tray tool (macOS to follow). It captures system audio and the microphone in real time and transcribes them locally into English text. Through MCP, Claude reads the transcript on demand and uses it as conversation context.

## 2. Confirmed decisions

| Item | Decision |
|---|---|
| Use cases | Online meetings + videos/online classes/live streams. General system audio; microphone optional |
| ASR | Local and offline; no audio is uploaded |
| Language | English |
| Claude interaction | MCP pull (Claude calls tools on demand); no active push in the MVP |
| Speakers | Only "me / them", implemented with two channels |
| Storage | Each meeting is saved as a local file |
| Tech stack | Python |
| Compliance | A legal-risk notice on first run is enough; no complex mechanism |
| UI | Tray icon + menu; live transcript viewing through a local web panel (opened in the browser); no native main window |

## 3. Functional requirements

### 3.1 Audio capture
- **F1** Capture system output audio through WASAPI loopback (labeled "them").
- **F2** Optionally capture the default microphone (labeled "me"); it can be toggled in the menu.
- **F3** The two audio streams are processed independently and not mixed, so speaker labels stay accurate.
- **F4** The capture layer is abstracted behind an interface, so a macOS implementation (ScreenCaptureKit) can be added later.

### 3.2 Transcription
- **F5** Use a local model (candidates: faster-whisper or whisper.cpp small/base English models) and transcribe in segments (VAD). The MVP uses CPU inference only (int8 quantization) and does not depend on a GPU.
- **F5a** The inference device (CPU / GPU) and model size are config options. The MVP is fixed to CPU; GPU switching and a settings entry are planned for phase 2.
- **F6** Only final results are saved, not partial ones.
- **F7** Each segment contains: sequence number, start and end timestamps, speaker (me / them), text.
- **F8** Latency target: a sentence can be read about 5 seconds after it ends (to be measured).

### 3.3 Storage
- **F9** Each recording start creates a session, written to `transcripts/<date-time>.jsonl`, one segment per line.
- **F10** When a session ends, a readable `.md` is also generated.
- **F11** Audio itself is never written to disk; only text is saved.

### 3.4 MCP service
- **F12** Provide an MCP server (stdio, configured in Claude Desktop / Claude Code).
- **F13** Tools:
  - `get_transcript(since_cursor?, last_n_minutes?)`: incremental read; returns a new cursor.
  - `search_transcript(query)`: keyword search.
  - `list_sessions()`: list past sessions.
  - `get_status()`: whether recording is active, the current session ID, and the number of segments recorded.
- **F14** A rolling summary (`get_summary`) is not in the MVP; it is planned for phase 2.

### 3.5 Tray UI
- **F15** The icon has three states: idle, recording, error.
- **F16** Menu: start/pause, toggle microphone, open panel (see F28), open transcript folder, connect to Claude (see F22), quit.
- **F17** On first run, show a one-time notice: before recording other people, confirm this complies with local law and inform the participants. After the user confirms, it is not shown again.

### 3.6 Installation and distribution
- **F18** Publish as the PyPI package `audio-notes`, with the console script `audio-notes`. Platform-specific dependencies (such as PyAudioWPatch) use the environment marker `sys_platform == "win32"`.
- **F19** Developer install path: `uv tool install audio-notes` (uv manages Python automatically; all dependencies are prebuilt wheels; no manual environment setup).
- **F20** Regular-user install path: a Windows installer (PyInstaller **onedir** + Inno Setup). Double-click to install; no preinstalled Python needed.
  - Tray, MCP and CLI share the same `audio-notes.exe`, distinguished by subcommand.
  - Do not use onefile mode (it unpacks on every start, which slows down Claude launching the MCP process).
  - Installer: creates a Start menu entry; adding to PATH is optional.
  - **No launch at startup** (neither on Windows nor macOS). The product is local and offline and only runs when the user opens it. A recording tool that starts itself at boot would make people uneasy.
- **F21** The model is downloaded on first run (not bundled in the installer). The tray shows a "downloading" state. After the download, the tool works fully offline. `audio-notes model download` will also be offered for pre-downloading (later).
- **F22** Tray menu "Connect to Claude": calls `setup claude` to write Claude's MCP config. A confirmation dialog is required before writing. The config uses the **absolute path** of the `audio-notes` executable (the PATH of Claude Desktop's child process may be incomplete). The CLI `setup claude` only prints the config by default; it writes only with `--write`.
- **F23** CI/CD (GitHub Actions): push/PR triggers pytest on Windows. Pushing a `v*` tag triggers the build, publishes to PyPI (using Trusted Publishing; PyPI publishing needs manual approval), and builds the installer and attaches it to GitHub Releases. The version number comes from the git tag (hatch-vcs).

- **F33** Distribution channel priority: in the MVP, `uv tool install` / `pip install` are the main recommended channels (they do not trigger SmartScreen download blocking). The Windows installer is an extra channel.
- **F34** False-positive and blocking mitigation (required for the MVP):
  - PyInstaller uses onedir, with no UPX or other compression.
  - The installer is only built on GitHub Actions; GitHub Release notes include the SHA256 checksum.
  - The README and release notes state that unsigned programs trigger SmartScreen ("More info → Run anyway"). Windows 11 with Smart App Control enabled may block unsigned programs outright, with no option to allow them; in that case, use pip/uv instead.
  - After each release, submit false-positive reports to Microsoft Defender and the major antivirus vendors (the process is written in the release notes).
  - Depending on false positives, reevaluate compiling the PyInstaller bootloader ourselves.
- **F35** Code signing (not in the MVP; listed with a trigger condition): reevaluate when the tool needs to be distributed to non-technical users. Candidates: Microsoft Trusted Signing (has regional and applicant-identity restrictions; confirm eligibility first), a traditional OV certificate, Microsoft Store (MSIX, signed by the store, but requires packaging and review per store rules). Official pages are authoritative for prices and policies.

### 3.7 Command line (CLI)
- **F24** Single entry point `audio-notes` (or `python -m audio_notes`). MVP subcommands:
  - `tray`: start the tray daemon.
  - `mcp`: start the MCP server (stdio).
  - `record`: headless foreground recording; Ctrl+C to stop.
  - `devices`: list audio devices (loopback / microphone).
  - `sessions`: list past sessions.
  - `show [session] -n N -f`: view a transcript; `-f` keeps following.
  - `status`: whether the daemon is running, and the current session.
  - `setup claude`: print (or write, with `--write`) Claude's MCP config; see F22.
  - `--version`.
- **F25** Lazy loading of heavy dependencies: `mcp`, `sessions`, `show`, `status` and `--help` must not import ASR or audio capture dependencies, so they start fast.
- **F26** Implemented with Typer.
- **F27** To add later: `export` (export md), `model download`, `doctor` (self-check of devices/model/permissions).

### 3.8 Local web panel
- **F28** The tray process starts a local HTTP server, bound only to `127.0.0.1`, with a configurable port. The tray menu "Open panel" opens it in the default browser.
- **F29** Pages (read-only in the MVP): live transcript (SSE push, me/them distinguished, auto-scroll), session list and history view, recording status.
- **F30** Tech: Starlette + plain HTML/JS. No frontend build step and no Node. Page data is always read through `store.reader`, with no direct dependency on the transcription pipeline.
- **F31** Security: listen only on the loopback address; validate the Host header; no CORS; the URL carries a random token generated at startup (attached when the tray opens it), so other web pages cannot read the transcript through DNS rebinding.
- **F32** Editing settings in the panel (CPU/GPU, model size, etc.) is not in the MVP.

## 4. Non-functional requirements

- **Lightweight**: CPU near 0 when idle. While recording, the CPU target is under 50% of one core (base model, to be measured).
- **Privacy**: fully usable without a network connection. No data is sent to any service, except what MCP returns to the user's own Claude.
- **Stability**: no crash when the audio device changes (headphones plugged in or out); automatically reconnect to the default device.
- **Platform**: the MVP supports only Windows 10/11 (x64); macOS 13+ is planned for phase 2. Availability of dependency wheels on Windows ARM devices is to be verified.
- **Runtime environment**:
  - Python 3.10+ (3.11/3.12 recommended; on 3.13 some dependency wheels may lag behind; to be measured in M1). No preinstalled Python is needed when using the installer.
  - Memory: `base.en` takes a few hundred MB; `small.en` is on the order of 1 GB (to be measured in M2). Disk: the model is about 150–500 MB; together with dependencies, under 1 GB in total.
  - Network: needed only for the first model download.
  - Permissions: no admin rights needed. Desktop apps must be allowed to access the microphone in Windows privacy settings.
  - No extra drivers, virtual sound cards, C++ build tools or ffmpeg needed.
  - Known limitations: audio in WASAPI exclusive mode cannot be captured through loopback. Using speakers makes the microphone record the other side's voice again; headphones are recommended.
  - On the Claude side, a client that supports MCP stdio is needed (Claude Desktop / Claude Code).

## 5. How to use it with Claude

1. Configure this MCP server in Claude Desktop or Claude Code.
2. Create a Project, with instructions such as "The user is in a meeting. When needed, call the audio-notes tools to read the transcript."
3. Start a new conversation for each meeting and ask at any time during it, for example "What did they just say?" or "Help me draft a reply." Claude pulls the content through `get_transcript`.

## 6. Out of scope (not in the MVP)

- Active push, notifications, keyword-triggered alerts
- Separating multiple remote speakers (Speaker 1/2/3)
- Cloud ASR, Chinese and other languages
- Rolling summaries, automatic post-meeting summaries
- macOS support, auto-update, installer code signing (the MVP accepts the warnings that come with being unsigned; see F35 for trigger conditions and candidates)
- A settings UI (including CPU/GPU switching and model size switching, and settings editing in the web panel), automatic data cleanup
- Accessing the web panel over the network (local machine only)

## 7. Milestones

1. **M1** Capture check: record loopback + microphone to wav and confirm both streams work.
2. **M2** Transcription: add VAD and local ASR, output JSONL, measure latency and CPU.
3. **M3** CLI: `record`, `show -f`, `sessions`, etc. At this point, end-to-end testing works without the tray.
4. **M4** MCP server + `setup claude`: implement F12–F13 and the CLI part of F22; get "read and answer" working in Claude.
5. **M5** Tray and web panel: status icon, menu, first-run legal notice, "Connect to Claude", live transcript panel (F28–F31).
6. **M6** Release: PyPI package and CI/CD (F18–F19, F23), then the Windows installer (F20–F21).
7. **M7** Phase 2 evaluation: rolling summary, active alerts, GPU and settings UI, macOS.

## 8. Risks to verify

- Accuracy and latency of local English ASR on meeting audio quality (compression, overlapping speech).
- Pick the model size (`base.en` / `small.en`, int8 quantization), and measure CPU usage and latency with system audio + microphone running concurrently (CPU is expected to be viable; only a balance point needs to be chosen).
- MCP is pull-based. If users want Claude to interrupt with alerts on its own, phase 2 needs a direct API connection or another mechanism.
- Installer size (ctranslate2 and onnxruntime are heavy; expected to be on the order of a few hundred MB; confirm after actual packaging).
- Impact of SmartScreen / antivirus false positives on the unsigned exe for the first users, and Smart App Control blocking unsigned programs outright. Mitigations are in F33–F35; the actual false-positive rate must be observed after the first release.
- Security of the local web service: confirm that Host validation and the token scheme are enough to defend against DNS rebinding. Confirm that the Starlette / uvicorn already pulled in by the MCP SDK can be reused, to avoid extra dependencies.

## 9. Manual test checklist (not automated; discussed with the user late in development and tested by the user)

- Tray: switching between the three icon states, each right-click menu item, "Open panel", first-run legal notice.
- Duplicate `me` / `them` transcription caused by microphone echo when using speakers (not headphones).
- Whether recording recovers automatically after the default audio device changes (plugging headphones in or out) mid-recording.
- After "Connect to Claude" writes the config, really getting "read and answer" working in Claude Desktop / Claude Code.
- Installing, launching and uninstalling the installer on a clean Windows environment, and the SmartScreen / antivirus warnings.
- Note: whether to keep the automated installer smoke test (`--version` + MCP handshake) is up to the user.
