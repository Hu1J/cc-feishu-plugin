# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [0.3.4] - 2026-04-05

### Changed
- **记忆系统改由 CC 自驱**：移除简陋的关键词规则引擎 `_try_extract_memory`，改为在每次对话时向 CC 注入固定提示词，引导 CC 遇到报错时主动搜记忆、解决后主动问用户是否记住、用户说"记住"时直接写入

## [0.3.3] - 2026-04-05

### Fixed
- **`/memory list` 报错**：`message_handler.py` 的 `_handle_memory()` 漏掉了 `list` 子命令处理，发 `/memory list` 时误报"未知子命令"，现已补全

## [0.3.0] - 2026-04-05

### Added
- **记忆增强系统**：本地 SQLite+FTS5 存储，记忆库位于 `~/.cc-feishu-bridge/memories.db`，所有项目全局共享
- **cc-memory-search skill**：CC 遇到报错时自动使用此 skill 搜索本地记忆库获取解决方案；skill 在 bridge 启动时自动安装到 `~/.claude/skills/`
- **`/memory` 指令**：飞书端管理记忆，支持 list / add / search / delete / clear 子命令
- **FTS5 全文搜索**：关键词检索，命中次数（use_count）越高的记忆越靠前
- **记忆类型与作用域**：
  - `problem_solution`（问题解决）— 全局共享，CC 通过 skill 按需搜索
  - `user_preference`（用户偏好）— 全局共享，每次对话自动注入 prompt
  - `project_context`（项目背景）— 项目隔离，每次对话自动注入 prompt
- **自动提取**：会话成功解决报错后，自动提取对话中的错误+解决方案写入记忆库

### Fixed
- **`/git` 工作区干净时不显示提交历史**：修复因条件判断错误导致无变更时 commit 历史被隐藏的问题

## [0.2.9] - 2026-04-05

### Fixed
- **`/help` 和 `/git` 报错**：`MessageHandler` 类缩进错误导致 `_safe_send`、`_handle_git` 等方法不在类内，引发 `AttributeError`
- **`/update` 已是最新时 bridge 意外死亡**：`os._exit(0)` 无条件执行，现改为 `run_update` 返回 bool，只有真正更新才 exit
- **`/update` 版本相同误触发更新**：`__version__` 硬编码为 `0.2.6`，现改为 `importlib.metadata` 动态读取，始终与 pip 安装版本一致
- **`/status` 显示版本号错误**：同上
- **Edit 工具降级路径报错**：fallback 分支错误引用 `marker.message_id`，`_DiffMarker` 无此字段，修复为 `message.message_id`
- **卡片行号对齐**：零填充（`01`、`02`…）替代空格右对齐，避免等宽字体压缩导致错位

### Changed
- **`__version__`**：从 `importlib.metadata` 动态读取，版本号与 PyPI 安装包始终一致

## [0.2.7] - 2026-04-05

### Added
- **`/restart` 飞书指令**：热重启当前 bridge 实例，所有通知卡片在退出前发完
- **`/update` 飞书指令**：检查 PyPI 最新版本，有更新则下载并自动 restart

### Removed
- **CLI 桌面客户端发布**：取消 GitHub Release 和 PyInstaller 多平台二进制打包，用户通过 pip 或源码安装；`/restart` 和 `/update` 指令保留，通过飞书指令使用

## [0.2.6] - 2026-04-05

### Changed
- **`cc-feishu-bridge stop`**：不再需要传入 PID，直接停掉当前目录下运行的 bridge 实例；当前目录无 bridge 时给出明确提示

## [0.2.5] - 2026-04-05

### Fixed
- **CLI switch 飞书通知**：修复 `cc-feishu-bridge switch` 执行时飞书消息不发送的问题——`asyncio.new_event_loop()` 创建后未设为当前线程 active loop，导致 FeishuClient/aiohttp 异步请求失败
- **approved_directory 路径重写**：切换项目时拷贝 config.yaml 同时重写 `claude.approved_directory` 为目标目录（之前只重写 `storage.db_path`）

## [0.2.4] - 2026-04-04

### Added
- **消息存储**：所有收到的用户消息自动写入 `messages` 表（原始 JSON + 处理后文本），为未来记忆增强打下基础

## [0.2.3] - 2026-04-04

### Changed
- **日志打印原始消息**：`ws_client.py` 日志字段从 `content`（已提取文本）改为 `raw_content`（原始 JSON 字符串），便于调试音频等特殊消息格式

### Removed
- **移除 server 配置**：删除了未使用的 `host`/`port`/`webhook` 配置项及其相关代码和 README 文档

### Added
- **README 文档完善**：新增主动推送功能说明、`/git` 指令使用说明及功能截图展示

## [0.2.2] - 2026-04-04

### Added
- **/git 命令**：直接展示当前项目 git status（emoji 状态标识）和最近 5 次提交（表格形式）
- **TodoWrite 卡片**：Claude 发出 TodoWrite 工具调用时自动拦截，渲染为待办事项表格，支持 pending/in_progress/completed 三种状态图标
- **README 截图展示**：新增功能截图展示区域

### Changed
- **Edit/Write 彩色 Diff 卡片**：使用 LCS 算法计算行级 diff，通过飞书 `lark_md` + `<font color>` 标签实现红色（删除）、绿色（新增）、灰色（上下文）着色，每行附带行号
- **Bash 工具格式化**：解析 `command` 和 `description` 字段，description 显示在标题行，命令以 ` ```bash ` 代码段呈现
- **Read 工具格式化**：提取 `file_path`，以换行 + backtick 包裹路径的形式展示
- **卡片发送失败降级**：当 Edit/Write 卡片发送失败时，自动降级为带图标的纯文本提示，确保用户始终收到通知
- **错误通知**：内部异常时主动向用户发送错误提示，而非静默丢弃
- **工具调用通知样式全面升级**：Read / Bash / Edit / Write 告别纯 backtick 格式，改为语义化展示

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
