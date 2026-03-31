# WebSocket 长连接重构实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 将 cc-feishu-bridge 从 Webhook 模式（需要公网 IP）重构为 WebSocket 长连接模式（程序主动连飞书，无需端口暴露），同时确保 Claude 的 cwd 使用 session.project_path。

**架构：** 用 `lark_oapi.ws.Client` 建立与飞书的长连接，通过 `EventDispatcherHandlerBuilder` 注册 `im.message.receive_v1` 事件回调。收到消息后路由到现有 MessageHandler 处理。发消息依然用 `lark_oapi.Client` 的 REST API。

**技术栈：** lark-oapi ws.Client、asyncio、SQLite

---

## 文件变更概览

| 文件 | 改动 |
|------|------|
| `src/main.py` | 删除 aiohttp server 和 webhook 路由，改用 ws.Client 建立长连接 |
| `src/feishu/ws_client.py` | 新建：封装 ws.Client，提供消息回调接口 |
| `src/feishu/message_handler.py` | cwd 改为 session.project_path |

---

## Task 1: 新建 FeishuWSClient

**文件：**
- 创建: `src/feishu/ws_client.py`
- 测试: `tests/test_ws_client.py`

- [ ] **Step 1: 写测试**

```python
# tests/test_ws_client.py
import pytest
from unittest.mock import AsyncMock, MagicMock

def test_ws_client_initializes():
    from src.feishu.ws_client import FeishuWSClient
    client = FeishuWSClient(
        app_id="test_app_id",
        app_secret="test_secret",
        on_message=AsyncMock(),
    )
    assert client.app_id == "test_app_id"
    assert client.app_secret == "test_secret"
    assert client._handler is not None
    assert client._ws_client is not None

def test_on_message_callback():
    from src.feishu.ws_client import FeishuWSClient
    cb = AsyncMock()
    client = FeishuWSClient(app_id="id", app_secret="secret", on_message=cb)
    # Simulate message event
    mock_event = MagicMock()
    mock_event.message.message_id = "msg_123"
    mock_event.message.chat_id = "chat_abc"
    mock_event.message.sender.sender_id.open_id = "user_xyz"
    mock_event.message.content = '{"text":"hello"}'
    mock_event.message.msg_type = "text"
    mock_event.message.create_time = "1234567890"
    client._handle_p2p_message(mock_event)
    cb.assert_called_once()
    msg = cb.call_args[0][0]
    assert msg.message_id == "msg_123"
    assert msg.chat_id == "chat_abc"
    assert msg.user_open_id == "user_xyz"
    assert msg.content == "hello"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_ws_client.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: 实现 FeishuWSClient**

```python
# src/feishu/ws_client.py
"""Feishu WebSocket long-connection client using lark-oapi ws.Client."""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Awaitable
from dataclasses import dataclass

from src.feishu.client import IncomingMessage

logger = logging.getLogger(__name__)

MessageCallback = Callable[[IncomingMessage], Awaitable[None]]


