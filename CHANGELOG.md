# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [0.2.0] - 2026-04-04

### Added
- **Edit/Write 工具彩色 Diff 渲染**：使用飞书 `annotated_text` 逐行着色，红色为删除、绿色为新增、灰色为上下文，大幅提升代码变更可读性
- **主动联系冷却机制**：新增 `cooldown_minutes` 配置项，避免过于频繁地主动向用户推送消息

### Fixed
- **工具调用参数中文乱码**：修复 `json.dumps` 默认 `ensure_ascii=True` 导致中文被转义为 Unicode escape 的问题
- **文件扩展名错误**：修复下载 .txt 和 .csv 文件时被错误保存为 .bin 的问题

## [0.1.6] - 2026-04-03

### Added
- **启动 Banner**：终端和日志文件同步打印红色 `cc-feishu-bridge v{version}` + 绿色 `started at {timestamp}`
- **PyPI 自动发布**：推送 tag 时自动触发 GitHub Actions 构建 whl 并发布到 PyPI，同时验证 tag 版本与 pyproject.toml 一致

### Changed
- **主动推送默认开启**：`ProactiveConfig.enabled` 默认为 `True`（之前为 `False`）
- **旧配置自动升级**：老用户 config.yaml 无 proactive 字段时，首次启动自动补全

### Fixed
- **ProactiveScheduler 事件循环**：修复在同步上下文中调用 `start()` 时 `asyncio.create_task()` 报错的问题，改为独立 daemon 线程运行自己的事件循环

## [0.1.7] - 2026-04-03

### Fixed
- **主动推送冷却机制**：修复发完通知后无冷却期导致频繁重复提醒的问题，新增 `cooldown_minutes`（默认 60 分钟）配置；发完后记录 `last_proactive_at` 时间戳，同会话冷却期内不再触发

### Changed
- **沉默阈值调高**：`silence_threshold_minutes` 默认值从 60 分钟调整为 90 分钟，减少误触发

## [0.1.8] - 2026-04-03

### Added
- **`-v` / `--version` 参数**：支持 `cc-feishu-bridge -v` / `--version` 显示版本号，与 pyproject.toml 版本同步

### Fixed
- **文件扩展名修复**：接收文件时优先使用原始文件名扩展名，不再被飞书返回的 `file_type` 带跑（例如 txt 文件不会变成 .bin）；同时修正 `guess_file_type` 中 `.txt` → `"stream"` 的错误映射

## [0.1.9] - 2026-04-03

### Fixed
- **MCP 工具调用中文乱码**：修复 `json.dumps` 默认 `ensure_ascii=True` 导致工具参数中的中文被转义为 Unicode escape 的问题，改为 `ensure_ascii=False` 保留原始中文；同时移除对工具输入日志的截断

<!--
发版流程：
1. 在上方 [Unreleased] 区域填入本次变更内容
2. 创建 tag：git tag vx.x.x && git push --tags
3. GitHub Actions 自动读取本文件作为 Release 说明
4. 发版完成后，将 [Unreleased] 内容移至正式版本块，日期填当天，清空 [Unreleased]
-->

## [0.1.3] - 2026-04-02

### Fixed
- **Claude 检查提前**：在 WS 连接前检查 Claude CLI 可用性，找不到直接报错退出，不再先连上飞书才发现
- **/stop 修复**：修复偶发情况下 `/stop` 报"没有正在运行的查询"的问题（race condition：`create_task` 后协程未执行时 `task.done()` 已为 False）
- **Windows Claude 路径**：把 `cli_path="claude"` 解析成完整路径，解决 Windows npm 安装的 `claude.cmd` 子进程找不到的问题
- **Windows emoji 日志**：用 SafeStreamHandler 捕获 UnicodeEncodeError，避免 Windows GBK 控制台无法输出 emoji 导致日志报错
- **会话续接修复**：`continue_conversation` 必须在 `ClaudeSDKClient` 创建前设置，SDK 在 `__init__` 时已读取该选项

### Changed
- `/feishu` 帮助指令改名为 `/help`，更直观
- README 调整安装方式顺序，pip 安装推荐优先
- 移除 PyInstaller 中冗余的 `qrcode_terminal` 隐式导入

## [0.1.2] - 2026-04-02

### Added
- **全局消息队列**：所有用户消息统一进入 FIFO 队列，由单一 Worker 串行处理，支持多用户并发和同一用户连续消息有序执行
- **回复链（Threaded Reply）**：Claude 的所有回复均以飞书引用回复（Reply API）的形式发送，对话结构清晰
- **引用消息感知**：用户引用某条消息发送时，Claude 自动获取被引用内容并注入 prompt，格式为 `[引用消息: id] 发送者: 内容`；若引用消息不可用则降级显示 `[引用消息不可用: id]`
- **音频消息支持**：用户发送语音消息时下载为 `.opus` 文件，以 `[Audio: path]` 格式传给 Claude
- **/stop 打断指令**：用户发送 `/stop` 立即中断 Claude 当前查询，同时取消后台 Worker 任务
- **多文件并发发送**：`cc-feishu-bridge send` 支持一次传入多个文件，所有文件并发上传、并发发送，显著提升批量发送速度（图片、文件可混合）
- **Stream 实时推送**：Claude 生成回复时，文字片段实时推送到飞书（带缓冲，工具调用时 flush），避免碎片刷屏；如果流式过程中已发送过文字，则跳过最终完整回复，避免重复
- **工具图标**：未知工具的兜底图标从 🔧 改为 🤖
- **图片 prompt 格式修复**：接收图片时使用 `![image](path)` markdown 格式，确保 Claude Code CLI 的 `detectAndLoadPromptImages` 正确识别并描述图片
- **单实例锁**：使用 `filelock` 确保同一机器同时只有一个 bridge 进程运行，避免重复连接飞书 WS

### Changed
- `/feishu` 帮助指令改名为 `/help`，更直观

### Fixed
- 修复富文本消息（Rich Post）中图片 key 的提取
- 修复 WS 事件中图片消息 content 缺少 `image_key` 的问题（改用 API 获取）
- 修复 BytesIO 媒体下载后的读取方式（`response.file.read()`）
- 降低 WS 解析兜底日志级别（`warning` → `debug`）

## [0.1.1] - 2026-04-02

### Added
- **双向图片/文件传输**：用户发送图片或文件给机器人，Claude 可以读取并处理；Claude 生成的图片会自动发回飞书
  - 图片：下载保存至 `.cc-feishu-bridge/received_images/`，以本地路径传给 Claude
  - 文件：下载保存至 `.cc-feishu-bridge/received_files/`，以本地路径传给 Claude
  - Claude 返回的图片：以 base64 接收，上传至飞书后发回聊天

### Fixed
- 修复 `test_integration.py` 中引用不存在方法 `_parse_event` 的问题
- 修复 `test_main_ws.py` 中旧包名 `src.main` 的问题

## [0.1.0] - 2026-04-01

### Added
- 初始版本，支持飞书文字消息收发
- 扫码安装流程
- `/new` 和 `/status` 命令
- bypass 风险提示（首次确认后记录到配置）
- 回复内容记录到日志
