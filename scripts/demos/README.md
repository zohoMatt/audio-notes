# Visual demos

Small throwaway tools for checking single modules by eye. Each one serves a local HTTP page, bound
to 127.0.0.1 only; Ctrl+C stops it. Run them from the repository root:

| Module | Command | Address | What it shows |
|---|---|---|---|
| Capture | `uv run python scripts/demos/capture_demo.py` | http://127.0.0.1:8801 | System audio / microphone levels, a test tone, FileSource chunks. Windows only |
| Processing pipeline | `uv run python scripts/demos/processing_demo.py` | http://127.0.0.1:8802 | Press Start: waveform, VAD segments, line-by-line transcription, speed relative to real time. Uses `tests/fixtures` by default; choosing `base.en` the first time downloads the model |
| Store + MCP | `uv run python scripts/demos/store_mcp_demo.py` | http://127.0.0.1:8803 | A simulated two-person conversation being written, the `StoreReader` output, and the raw results of the real MCP tools. Uses a temporary data folder and never touches your real data or Claude's config |
| Tray + web panel | `uv run python scripts/demos/tray_web_demo.py` | http://127.0.0.1:8765 (with a token, printed in the terminal; double-clicking the tray icon also opens it) | The real `TrayApp` (with a fake recorder) and the real `PanelServer`: "Start recording" in the tray menu starts writing a simulated conversation, which the panel shows live with me/them separated. Shows the legal notice the first time. Uses a temporary data folder; `DEMO_NO_TRAY=1` runs the panel only |

The capture, processing and store demos use different ports and can run at the same time. The tray
demo uses 8765, the same port as the real panel, so don't run it next to the real app.

These scripts are not product code and do not run in CI. They depend on the current interfaces and
may need updating when those change.
