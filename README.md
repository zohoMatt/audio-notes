<div align="center">

<img src="docs/icon.png" alt="Audio Notes" width="180">

# Audio Notes

### Your meetings, transcribed on your computer. Ask Claude about them.

**Open source. Fully local. Works offline. Secure by default.**<br>
System audio + microphone → Whisper on your CPU → Claude, over MCP. Audio never leaves your machine.

[![Download](https://img.shields.io/badge/Download-Windows%20%7C%20macOS-312E81?style=for-the-badge&logo=github&logoColor=white)](https://github.com/zohoMatt/audio-notes/releases/latest)
[![Quick start](https://img.shields.io/badge/Quick%20start-4%20steps-F472B6?style=for-the-badge)](#quick-start)

![Windows](https://img.shields.io/badge/Windows-10%20%7C%2011-0078D6?logo=windows&logoColor=white)
![macOS](https://img.shields.io/badge/macOS-14.2%2B%20Apple%20Silicon-000000?logo=apple&logoColor=white)
![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![MCP](https://img.shields.io/badge/Claude-MCP%20server-D97757)
![100% local](https://img.shields.io/badge/transcription-100%25%20local-16A34A)
![License: MIT](https://img.shields.io/badge/license-MIT-blue)

</div>

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
become part of that conversation. See [What stays on your computer](#what-stays-on-your-computer).

| | Supported |
|---|---|
| Windows | 10 and 11, 64-bit |
| macOS | 14.2 (Sonoma) or later, Apple Silicon (M1 or newer). Intel Macs are not supported |
| Linux | Not supported |

## Quick start

### 1. Install

#### Windows

Download `Audio-Notes-<version>-windows-x64-setup.exe` from
[GitHub Releases](https://github.com/zohoMatt/audio-notes/releases) and run it (no Python needed).
It adds a Start Menu entry, connects Audio Notes to Claude Desktop, and can optionally add the
`audio-notes` command to your PATH.

> **The installer is not code-signed**, so:
>
> - Windows SmartScreen will likely warn you. Click "More info", then "Run anyway".
> - Windows 11 with **Smart App Control** enabled may block unsigned programs outright, with no
>   override. In that case install with uv instead (below).
> - Antivirus products occasionally flag PyInstaller-built programs as false positives.
> - To verify your download, compare its SHA256
>   (`Get-FileHash .\Audio-Notes-<version>-windows-x64-setup.exe`) with the hash in the release
>   notes.

#### macOS

Download `Audio-Notes-<version>-macos-arm64.dmg` from
[GitHub Releases](https://github.com/zohoMatt/audio-notes/releases) (starting with the next
release), open it and drag **Audio Notes** into **Applications**. Open it from Applications, not
from the disk image.

> **The app is not yet notarized**, so macOS blocks the first launch. Open **System Settings >
> Privacy & Security**, scroll down and click **Open Anyway**. To verify your download, compare
> `shasum -a 256 Audio-Notes-<version>-macos-arm64.dmg` with the hash in the release notes.

On first launch Audio Notes shows a short recording notice, explains its two permissions, and
macOS asks for **Microphone** and **System Audio Recording**. Allow both. Audio Notes lives in the
menu bar at the top right and has no Dock icon.

#### Either platform: uv (developers)

```bash
uv tool install git+https://github.com/zohoMatt/audio-notes
audio-notes --version
audio-notes tray
```

Install [uv](https://docs.astral.sh/uv/) first if you don't have it; it manages Python for you. On
macOS this compiles the capture helper, so it needs the Command Line Tools
(`xcode-select --install`). With uv, connect to Claude yourself (see
[Connect to Claude](#connect-to-claude)).

> **macOS: start Audio Notes from Terminal, iTerm or the app, not from an IDE or from Claude.**
> macOS grants the permissions to the app that started Audio Notes. It won't grant System Audio
> Recording to an IDE or to Claude, so Audio Notes refuses to record there instead of recording
> silence. `audio-notes devices` shows which app the permissions go to.

### 2. Open the panel

- **Windows:** start **Audio Notes** from the Start Menu. The icon
  <img src="docs/tray-icon.png" alt="Audio Notes icon" width="20" height="20"> appears in the
  taskbar's notification area (click the `^` arrow if it is hidden). Click it to open the panel;
  right-click it for the full menu.
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
2. **Add Audio Notes to Claude's config**, in one of these ways:
   - **Windows installer:** keep the "Connect to Claude Desktop" option ticked (the default); setup
     does it for you.
   - **From the app:** choose **Connect to Claude…** in the tray / menu bar menu. Use this on macOS,
     after skipping the installer option, or after installing Claude Desktop later. On macOS, move
     Audio Notes into Applications first; it won't connect while running from the disk image.
   - **From the command line** (uv installs, or any install with the `audio-notes` command):

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

To disconnect, run `audio-notes clean` (it shows what it will remove and asks first). Uninstalling
does not touch Claude's config.

## Usage

Claude gets four tools: `get_transcript`, `search_transcript`, `list_sessions`, `get_status`.
Sessions are named Stream001, Stream002, … (oldest first), so you can ask about "Stream007".

Command line:

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

Where the command is:

- **Windows installer:** `audio-notes` if you ticked "Add to PATH", otherwise
  `"C:\Program Files\Audio Notes\audio-notes.exe"` (or wherever you installed it).
- **macOS app:** `"/Applications/Audio Notes.app/Contents/MacOS/audio-notes"`.
- **uv:** `audio-notes`.

Where transcripts are stored (set `AUDIO_NOTES_DATA_DIR` to use another folder):

| Install | Transcripts | Log |
|---|---|---|
| Windows installer | `data` folder next to the program | same folder |
| Windows, uv / pip | `%APPDATA%\audio-notes\` | same folder |
| macOS (app or uv) | `~/Library/Application Support/Audio Notes/` | `~/Library/Logs/Audio Notes/` |

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
  shared mixer; their audio is **not captured**. The installer is not code-signed.
- **macOS:** Apple Silicon only. The app is not yet notarized. System Audio Recording can't be
  granted when Audio Notes is started from an IDE or from Claude. Notifications appear under
  "Script Editor".

## Development

```bash
uv sync
uv run pytest
```

`uv sync` uses Python 3.12, pinned in `.python-version` (the version CI runs on macOS).
`uv tool install` works with any Python from 3.10 to 3.14. On macOS, `uv sync` also compiles the
Swift capture helper in `macos/capture` (rebuild it after Swift changes with
`swift build -c release --package-path macos/capture`).

**macOS: keep the virtual environment out of iCloud.** If the checkout is in `~/Documents` or
`~/Desktop` with iCloud Drive's "Desktop & Documents" sync on, iCloud marks `.venv` as hidden a
few seconds after it is created, and Python skips hidden `.pth` files. The editable install then
stops working: subprocesses and the MCP / end-to-end tests fail with
`No module named 'audio_notes'` (`ls -lO .venv/lib/python*/site-packages/*.pth` shows `hidden`).
Clone the repository somewhere iCloud doesn't sync, or keep the environment elsewhere, for example
in `~/.zshrc`:

```bash
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/audio-notes"
```

`chflags -R nohidden .venv` fixes a broken environment until iCloud hides it again.

Building and releasing the Windows installer and the macOS app: see
[installer/RELEASING.md](installer/RELEASING.md).

### Running from source

Everything runs from the repository without building or installing the app:

```bash
uv run audio-notes tray              # tray / menu bar icon + web panel
uv run audio-notes tray --no-tray    # web panel only (real recorder); prints the panel URL, Ctrl+C stops
uv run audio-notes record --no-mic   # record system audio without any UI; Ctrl+C stops
uv run audio-notes sessions          # then: show, status
```

On macOS run these from Terminal or iTerm (see the note under [Install](#either-platform-uv-developers)).

Run the whole pipeline without speakers or a microphone, from the test recordings:

```bash
uv run audio-notes record --them-file tests/fixtures/them_budget.wav --me-file tests/fixtures/me_question.wav --fast
```

Point Claude Code at the source tree instead of an installed build (restart the Claude Code
session to pick up code changes):

```bash
claude mcp add audio-notes -- uv --directory /path/to/audio-notes run audio-notes mcp
```

`tray --no-tray` and `record` skip the first-run recording notice. The demos in
[scripts/demos](scripts/demos/README.md) show single modules with fake data in a temporary folder;
`DEMO_NO_TRAY=1 uv run python scripts/demos/tray_web_demo.py` (PowerShell:
`$env:DEMO_NO_TRAY=1; uv run python scripts/demos/tray_web_demo.py`) runs the panel with a
simulated conversation.

Environment variables that help while developing:

| Variable | Effect |
|---|---|
| `AUDIO_NOTES_DATA_DIR` | Keep transcripts in another folder, away from your real ones |
| `AUDIO_NOTES_WEB_PORT` | Panel port (default 8765); lets a source run sit next to an installed one |
| `AUDIO_NOTES_MODEL` | ASR model, e.g. `tiny.en` for faster downloads and transcription |
| `AUDIO_NOTES_VAD_SILENCE_MS`, `AUDIO_NOTES_VAD_MAX_S` | When a segment is cut and sent to ASR |
| `AUDIO_NOTES_CLAUDE_CONFIG` | Claude Desktop config file used by `setup claude --write` and `clean` |
| `AUDIO_NOTES_CAPTURE_HELPER` | macOS: path of the Swift capture helper to use |

### Clean up after local testing

Testing leaves the app, its permissions, Claude entries, config backups and data behind. One script
per platform removes all of it, so the next run behaves like a first install. Quit Claude Desktop
completely first (it rewrites its config while running, and the scripts skip that config if it is
open), and restart Claude Code sessions afterwards.

**Windows** (PowerShell, from the repository):

```powershell
.\scripts\clean_dev_windows.ps1 -DryRun   # show what would be done
.\scripts\clean_dev_windows.ps1           # do it (asks once; -Yes skips the question)
```

It stops running copies, uninstalls the installed app silently, removes a `uv tool` install, the
Audio Notes entry from every Claude Desktop config, our `claude_desktop_config.json.bak-*`
backups, the Claude Code registrations (user scope, every project's local scope, project
`.mcp.json`) and the transcripts folders. `-PurgeModels` also deletes the downloaded speech models.

**macOS** (from the repository):

```bash
scripts/clean_dev_mac.sh --dry-run   # show what would be done
scripts/clean_dev_mac.sh             # do it (asks once; --yes skips the question)
```

The same, plus what only exists on a Mac: it quits the app and its capture helpers, ejects a
mounted Audio Notes disk image, unregisters and deletes installed copies of `Audio Notes.app`,
deletes `~/Library/Application Support/Audio Notes` and `~/Library/Logs/Audio Notes`, and resets
the Microphone and System Audio Recording permissions of Audio Notes and of the apps that started
it during development (Terminal, iTerm, Claude Code). `--keep-terminal-permissions` leaves those
apps' permissions alone; `--purge-models` deletes the speech models.

Both scripts call `uv run audio-notes clean`, which you can also run on its own for just the
Claude entries (`--purge-data` adds the transcripts, `--keep-backups` keeps the backups).
