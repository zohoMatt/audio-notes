# 并行开发分工

骨架（`pyproject.toml`、各包的 `__init__.py`、接口契约、CLI 注册机制）已就位。各轨道只编辑自己拥有的文件，通过**已冻结的接口**协作，互不干涉。设计背景见 `REQUIREMENTS.md` 和 `ARCHITECTURE.md`。

## 通用规则

1. **只改自己拥有的文件**（见下表）。需要别人拥有的文件有改动时，不要动手，在最终报告里写明。
2. **不要编辑**：`pyproject.toml`、`src/audio_notes/cli/__init__.py`、`capture/base.py`、`asr/base.py`、`store/models.py`、`config.py`、`paths.py`。需要新增依赖或修改接口，在最终报告里提出，由主会话统一处理。
3. **不要 `git commit`，不要切换分支**，所有轨道共用同一个工作目录。
4. 测试文件用各轨道自己的文件名前缀（见表），测试中数据目录一律通过环境变量 `AUDIO_NOTES_DATA_DIR` 指向 `tmp_path`，不碰真实的 `%APPDATA%`。
5. 重依赖（faster-whisper、PyAudioWPatch、pystray）只在需要它们的模块内导入。`store/`、`mcp_server.py`、`cli/inspect.py`、`cli/setup.py` 不得导入它们。
6. 不使用 torch / silero-vad pip 包（会引入 torch）。VAD 走 onnxruntime。
7. 运行测试：`uv run pytest`（默认跳过 `hardware`）。

## 轨道与文件归属

| 轨道 | 内容 | 拥有的文件 | 测试前缀 |
|---|---|---|---|
| **A 采集** | WASAPI loopback 与麦克风、回放文件的 `FileSource`、`devices` 命令 | `src/audio_notes/capture/win_wasapi.py`、`capture/file_source.py`、`cli/devices.py`、`scripts/dump_devices.py` | `tests/test_capture_*.py` |
| **B 转写** | 重采样、VAD 分段、runner 编排、faster-whisper 引擎、测试素材生成 | `src/audio_notes/processing/*`、`asr/faster_whisper_engine.py`、`scripts/make_fixtures.py`、`tests/fixtures/*` | `tests/test_processing_*.py`、`tests/test_asr_*.py` |
| **C 存储与 MCP** | `SessionWriter`、`StoreReader`、MCP 工具、`sessions/show/status`、`setup claude` | `src/audio_notes/store/writer.py`、`store/reader.py`、`mcp_server.py`、`cli/inspect.py`、`cli/setup.py` | `tests/test_store_*.py`、`tests/test_mcp_*.py`、`tests/test_cli_inspect_*.py` |
| **D 托盘与 Web**（第二批） | pystray 托盘与状态机、Starlette 面板 | `src/audio_notes/tray/*`、`web/*` | `tests/test_tray_*.py`、`tests/test_web_*.py` |
| **E 发布**（第二批） | CI、release 工作流、安装包脚本 | `.github/workflows/*`、`installer/*` | — |
| **集成**（最后） | `cli/run.py` 的 `tray`/`record`、软件 E2E 测试 | `cli/run.py`、`tests/test_e2e_*.py` | — |

## 契约（已冻结）

- `capture/base.py`：`AudioChunk`、`AudioSource.start(on_chunk, origin)` / `stop()`。`t` 为相对共享 session 原点的秒数，各路共用同一时间基准。
- `asr/base.py`：`Transcriber.transcribe(samples)`，输入 16 kHz 单声道 float32。
- `store/models.py`：`Segment`（含 JSONL 序列化）、`SessionInfo`、`Status`，以及两个 Protocol：`TranscriptSink`（processing 写入）、`TranscriptReader`（CLI / MCP / Web 读取）。
- 轨道之间的依赖只通过这些接口：B 用假的 `AudioSource` 和内存版 `TranscriptSink` 做测试；D 用假的 `TranscriptReader` 做测试；C 不依赖 A、B。
- CLI：每个命令模块暴露 `register(app)`，命令各自实现；`cli/__init__.py` 已注册全部模块。

## 数据格式

`%APPDATA%\audio-notes\sessions\<YYYY-MM-DD_HH-MM-SS>.jsonl`，每行一个 `Segment`；`status.json` 由 writer 写入并带心跳。`seq` 从 1 起递增，兼作读取 cursor。
