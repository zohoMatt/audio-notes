# audio-notes 需求文档（MVP）

## 1. 目标

一个轻量的 Windows 托盘小工具（后续扩展 macOS）：实时捕获系统音频和麦克风，本地转写为英文文字，并通过 MCP 让 Claude 按需读取转写内容，作为对话上下文。

## 2. 已确认的决策

| 项 | 决策 |
|---|---|
| 使用场景 | 线上会议 + 视频/网课/直播，通用系统音频，麦克风可选 |
| ASR | 本地离线，不上传音频 |
| 语言 | 英文 |
| Claude 交互 | MCP 拉取（Claude 按需调用工具），MVP 不做主动推送 |
| 说话人 | 仅区分「我 / 对方」，用双通道实现 |
| 存储 | 每场会议保存为本地文件 |
| 技术栈 | Python |
| 合规 | 首次运行时提示法律风险即可，不做复杂机制 |
| 界面 | 托盘图标 + 菜单；实时转写查看用本地 Web 面板（浏览器打开），无原生主窗口 |

## 3. 功能需求

### 3.1 音频采集
- **F1** 通过 WASAPI loopback 捕获系统输出音频（标记为「对方」）。
- **F2** 可选捕获默认麦克风（标记为「我」），在菜单中可开关。
- **F3** 两路音频独立处理，不混音，以保证说话人标签准确。
- **F4** 采集层抽象为接口，便于后续加入 macOS 实现（ScreenCaptureKit）。

### 3.2 转写
- **F5** 使用本地模型（候选：faster-whisper 或 whisper.cpp 的 small/base 英文模型），分段（VAD）转写。MVP 仅使用 CPU 推理（int8 量化），不依赖 GPU。
- **F5a** 推理设备（CPU / GPU）与模型档位做成配置项，MVP 固定为 CPU，GPU 切换与设置入口列入第二阶段。
- **F6** 仅保存 final 结果，不保存 partial。
- **F7** 每段包含：序号、起止时间戳、说话人（me / them）、文本。
- **F8** 转写延迟目标：一句话结束后约 5 秒内可被读取（待实测）。

### 3.3 存储
- **F9** 每次开始录制创建一个会话，写入 `transcripts/<日期时间>.jsonl`，一行一段。
- **F10** 会话结束时附带生成一份可读的 `.md`。
- **F11** 音频本身不落盘，仅保存文字。

### 3.4 MCP 服务
- **F12** 提供 MCP server（stdio 方式，供 Claude 桌面端 / Claude Code 配置）。
- **F13** 工具：
  - `get_transcript(since_cursor?, last_n_minutes?)`：增量读取，返回新的 cursor。
  - `search_transcript(query)`：关键词检索。
  - `list_sessions()`：列出历史会话。
  - `get_status()`：当前是否在录制、当前会话 ID、已记录段数。
- **F14** 滚动摘要（`get_summary`）不在 MVP 内，列入第二阶段。

### 3.5 托盘界面
- **F15** 图标有三种状态：空闲、录制中、出错。
- **F16** 菜单：开始/暂停、切换麦克风、打开面板（见 F28）、打开转写目录、连接到 Claude（见 F22）、退出。
- **F17** 首次运行弹出一次性提示：录制他人声音前请确认符合当地法律并告知参会者，用户确认后不再提示。

### 3.6 安装与分发
- **F18** 发布为 PyPI 包 `audio-notes`，提供 console script `audio-notes`；平台相关依赖（如 PyAudioWPatch）使用环境标记 `sys_platform == "win32"`。
- **F19** 开发者安装路径：`uv tool install audio-notes`（uv 自动管理 Python，依赖均为预编译 wheel，无需手动配置环境）。
- **F20** 普通用户安装路径：Windows 安装包（PyInstaller **onedir** + Inno Setup），双击安装，无需预装 Python。
  - 托盘、MCP、CLI 共用同一个 `audio-notes.exe`，以子命令区分。
  - 不使用 onefile 模式（每次启动需解压，会拖慢 Claude 拉起 MCP 进程）。
  - 安装器：创建开始菜单项；可选开机自启；可选加入 PATH。
