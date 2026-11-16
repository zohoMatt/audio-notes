# 可视化 demo

用来目视检查各模块的一次性小工具，各自起一个本地 HTTP 页面，仅绑定 127.0.0.1，按 Ctrl+C 停止。在仓库根目录运行：

| 模块 | 命令 | 地址 | 说明 |
|---|---|---|---|
| 采集 | `uv run python scripts/demos/capture_demo.py` | http://127.0.0.1:8801 | 系统音频 / 麦克风电平、测试音、FileSource 分块。仅 Windows |
| 转写流水线 | `uv run python scripts/demos/processing_demo.py` | http://127.0.0.1:8802 | 点 Start：波形、VAD 分段、逐行转写、相对实时的速度。默认用 `tests/fixtures`，首次选 `base.en` 会下载模型 |
| 存储 + MCP | `uv run python scripts/demos/store_mcp_demo.py` | http://127.0.0.1:8803 | 模拟两人对话写入、`StoreReader` 输出、真实 MCP 工具的原始返回。使用临时数据目录，不碰真实数据和 Claude 配置 |
| 托盘 + Web 面板 | `uv run python scripts/demos/tray_web_demo.py` | http://127.0.0.1:8765（带 token，终端会打印；双击托盘图标也会打开） | 真实 `TrayApp`（假录音控制器）+ 真实 `PanelServer`：托盘菜单“Start recording”开始写入模拟对话，面板实时显示、区分 me/them；首次会弹法律提示。使用临时数据目录；`DEMO_NO_TRAY=1` 只跑面板 |

三个端口互不冲突，可同时运行。8765 留给将来的正式 Web 面板。

这些脚本不属于产品代码，也不在 CI 中运行；它们依赖当前接口，接口变化后可能需要同步更新。
