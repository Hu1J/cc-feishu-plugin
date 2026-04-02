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
- **多文件并发发送**：`cc-feishu-bridge send` 支持一次传入多个文件，所有文件并发上传、并发发送，显著提升批量发送速度（图片、文件可混合）
- **Stream 实时推送**：Claude 生成回复时，中间的流式文字现在会实时推送到飞书（带缓冲，工具调用时 flush，避免碎片刷屏）

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
