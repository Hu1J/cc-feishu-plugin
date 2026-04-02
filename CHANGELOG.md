# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

<!--
发版流程：
1. 在上方 [Unreleased] 区域填入本次变更内容
2. 创建 tag：git tag vx.x.x && git push --tags
3. GitHub Actions 自动读取本文件作为 Release 说明
4. 发版完成后，将 [Unreleased] 内容移至正式版本块，日期填当天，清空 [Unreleased]
-->

<!-- Add new changes here before each release. Move to a version section below when tagging. -->

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
