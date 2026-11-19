# Parallel development tracks

> **Status: the parallel phase is over.** Tracks A–E and the integration (`recorder.py`, `cli/run.py`, E2E tests) are all done and merged into `main`. The content below is kept as a historical record and a reference for module ownership. Rules such as "do not commit" applied only to that parallel phase.

The skeleton (`pyproject.toml`, each package's `__init__.py`, the interface contracts, the CLI registration mechanism) is in place. Each track edits only the files it owns and collaborates through **frozen interfaces**, without interfering with the others. For design background, see `REQUIREMENTS.md` and `ARCHITECTURE.md`.

## General rules

1. **Only change files you own** (see the table below). If a file owned by someone else needs a change, do not touch it; state it in the final report.
2. **Do not edit**: `pyproject.toml`, `src/audio_notes/cli/__init__.py`, `capture/base.py`, `asr/base.py`, `store/models.py`, `config.py`, `paths.py`. If you need a new dependency or an interface change, raise it in the final report; the main session handles it.
3. **Do not `git commit` and do not switch branches.** All tracks share the same working directory.
4. Test files use each track's own file-name prefix (see the table). In tests, the data directory always points to `tmp_path` through the environment variable `AUDIO_NOTES_DATA_DIR`; never touch the real `%APPDATA%`.
5. Heavy dependencies (faster-whisper, PyAudioWPatch, pystray) are imported only in the modules that need them. `store/`, `mcp_server.py`, `cli/inspect.py` and `cli/setup.py` must not import them.
6. Do not use the torch / silero-vad pip packages (they pull in torch). VAD goes through onnxruntime.
7. Run tests: `uv run pytest` (skips `hardware` by default).

## Tracks and file ownership

| Track | Scope | Owned files | Test prefix |
|---|---|---|---|
| **A Capture** | WASAPI loopback and microphone, `FileSource` for file playback, `devices` command | `src/audio_notes/capture/win_wasapi.py`, `capture/file_source.py`, `cli/devices.py`, `scripts/dump_devices.py` | `tests/test_capture_*.py` |
| **B Transcription** | Resampling, VAD segmentation, runner orchestration, faster-whisper engine, test fixture generation | `src/audio_notes/processing/*`, `asr/faster_whisper_engine.py`, `scripts/make_fixtures.py`, `tests/fixtures/*` | `tests/test_processing_*.py`, `tests/test_asr_*.py` |
| **C Storage and MCP** | `SessionWriter`, `StoreReader`, MCP tools, `sessions/show/status`, `setup claude` | `src/audio_notes/store/writer.py`, `store/reader.py`, `mcp_server.py`, `cli/inspect.py`, `cli/setup.py` | `tests/test_store_*.py`, `tests/test_mcp_*.py`, `tests/test_cli_inspect_*.py` |
| **D Tray and web** (second batch) | pystray tray and state machine, Starlette panel | `src/audio_notes/tray/*`, `web/*` | `tests/test_tray_*.py`, `tests/test_web_*.py` |
| **E Release** (second batch) | CI, release workflow, installer scripts | `.github/workflows/*`, `installer/*` | — |
| **Integration** (last) | `tray`/`record` in `cli/run.py`, software E2E tests | `cli/run.py`, `tests/test_e2e_*.py` | — |

## Contracts (frozen)

- `capture/base.py`: `AudioChunk`, `AudioSource.start(on_chunk, origin)` / `stop()`. `t` is in seconds relative to the shared session origin; all streams share the same time base.
- `asr/base.py`: `Transcriber.transcribe(samples)`; input is 16 kHz mono float32.
- `store/models.py`: `Segment` (with JSONL serialization), `SessionInfo`, `Status`, and two Protocols: `TranscriptSink` (written by processing) and `TranscriptReader` (read by CLI / MCP / Web).
- Tracks depend on each other only through these interfaces: B tests with a fake `AudioSource` and an in-memory `TranscriptSink`; D tests with a fake `TranscriptReader`; C does not depend on A or B.
- CLI: each command module exposes `register(app)` and implements its own commands; `cli/__init__.py` already registers all modules.

## Data format

`%APPDATA%\audio-notes\sessions\<YYYY-MM-DD_HH-MM-SS>.jsonl`, one `Segment` per line. `status.json` is written by the writer and carries a heartbeat. `seq` increments from 1 and doubles as the read cursor.
