<div align="center">

<img src="docs/icon.png" alt="Audio Notes" width="180">

# Audio Notes

### Your meetings, transcribed on your PC. Ask Claude about them.

**System audio + microphone → local Whisper transcript → Claude, over MCP.**<br>
Nothing is uploaded. Audio never leaves your machine.

[![Download for Windows](https://img.shields.io/badge/Download-Windows%20installer-312E81?style=for-the-badge&logo=windows&logoColor=white)](https://github.com/zohoMatt/audio-notes/releases/latest)
[![Quick start](https://img.shields.io/badge/Quick%20start-4%20steps-F472B6?style=for-the-badge)](#quick-start)

![Windows](https://img.shields.io/badge/platform-Windows-0078D6?logo=windows&logoColor=white)
![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![MCP](https://img.shields.io/badge/Claude-MCP%20server-D97757)
![100% local](https://img.shields.io/badge/transcription-100%25%20local-16A34A)
![License: MIT](https://img.shields.io/badge/license-MIT-blue)

</div>

---

A lightweight Windows tray tool that captures **system audio** (what you hear) and your **microphone**,
transcribes both **locally** with [faster-whisper](https://github.com/SYSTRAN/faster-whisper) on the CPU,
and lets Claude read the transcript through an [MCP](https://modelcontextprotocol.io) server.
Nothing is uploaded: audio never leaves your machine. Transcripts are stored in the `data` folder next to
the program when you use the installer or the packaged build (so the tray, the command line and the MCP
server always agree on where they are), and under `%APPDATA%\audio-notes\` when you install with
pip / uv. Set `AUDIO_NOTES_DATA_DIR` to put them somewhere else.

## Quick start

### 1. Install

Download `audio-notes-setup-<version>.exe` from the project's GitHub Releases page and run it
(no Python needed). It adds a Start Menu entry, connects Audio Notes to Claude Desktop, and can
optionally start with Windows and add the `audio-notes` command to your PATH.

> **Notes on the installer**
>
> The installer is **not code-signed**, so:
>
> - Windows SmartScreen will likely warn you. Click "More info", then "Run anyway".
> - Windows 11 with **Smart App Control** enabled may block unsigned programs outright, with no
>   override. In that case install with uv instead (below).
> - Antivirus products occasionally flag PyInstaller-built programs as false positives.
> - To verify your download, compare its SHA256 (`Get-FileHash .\audio-notes-setup-<version>.exe`)
>   with the hash printed in the release notes on the GitHub Releases page.
>
> **Alternative: uv (developers).** Not affected by any of the above:
>
> ```powershell
> uv tool install audio-notes
> audio-notes --version
> ```
>
> Install [uv](https://docs.astral.sh/uv/) first if you don't have it. uv manages Python for you.
> With uv, connect to Claude yourself (see [Connect to Claude](#connect-to-claude)).

### 2. Open the panel

Start **Audio Notes** from the Start Menu (or `audio-notes tray`). The icon
<img src="docs/tray-icon.png" alt="Audio Notes icon" width="20" height="20"> appears in the
taskbar's notification area (click the `^` arrow if it is hidden). Click it to open the Audio
Notes panel, a local page in your browser served from your own machine. Right-click the icon for
the full menu.

### 3. Start recording

Click **Start recording** in the panel (or in the tray menu). The speech model (`base.en` by
default) is **downloaded once on first use** and cached; after that everything works offline.
The tray shows a "downloading" state while this happens. Set `AUDIO_NOTES_MODEL` to pick another
faster-whisper model (for example `small.en`).

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

With the Windows installer there is nothing to do: the "Connect to Claude Desktop" option is
ticked by default and adds audio-notes to Claude Desktop's config during setup. Restart Claude
Desktop afterwards. If you skipped it, or installed Claude Desktop later, use **Connect to Claude**
in the tray menu. Uninstalling does not touch Claude's config; remove the `audio-notes` entry from
`%APPDATA%\Claude\claude_desktop_config.json` yourself if you want it gone.

Advanced / `uv` installs, from the command line:

```powershell
audio-notes setup claude                 # prints the config / `claude mcp add` command
audio-notes setup claude --write         # merges it into Claude Desktop's config (asks first)
audio-notes setup claude --write --yes   # same, without asking (exit code 3: Claude Desktop not installed)
```

The configuration uses the absolute path to the `audio-notes` executable, so it works even when
Claude's child processes have an incomplete PATH. **Quit Claude Desktop completely (also from the
tray) before running `--write`, then start it again**: it rewrites its config file on exit and would
erase the entry. The Microsoft Store build keeps its config under
`%LOCALAPPDATA%\Claude-Data\claude_<id>\`; the command finds it automatically.

## Usage

Claude gets four tools: `get_transcript`, `search_transcript`, `list_sessions`, `get_status`.

Command line:

| Command | What it does |
|---|---|
| `audio-notes tray` | Start the tray daemon |
| `audio-notes record` | Record without UI; Ctrl+C to stop |
| `audio-notes devices` | List audio devices |
| `audio-notes sessions` | List past sessions |
| `audio-notes show [-n N] [-f]` | Show a transcript, `-f` to follow |
| `audio-notes status` | Is the daemon running, current session |
| `audio-notes mcp` | Run the MCP server over stdio (Claude launches this) |
| `audio-notes setup claude` | Print or write Claude's MCP config |

## Legal notice: recording other people

Recording and transcribing conversations may require the consent of everyone involved, and the
rules differ by country and state (some require all parties to consent). You are solely
responsible for complying with the laws that apply to you and for telling participants when you
record meetings or calls. Do not use this tool to record people without their knowledge where the
law forbids it.

## Known limitations

- **Headphones recommended.** With speakers, the microphone can pick up the system audio again, so
  the same speech may appear twice (once as "them", once as "me"). Some laptop microphones with
  built-in echo cancellation reduce this, but don't count on it.
- Applications that open the audio device in **WASAPI exclusive mode** bypass the shared mixer;
  their audio is **not captured**.
- Windows only for now.
- The installer is unsigned.

## Development

```powershell
uv sync
uv run pytest
```

Releasing: see [installer/RELEASING.md](installer/RELEASING.md).
