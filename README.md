# cc-feishu-bridge

Claude Code 飞书桥接插件 — 在飞书中与本地 Claude Code 对话。

## 核心特性

**工作目录即 Claude 的工作目录。** 在哪个目录下启动 `cc-feishu-bridge`，Claude 就在哪个目录下工作。这意味着：

- 可以同时运行多个实例（多开），每个实例对应不同的飞书机器人、不同的 Claude 工作目录
- 例如在 `/project-A` 启动一个机器人，在 `/project-B` 启动另一个机器人，两者互不干扰

## 快速开始

### 方式一：直接运行编译好的 CLI（推荐）

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

首次运行会自动进入安装流程。

### 方式二：pip 安装

```bash
pip install cc-feishu-bridge
cc-feishu-bridge
```

### 方式三：源码安装

```bash
git clone https://github.com/Hu1J/cc-feishu-bridge.git
cd cc-feishu-bridge
pip install -e .
cc-feishu-bridge
```

## 安装配置

首次运行 `cc-feishu-bridge` 时会自动进入安装流程，按提示操作即可：

1. 使用飞书扫码授权
2. 扫码完成后自动创建机器人并保存配置

安装完成后配置文件位于 `.cc-feishu-bridge/config.yaml`（相对于启动目录）。

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

server:
  host: "0.0.0.0"
  port: 8080
  webhook_path: /feishu/webhook
```

## 使用方法

启动机器人：

```bash
cc-feishu-bridge
```

机器人启动后，在飞书中向机器人发送消息即可与 Claude Code 对话。

### 多开实例

在不同目录下启动 `cc-feishu-bridge`，即可同时运行多个机器人实例，每个实例有独立的工作目录和配置文件：

```bash
cd /path/to/project-A && cc-feishu-bridge  # 机器人 A 在 /path/to/project-A 下工作
cd /path/to/project-B && cc-feishu-bridge  # 机器人 B 在 /path/to/project-B 下工作
```

### 命令

- `/new` — 创建新会话
- `/status` — 查看当前会话状态

## 安全说明

`cc-feishu-bridge` 以 **bypassPermissions 模式**运行，Claude Code 可执行任意终端命令、读写本地文件，无需每次授权确认。请仅在可信任的网络环境下使用。

## 获取帮助

如有问题请提交 [Issue](https://github.com/Hu1J/cc-feishu-bridge/issues)。
