# cc-feishu-bridge

Claude Code 飞书桥接插件 — 在飞书中与本地 Claude Code 对话。

## 命令

- `/new` — 创建新会话
- `/status` — 查看当前会话状态（会话 ID、消息数、累计费用、工作目录）
- `/stop` — 打断 Claude 当前正在执行的查询
- `/help` — 查看所有可用命令

## 核心功能

- **工作目录即 Claude 的工作目录** — 在哪个目录下启动，就在哪个目录下工作；支持多开实例
- **消息队列** — 所有消息串行处理，不会出现并发冲突
- **引用回复** — Claude 的每条回复作为引用回复发出，对话结构清晰
- **引用消息感知** — 引用某条消息发送时，Claude 能感知原文
- **实时流式推送** — Claude 生成回复时实时推送，工具调用立即 flush，不重复发送
- **工具调用精美卡片** — Edit/Write 显示彩色 diff（行号 + 增删着色）；Bash 以代码段展示；Read 显示文件路径；TodoWrite 渲染为待办表格；Git Status 展示状态和最近提交

## 截图展示

### Edit / Write 彩色 Diff

![Edit Diff](docs/screenshots/edit-diff.png)

### Bash 工具

![Bash](docs/screenshots/bash-command.png)

### Git Status

![Git Status](docs/screenshots/git-command.png)

### TodoWrite 待办列表

![TodoWrite](docs/screenshots/todowrite.png)

### 日常对话

![Regular Text](docs/screenshots/regular-text.png)

## 快速开始

### 方式一：pip 安装（推荐）

```bash
pip install -U cc-feishu-bridge
cc-feishu-bridge
```

### 方式二：直接运行编译好的 CLI

下载对应平台的压缩包并解压，然后将其加入系统 PATH 环境变量：

| 平台 | 架构 | 下载文件 |
|------|------|---------|
| macOS | Apple Silicon (arm64) | `cc-feishu-bridge-macos-arm64` |
| macOS | Intel (x86_64) | `cc-feishu-bridge-macos-x86_64` |
| Windows | x86_64 | `cc-feishu-bridge-windows-x86_64.exe` |

**macOS / Linux：**

```bash
# 下载并解压后，移入 PATH
chmod +x cc-feishu-bridge-*
sudo mv cc-feishu-bridge-* /usr/local/bin/cc-feishu-bridge

# 验证安装成功
cc-feishu-bridge
```

**Windows：**

1. 下载 `cc-feishu-bridge-windows-x86_64.exe` 并放到任意目录，例如 `C:\Program Files\cc-feishu-bridge\`
2. 按 `Win + R` 输入 `sysdm.cpl` → 高级 → 环境变量
3. 在用户变量或系统变量的 `Path` 中添加该目录路径
4. 重新打开命令提示符验证：

```cmd
cc-feishu-bridge.exe
```

### 方式三：源码安装

```bash
git clone https://github.com/Hu1J/cc-feishu-bridge.git
cd cc-feishu-bridge
pip install -e .
cc-feishu-bridge
```

## 安装配置

首次运行 `cc-feishu-bridge` 时会自动进入安装流程，按提示操作即可（飞书扫码授权 → 创建机器人）。

配置文件位于 `.cc-feishu-bridge/config.yaml`（相对于启动目录）。

### 手动配置

如果需要手动配置，复制 `config.example.yaml` 为 `.cc-feishu-bridge/config.yaml`（相对于启动目录）：

```yaml
feishu:
  app_id: cli_xxx          # 飞书应用 App ID
  app_secret: xxx          # 飞书应用 App Secret
  bot_name: Claude

auth:
  allowed_users:            # 允许使用机器人的用户 open_id 列表
    - ou_xxx

claude:
  cli_path: claude          # claude CLI 路径
  max_turns: 50             # 最大对话轮数
  approved_directory: /path/to/workdir  # Claude 工作目录

storage:
  db_path: .cc-feishu-bridge/sessions.db
```

## 多开实例

在不同目录下启动 `cc-feishu-bridge`，即可同时运行多个机器人实例，每个实例有独立的工作目录和配置文件：

```bash
cd /path/to/project-A && cc-feishu-bridge  # 机器人 A 在 /path/to/project-A 下工作
cd /path/to/project-B && cc-feishu-bridge  # 机器人 B 在 /path/to/project-B 下工作
```

## 安全说明

`cc-feishu-bridge` 以 **bypassPermissions 模式**运行，Claude Code 可执行任意终端命令、读写本地文件，无需每次授权确认。请仅在可信任的网络环境下使用。

## 获取帮助

如有问题请提交 [Issue](https://github.com/Hu1J/cc-feishu-bridge/issues)。

## 更新日志

详见 [CHANGELOG.md](./CHANGELOG.md)。