class FeishuWSClient:
    """Manages WebSocket connection to Feishu via lark-oapi ws.Client."""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        bot_name: str = "Claude",
        domain: str = "feishu",
        on_message: MessageCallback | None = None,
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.bot_name = bot_name
        self.domain = domain
        self._on_message = on_message
        self._ws_client = None
        self._handler = None

    def _build_event_handler(self):
        """Build EventDispatcherHandler with message callback registered."""
        import lark_oapi as lark

        builder = lark.EventDispatcherHandler.builder(
            encrypt_key="",
            verification_token="",
        )

        def wrapped_handler(event):
            """Handle incoming p2p message event."""
            if self._on_message is None:
                return
            try:
                message = event.message
                sender = event.sender
                msg_type = getattr(message, "msg_type", "text")
                content_str = getattr(message, "content", "{}")

                # Parse JSON content
                content = content_str
                if msg_type == "text":
                    try:
                        import json
                        content = json.loads(content_str).get("text", "")
                    except Exception:
                        pass

                sender_id = getattr(sender, "sender_id", None)
                user_open_id = ""
                if sender_id is not None:
                    user_open_id = getattr(sender_id, "open_id", "")

                incoming = IncomingMessage(
                    message_id=getattr(message, "message_id", ""),
                    chat_id=getattr(message, "chat_id", ""),
                    user_open_id=user_open_id,
                    content=content,
                    message_type=msg_type,
                    create_time=getattr(message, "create_time", ""),
                )
                # Schedule the async handler in the running event loop
                asyncio.ensure_future(self._on_message(incoming))
            except Exception as e:
                logger.exception(f"Error handling message: {e}")

        builder.register_p2_im_message_receive_v1(wrapped_handler)
        self._handler = builder.build()
        return self._handler

    def start(self) -> None:
        """Start the WebSocket long connection (blocking)."""
        import lark_oapi as lark

        handler = self._build_event_handler()
        base_url = "https://open.feishu.cn" if self.domain == "feishu" else "https://open.larksuite.com"

        self._ws_client = lark.ws.Client(
            self.app_id,
            self.app_secret,
            log_level=lark.LogLevel.INFO,
            event_handler=handler,
            domain=base_url,
            auto_reconnect=True,
        )
        logger.info(f"Starting Feishu WebSocket connection to {base_url}...")
        self._ws_client.start()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_ws_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_ws_client.py src/feishu/ws_client.py
git commit -m "feat: add FeishuWSClient for WebSocket long connection"
```

---

## Task 2: 重构 main.py — 去掉 aiohttp server，启用 WS 长连接

**文件：**
- 修改: `src/main.py`

- [ ] **Step 1: 写测试**

```python
# tests/test_main_ws.py
def test_run_server_raises_notImplemented():
    """run_server should raise NotImplementedError in WS mode."""
    from src.main import run_server
    import pytest
    with pytest.raises(NotImplementedError):
        run_server("config.yaml")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_main_ws.py -v`
Expected: FAIL (run_server doesn't exist yet)

- [ ] **Step 3: 实现重构后的 main.py**

`src/main.py` 变更：

```python
"""CLI entry point — starts WebSocket long connection to Feishu."""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from src.config import load_config
from src.feishu.client import FeishuClient, IncomingMessage
from src.feishu.ws_client import FeishuWSClient
from src.feishu.message_handler import MessageHandler
from src.security.auth import Authenticator
from src.security.validator import SecurityValidator
from src.claude.integration import ClaudeIntegration
from src.claude.session_manager import SessionManager
from src.format.reply_formatter import ReplyFormatter

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = "config.yaml"


def create_handler(config) -> MessageHandler:
    """Create MessageHandler with all dependencies wired up."""
    feishu = FeishuClient(
        app_id=config.feishu.app_id,
        app_secret=config.feishu.app_secret,
        bot_name=config.feishu.bot_name,
    )
    authenticator = Authenticator(allowed_users=config.auth.allowed_users)
    validator = SecurityValidator(approved_directory=config.claude.approved_directory)
    claude = ClaudeIntegration(
        cli_path=config.claude.cli_path,
        max_turns=config.claude.max_turns,
        approved_directory=config.claude.approved_directory,
    )
    session_manager = SessionManager(db_path=config.storage.db_path)
    formatter = ReplyFormatter()

    handler = MessageHandler(
        feishu_client=feishu,
        authenticator=authenticator,
        validator=validator,
        claude=claude,
        session_manager=session_manager,
        formatter=formatter,
        approved_directory=config.claude.approved_directory,
    )
    return handler


async def handle_message(message: IncomingMessage, handler: MessageHandler) -> None:
    """Callback for incoming Feishu messages — dispatch to handler."""
    try:
        await handler.handle(message)
    except Exception as e:
        logger.exception(f"Error handling message: {e}")


