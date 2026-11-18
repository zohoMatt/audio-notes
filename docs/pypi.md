<!-- The project description on PyPI (pyproject.toml `readme`). The GitHub README is README.md.
     PyPI resolves no relative links: use absolute URLs only. -->

<img src="https://raw.githubusercontent.com/zohoMatt/audio-notes/main/docs/icon.png" alt="Audio Notes" width="120">

# Audio Notes

**Your meetings, transcribed on your PC. Ask Claude about them.**

A lightweight Windows tray tool that captures **system audio** (what you hear) and your
**microphone**, transcribes both **locally** with
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) on the CPU, and lets Claude read the
transcript through an [MCP](https://modelcontextprotocol.io) server. Audio never leaves your
machine; Claude sees only the transcript lines it reads when you ask, as part of that
conversation. No telemetry, no account.

Prefer a regular Windows installer or a macOS app (no Python needed)? Get it from the
[GitHub Releases page](https://github.com/zohoMatt/audio-notes/releases/latest).

## Install

```powershell
uv tool install audio-notes
audio-notes --version
```

([uv](https://docs.astral.sh/uv/) manages Python for you; `pipx install audio-notes` works too.)
Python 3.10+. Windows, and (preview) macOS 14.2+ on Apple Silicon: the macOS wheel ships
the compiled capture helper. On a Mac, run it from a terminal app, which is then the app that
asks for microphone and system audio recording permission.

## Connect to Claude

Quit Claude Desktop completely (also from its tray icon) first: it rewrites its config when it
exits. Then:

```powershell
audio-notes setup claude --write   # adds Audio Notes to Claude Desktop's config (asks first)
audio-notes setup claude           # only prints the config and the `claude mcp add` command for Claude Code
```

Start Claude Desktop again, and make sure **Audio Notes** is on under **+ → Connectors**.

## Use

Run `audio-notes tray`, click the tray icon to open the local panel, and press **Start
recording**. The speech model (`base.en`; set `AUDIO_NOTES_MODEL` for another faster-whisper
model) is downloaded once on first use. Then ask Claude things like "Summarize the last 10
minutes" or "What did they say about the budget?".

Claude gets four tools: `get_transcript`, `search_transcript`, `list_sessions`, `get_status`.

| Command | What it does |
|---|---|
| `audio-notes tray` | Start the tray app and the local web panel |
| `audio-notes record` | Record without UI; Ctrl+C to stop |
| `audio-notes devices` | List audio devices |
| `audio-notes sessions` | List past sessions |
| `audio-notes show [-n N] [-f]` | Show a transcript, `-f` to follow |
| `audio-notes status` | Is the recorder running, current session |
| `audio-notes mcp` | Run the MCP server over stdio (Claude launches this) |
| `audio-notes setup claude` | Print or write Claude's MCP config |
| `audio-notes clean` | Remove Audio Notes from Claude Desktop / Claude Code |

Transcripts are stored under `%APPDATA%\audio-notes\` (set `AUDIO_NOTES_DATA_DIR` to change it).

## Legal notice: recording other people

Recording and transcribing conversations may require the consent of everyone involved, and the
rules differ by country and state. You are solely responsible for complying with the laws that
apply to you and for telling participants when you record meetings or calls.

## Known limitations

- **Headphones recommended.** With speakers, the microphone can pick up the system audio again,
  so the same speech may appear twice.
- Applications using **WASAPI exclusive mode** bypass the shared mixer and are not captured.
- macOS support is a preview: Apple Silicon only, macOS 14.2 or later.

Full documentation, screenshots and the installer:
[github.com/zohoMatt/audio-notes](https://github.com/zohoMatt/audio-notes)
