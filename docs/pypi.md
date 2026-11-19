<!-- The project description on PyPI (pyproject.toml `readme`). The GitHub README is README.md:
     keep the two in step. PyPI resolves no relative links: use absolute URLs only. -->

<img src="https://raw.githubusercontent.com/zohoMatt/audio-notes/main/docs/icon.png" alt="Audio Notes" width="180">

# Audio Notes

### Your meetings, transcribed on your computer. Ask Claude about them.

**Open source. Fully local. Works offline. Secure by default.**<br>
System audio + microphone → Whisper on your CPU → Claude, over MCP. Audio never leaves your machine.

[![Download](https://img.shields.io/badge/Download-Windows%20%7C%20macOS-312E81?style=for-the-badge&logo=github&logoColor=white)](https://github.com/zohoMatt/audio-notes/releases/latest)

![Windows](https://img.shields.io/badge/Windows-10%20%7C%2011-0078D6?logo=windows&logoColor=white)
![macOS](https://img.shields.io/badge/macOS-14.2%2B%20Apple%20Silicon-000000?logo=apple&logoColor=white)
![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![MCP](https://img.shields.io/badge/Claude-MCP%20server-D97757)
![100% local](https://img.shields.io/badge/transcription-100%25%20local-16A34A)
![License: MIT](https://img.shields.io/badge/license-MIT-blue)

---

Audio Notes is a lightweight tool for **Windows** (notification-area icon) and **macOS** (menu bar
icon). It captures **system audio** (what you hear) and your **microphone**, transcribes both on
your own CPU with [faster-whisper](https://github.com/SYSTRAN/faster-whisper), and lets Claude read
the transcript through an [MCP](https://modelcontextprotocol.io) server. No cloud service, no
account, no telemetry.

- **Open source.** MIT-licensed, built on open-source libraries. You can read exactly what it does
  with your audio.
- **Fully local.** Capture and transcription run on your computer. Audio is never written to disk
  or sent anywhere; transcripts are plain files on your disk.
- **Works offline.** After the speech model is downloaded once, recording and transcription need no
  internet connection.
- **Secure by default.** Claude connects over stdio, so there is no network port to reach. The
  panel listens on `127.0.0.1` only and requires a random token that changes on every run.

Transcript lines leave your computer only when you ask Claude about them: the lines Claude reads
become part of that conversation. See "What stays on your computer" below.

| | Supported |
|---|---|
| Windows | 10 and 11, 64-bit |
| macOS | 14.2 (Sonoma) or later, Apple Silicon (M1 or newer). Intel Macs are not supported |
| Linux | Not supported |

## Quick start

### 1. Install

```bash
uv tool install audio-notes
audio-notes --version
audio-notes tray
```

Install [uv](https://docs.astral.sh/uv/) first if you don't have it; it manages Python for you
(`pipx install audio-notes` works too). Any Python from 3.10 to 3.14. With uv, connect to Claude
yourself (see "Connect to Claude" below).

Prefer a regular Windows installer or a macOS app, with no Python needed? Download it from
[GitHub Releases](https://github.com/zohoMatt/audio-notes/releases/latest). The installer also
connects Audio Notes to Claude Desktop for you.

> **macOS: start Audio Notes from Terminal, iTerm or the app, not from an IDE or from Claude.**
> macOS grants the permissions to the app that started Audio Notes. It won't grant System Audio
> Recording to an IDE or to Claude, so Audio Notes refuses to record there instead of recording
> silence. `audio-notes devices` shows which app the permissions go to.

On first start Audio Notes shows a short recording notice. On macOS it also explains its two
permissions, and macOS asks for **Microphone** and **System Audio Recording**. Allow both.

### 2. Open the panel

- **Windows:** the Audio Notes icon appears in the taskbar's notification area (click the `^` arrow
  if it is hidden). Click it to open the panel; right-click it for the full menu.
- **macOS:** click the pencil icon in the menu bar and choose **Open Panel…**.

The panel is a local page in your browser, served from your own computer: a live transcript and
your past sessions.

### 3. Start recording

Click **Start recording** in the panel (or in the tray / menu bar menu). The speech model
(`base.en` by default) is **downloaded once on first use** and cached; after that everything works
offline. The icon shows a "downloading" state meanwhile. Set `AUDIO_NOTES_MODEL` to pick another
faster-whisper model (for example `small.en`).

Lines from your microphone are labelled **Me**, lines from system audio **Them**.

### 4. Ask Claude

In Claude Desktop, click **+** in the message box, open **Connectors**, and make sure
**Audio Notes** is turned on. Then just ask, for example:

- "Summarize the last 10 minutes of the meeting."
- "What action items have been assigned to me so far?"
- "What did they say about the budget?"
- "List my past sessions and summarize yesterday's call."

The first time Claude uses an Audio Notes tool it asks for permission. Click **Allow** (or
**Always allow** so it doesn't ask again).

## Connect to Claude

1. **Quit Claude Desktop completely.** Windows: also quit it from its icon in the notification
   area. macOS: ⌘Q. Claude Desktop rewrites its config file while it runs and when it exits, so an
   entry added while it is open gets erased.
2. **Add Audio Notes to Claude's config:**
   - **Windows:** right-click the Audio Notes icon in the notification area and choose
     **Connect to Claude…**. (The Windows installer from GitHub Releases does this during setup.)
   - **macOS:** click the pencil icon in the menu bar and choose **Connect to Claude…**.
   - **Command line** (either platform):

     ```bash
     audio-notes setup claude                 # print the Claude Desktop entry and the `claude mcp add` command for Claude Code
     audio-notes setup claude --write         # merge it into Claude Desktop's config (asks first, makes a backup)
     audio-notes setup claude --write --yes   # same, without asking (exit code 3: Claude Desktop not installed)
     ```
3. **Start Claude Desktop.** Click **+** in the message box, open **Connectors**, and check that
   **Audio Notes** is listed and turned on.

The entry is called **Audio Notes** and points at the absolute path of the `audio-notes` program,
so it works even when Claude starts it with an incomplete PATH. Claude Desktop keeps its config in
`%APPDATA%\Claude\claude_desktop_config.json` (Windows; the Microsoft Store build uses
`%LOCALAPPDATA%\Claude-Data\claude_<id>\`, found automatically) or
`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS).

To disconnect, run `audio-notes clean` (it shows what it will remove and asks first).

## Usage

Claude gets four tools: `get_transcript`, `search_transcript`, `list_sessions`, `get_status`.
Sessions are named Stream001, Stream002, … (oldest first), so you can ask about "Stream007".

| Command | What it does |
|---|---|
| `audio-notes tray` | Start the tray / menu bar icon and the panel (`--no-tray`: panel only) |
| `audio-notes record` | Record without any UI; Ctrl+C stops (`--no-mic`: system audio only) |
| `audio-notes devices` | List audio devices (macOS: also the permission status and which app holds it) |
| `audio-notes sessions` | List past sessions |
| `audio-notes show [SESSION] [-n N] [-f]` | Show a transcript; `-f` follows it live |
| `audio-notes status` | Whether the recorder is running, and the current session |
| `audio-notes mcp` | Run the MCP server over stdio (Claude starts this) |
| `audio-notes setup claude [--write]` | Print or write Claude's MCP config |
| `audio-notes clean` | Remove Audio Notes from Claude Desktop / Claude Code (`--purge-data`: also the transcripts) |

Where transcripts are stored (set `AUDIO_NOTES_DATA_DIR` to use another folder):

| Platform | Transcripts | Log |
|---|---|---|
| Windows | `%APPDATA%\audio-notes\` | same folder |
| macOS | `~/Library/Application Support/Audio Notes/` | `~/Library/Logs/Audio Notes/` |

## What stays on your computer

- **Audio** is captured and transcribed on your CPU, and is never written to disk or sent anywhere.
- **Transcripts** are plain JSON Lines files on your disk (see above for where).
- **The panel** is served on `127.0.0.1` only, so other computers on your network can't open it.
- **Claude** talks to Audio Notes over stdio: Claude Desktop starts the `audio-notes` program on
  your computer, with no network port and no server in between. When you ask a question, the
  transcript lines Claude reads become part of that conversation and are sent to Anthropic like
  anything else you type to Claude. Nothing is sent until you ask.
- **The network** is used to download the speech model from Hugging Face on first use. When the
  model is loaded later, the download library still checks Hugging Face for a newer copy if you
  are online, and falls back to the cached model if you are not. There is no telemetry and no
  account.

## Legal notice: recording other people

Recording and transcribing conversations may require the consent of everyone involved, and the
rules differ by country and state (some require all parties to consent). You are solely
responsible for complying with the laws that apply to you and for telling participants when you
record meetings or calls. Do not use this tool to record people without their knowledge where the
law forbids it.

## Known limitations

- **Headphones recommended.** With speakers, the microphone can pick up the system audio again, so
  the same speech may appear twice (once as "Them", once as "Me").
- **English only.** Transcription is set to English; other languages come out as poor English
  text, even with a multilingual model.
- **Windows:** applications that open the audio device in **WASAPI exclusive mode** bypass the
  shared mixer; their audio is **not captured**.
- **macOS:** Apple Silicon only. System Audio Recording can't be granted when Audio Notes is
  started from an IDE or from Claude. Notifications appear under "Script Editor".

Source code, development notes and the installers:
[github.com/zohoMatt/audio-notes](https://github.com/zohoMatt/audio-notes)