- **F21** 模型首次运行时下载（安装包不内置），托盘显示"下载中"状态；下载完成后可完全离线使用。同时提供 `audio-notes model download` 预下载（后续）。
- **F22** 托盘菜单"连接到 Claude"：调用 `setup claude` 写入 Claude 的 MCP 配置，写入前必须弹窗确认；配置中使用 `audio-notes` 可执行文件的**绝对路径**（Claude 桌面端子进程 PATH 可能不完整）。CLI 的 `setup claude` 默认只打印配置，加 `--write` 才写入。
- **F23** CI/CD（GitHub Actions）：push/PR 触发 Windows 上的 pytest；推送 `v*` 标签触发构建，依次发布 TestPyPI、PyPI（使用 Trusted Publishing，PyPI 发布需手动批准），并构建安装包挂到 GitHub Releases。版本号由 git 标签生成（hatch-vcs）。

- **F33** 分发渠道优先级：MVP 以 `uv tool install` / `pip install` 为主要推荐渠道（不会触发 SmartScreen 的下载拦截）；Windows 安装包作为附加渠道。
- **F34** 防误报与拦截缓解（MVP 必做）：
  - PyInstaller 使用 onedir，不使用 UPX 等压缩。
  - 安装包只在 GitHub Actions 上构建；GitHub Release 说明中附 SHA256 校验值。
  - README 与发布说明写明：未签名程序会触发 SmartScreen（"更多信息 → 仍要运行"）；开启 Smart App Control 的 Windows 11 可能直接拦截未签名程序，没有放行选项，此时建议改用 pip/uv 安装。
  - 每次发布后向 Microsoft Defender 及主要杀毒厂商提交误报申诉（流程写入发布说明）。
  - 视误报情况再评估自行编译 PyInstaller 引导程序。
- **F35** 代码签名（MVP 不做，列为触发条件）：当需要面向非技术用户分发时再评估。候选方案：Microsoft Trusted Signing（有地域与申请者身份限制，需先确认资格）、传统 OV 证书、Microsoft Store（MSIX，由商店签名，但需按商店要求打包与审核）。价格与政策以官方页面为准。

### 3.7 命令行（CLI）
- **F24** 单一入口 `audio-notes`（亦可 `python -m audio_notes`），MVP 子命令：
  - `tray`：启动托盘守护进程。
  - `mcp`：启动 MCP server（stdio）。
  - `record`：无界面前台录制，Ctrl+C 结束。
  - `devices`：列出音频设备（loopback / 麦克风）。
  - `sessions`：列出历史会话。
  - `show [会话] -n N -f`：查看转写，`-f` 持续跟随。
  - `status`：守护进程是否运行、当前会话。
  - `setup claude`：输出（`--write` 时写入）Claude 的 MCP 配置，见 F22。
  - `--version`。
- **F25** 重依赖懒加载：`mcp`、`sessions`、`show`、`status`、`--help` 不得导入 ASR 与音频采集依赖，保证启动快。
- **F26** 使用 Typer 实现。
- **F27** 后续再加：`export`（导出 md）、`model download`、`doctor`（自检设备/模型/权限）。

### 3.8 本地 Web 面板
- **F28** 托盘进程内启动本地 HTTP 服务，仅绑定 `127.0.0.1`，端口可配置；托盘菜单"打开面板"用默认浏览器打开。
- **F29** 页面（MVP 只读）：实时转写（SSE 推送，区分 me/them，自动滚动）、会话列表与历史查看、录制状态。
- **F30** 技术：Starlette + 原生 HTML/JS，无前端构建步骤，不引入 Node；页面数据一律经 `store.reader` 读取，不直接依赖转写流水线。
- **F31** 安全：仅监听回环地址；校验 Host 头；不开放 CORS；URL 带启动时生成的随机 token（由托盘打开时附带），防止其他网页通过 DNS rebinding 读取转写内容。
- **F32** 面板中的设置编辑（CPU/GPU、模型档位等）不在 MVP 内。

## 4. 非功能需求