def run_server(config_path: str):
    """Start WebSocket long connection to Feishu. This is blocking."""
    raise NotImplementedError(
        "run_server is removed in WS mode. "
        "Use start_bridge() instead."
    )


def start_bridge(config_path: str) -> None:
    """Start the bridge: load config and run WebSocket connection."""
    config = load_config(config_path)
    handler = create_handler(config)

    ws_client = FeishuWSClient(
        app_id=config.feishu.app_id,
        app_secret=config.feishu.app_secret,
        bot_name=config.feishu.bot_name,
        domain=config.feishu.domain,
        on_message=lambda msg: handle_message(msg, handler),
    )
    logger.info("Starting Feishu bridge (WebSocket mode)...")
    ws_client.start()


def detect_config(config_path: str) -> bool:
    """Check if config file exists and is non-empty."""
    p = Path(config_path)
    return p.exists() and p.stat().st_size > 0


async def interactive_install(config_path: str):
    """Run the QR-code install flow, then start bridge."""
    from src.install.flow import run_install_flow
    await run_install_flow(config_path)
    # Install complete; start bridge in a fresh loop.
    start_bridge(config_path)


def main():
    parser = argparse.ArgumentParser(description="Claude Code Feishu Bridge")
    parser.add_argument(
        "--config",
        type=str,
        default=DEFAULT_CONFIG_PATH,
        help="Path to config.yaml",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    log_path = Path("data") / "cc-feishu-bridge.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(log_path),
            logging.StreamHandler(),
        ],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("qrcode").setLevel(logging.WARNING)

    if detect_config(args.config):
        logger.info(f"Config found at {args.config}, starting bridge...")
        start_bridge(args.config)
    else:
        logger.info(f"No config found at {args.config}, running install flow...")
        asyncio.run(interactive_install(args.config))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_main_ws.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/main.py
git commit -m "refactor: replace aiohttp webhook with ws.Client long connection"
```

---

## Task 3: 更新 message_handler — 使用 session.project_path 作为 cwd

**文件：**
- 修改: `src/feishu/message_handler.py:81`

- [ ] **Step 1: 确认当前代码**

```python
# 确认当前第81行附近
response, new_session_id, cost = await self.claude.query(
    prompt=message.content,
    session_id=sdk_session_id,
    cwd=self.approved_directory,   # ← 这里是问题：永远用全局目录
    on_stream=stream_callback,
)
```

- [ ] **Step 2: 改用 session.project_path**

```python
# 替换 cwd=self.approved_directory 为 session.project_path
response, new_session_id, cost = await self.claude.query(
    prompt=message.content,
    session_id=sdk_session_id,
    cwd=session.project_path if session else self.approved_directory,
    on_stream=stream_callback,
)
```

- [ ] **Step 3: 运行测试**

Run: `pytest tests/ -v` (整体测试)
Expected: 现有测试通过

- [ ] **Step 4: Commit**

```bash
git add src/feishu/message_handler.py
git commit -m "fix: use session.project_path as Claude cwd instead of global approved_directory"
```

---

## Task 4: 清理 build.py 和 CI 配置

**文件：**
- 修改: `build.py` — 不需要改（entry point 依然是 run.py，main.py 改完即可）
- 修改: `.github/workflows/release.yml` — 不需要改

- [ ] **Step 1: 构建验证**

Run: `python build.py --clean && ls -lh dist/cc-feishu-bridge`
Expected: 41MB 左右的 binary 生成成功

- [ ] **Step 2: Commit CI 配置变更（如有）**

CI 无需改动，确认后提交。

---

## Task 5: 端到端测试

- [ ] **Step 1: 在 dist/ 目录下运行**

```bash
./dist/cc-feishu-bridge --config config.yaml
```

- [ ] **Step 2: 在飞书给 Bot 发消息**

Bot 应该能收到并回复，Claude 上下文正常维持。

- [ ] **Step 3: Commit 最终状态**

```bash
git add -A && git commit -m "chore: complete WS long connection refactor"
```