- **轻量**：空闲时 CPU 接近 0；录制时 CPU 占用目标低于一个核心的 50%（base 模型，待实测）。
- **隐私**：不联网即可完整使用；除 MCP 返回给用户本人的 Claude 外，不向任何服务发送数据。
- **稳定**：音频设备切换（耳机插拔）时不崩溃，自动重连默认设备。
- **平台**：MVP 仅 Windows 10/11（x64）；macOS 13+ 列入第二阶段。Windows ARM 设备的依赖 wheel 可用性待验证。
- **运行环境**：
  - Python 3.10+（建议 3.11/3.12；3.13 上部分依赖 wheel 可能滞后，M1 实测）。使用安装包时无需预装 Python。
  - 内存：`base.en` 约数百 MB，`small.en` 约 1 GB 量级（M2 实测）。磁盘：模型约 150–500 MB，加依赖总计不到 1 GB。
  - 网络：仅首次下载模型时需要。
  - 权限：无需管理员；需在 Windows 隐私设置中允许桌面应用访问麦克风。
  - 无需额外驱动、虚拟声卡、C++ 构建工具或 ffmpeg。
  - 已知限制：WASAPI 独占模式的音频无法通过 loopback 捕获；外放会使麦克风重复录到对方声音，建议戴耳机。
  - Claude 侧需支持 MCP stdio 的客户端（Claude 桌面端 / Claude Code）。

## 5. 与 Claude 的使用方式

1. 在 Claude 桌面端或 Claude Code 中配置本 MCP server。
2. 建议建一个 Project，指令写明"用户正在开会，需要时调用 audio-notes 的工具读取转写"。
3. 每场会议新开一个对话，会中随时提问，例如"刚才他们说了什么""帮我起草回应"，Claude 通过 `get_transcript` 拉取内容。

## 6. 范围外（MVP 不做）

- 主动推送、通知、关键词触发提醒
- 远端多人说话人分离（Speaker 1/2/3）
- 云端 ASR、中文及多语言
- 滚动摘要、会后自动总结
- macOS 支持、自动更新、安装包代码签名（MVP 接受未签名带来的提示，触发条件与候选方案见 F35）
- 设置界面（含 CPU/GPU 切换、模型档位切换，包括 Web 面板中的设置编辑）、数据自动清理
- 通过网络访问 Web 面板（仅限本机）

## 7. 里程碑

1. **M1** 采集验证：loopback + 麦克风录到 wav，确认两路音频正常。
2. **M2** 转写：接入 VAD 和本地 ASR，输出 JSONL，测量延迟和 CPU。
3. **M3** CLI：`record`、`show -f`、`sessions` 等，此时无需托盘即可端到端测试。
4. **M4** MCP server + `setup claude`：实现 F12–F13、F22 的 CLI 部分，在 Claude 中跑通"读取并回答"。
5. **M5** 托盘与 Web 面板：状态图标、菜单、首次法律提示、"连接到 Claude"、实时转写面板（F28–F31）。
6. **M6** 发布：PyPI 包与 CI/CD（F18–F19、F23），随后 Windows 安装包（F20–F21）。
7. **M7** 第二阶段评估：滚动摘要、主动提醒、GPU 与设置界面、macOS。

## 8. 待验证的风险

- 本地英文 ASR 在会议音质（压缩、重叠发言）下的准确率与延迟。
- 选定模型档位（`base.en` / `small.en`，int8 量化），并实测系统音频 + 麦克风双路并发时的 CPU 占用与延迟（预期 CPU 可行，仅需挑选平衡点）。
- MCP 是拉取式，若用户希望 Claude 主动打断提醒，需要在第二阶段引入直连 API 或其他机制。
- 安装包体积（ctranslate2、onnxruntime 较重，预计数百 MB 量级，需实际打包后确认）。
- 未签名 exe 的 SmartScreen / 杀毒误报对首批用户的影响，以及 Smart App Control 对未签名程序的直接拦截；缓解措施见 F33–F35，实际误报率需在首次发布后观察。
- 本地 Web 服务的安全性：确认 Host 校验与 token 方案足以防御 DNS rebinding；确认 MCP SDK 已带入的 Starlette / uvicorn 可复用，避免额外依赖。

## 9. 手动测试清单（不做自动化，开发后期统一与用户讨论并由用户手测）

- 托盘：图标三种状态切换、右键菜单各项、"打开面板"、首次法律提示。
- 外放（非耳机）时麦克风回声造成的 `me` / `them` 重复转写。
- 录制中切换默认音频设备（插拔耳机）后能否自动恢复。
- "连接到 Claude"写入配置后，在 Claude 桌面端 / Claude Code 中真实跑通"读取并回答"。
- 安装包在干净 Windows 环境中的安装、启动、卸载，以及 SmartScreen / 杀毒提示。
- 注：自动化的安装包冒烟测试（`--version` + MCP 握手）是否保留，待用户决定。
