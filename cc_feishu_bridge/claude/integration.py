"""Claude Code integration via claude-agent-sdk."""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from typing import Any, Callable, Awaitable, Optional

logger = logging.getLogger(__name__)


@dataclass
class ClaudeMessage:
    content: str
    is_final: bool = False
    tool_name: str | None = None
    tool_input: str | None = None


StreamCallback = Callable[[ClaudeMessage], Awaitable[None]]


class ClaudeIntegration:
    def __init__(
        self,
        cli_path: str = "claude",
        max_turns: int = 50,
        approved_directory: str | None = None,
    ):
        # Resolve "claude" to its absolute path so the subprocess spawned by the SDK
        # doesn't have to rely on PATH resolution (avoids issues on Windows where
        # npm's claude.cmd may not be found by anyio.open_process).
        if cli_path == "claude":
            resolved = shutil.which("claude")
            self.cli_path = resolved if resolved else cli_path
        else:
            self.cli_path = cli_path
        self.max_turns = max_turns
        self.approved_directory = approved_directory
        self._client: Optional[Any] = None  # 持久化 client
        self._client_ready: bool = False
        self._system_prompt_append: str | None = None  # 缓存当前 system prompt
        self._system_prompt_dirty: bool = False  # True = 下次 query 前需重连

    # -------------------------------------------------------------------------
    # System prompt stale marking
    # -------------------------------------------------------------------------

    def mark_system_prompt_stale(self) -> None:
        """
        标记 system prompt 已过期，下一条消息处理前需要重连 CLI。

        用户偏好/记忆更新时调用。
        """
        self._system_prompt_dirty = True
        logger.info("[ClaudeIntegration] System prompt marked stale, will reconnect on next query")

    # -------------------------------------------------------------------------
    # Lifecycle: connect / disconnect
    # -------------------------------------------------------------------------

    async def connect(
        self,
        system_prompt_append: str | None = None,
    ) -> None:
        """
        建立持久 CLI 进程。SDK 通过 continue_conversation=True 自动维护 session。
        """
        if self._client is not None:
            await self.disconnect()

        from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
        from cc_feishu_bridge.claude.memory_tools import get_memory_mcp_server
        from cc_feishu_bridge.claude.feishu_file_tools import get_feishu_file_mcp_server

        self._system_prompt_append = system_prompt_append
        self._system_prompt_dirty = False

        options = ClaudeAgentOptions(
            cwd=self.approved_directory or ".",
            max_turns=self.max_turns,
            cli_path=self.cli_path,
            include_partial_messages=True,
            permission_mode="bypassPermissions",
            # SDK 内部自动维护 session 状态，每次 query 接着上一次继续
            continue_conversation=True,
            mcp_servers={
                "memory": get_memory_mcp_server(),
                "feishu_file": get_feishu_file_mcp_server(),
            },
        )

        if system_prompt_append:
            options.system_prompt = {
                "type": "preset",
                "preset": "claude_code",
                "append": system_prompt_append,
            }

        self._client = ClaudeSDKClient(options=options)

        await self._client.connect()
        self._client_ready = True

        logger.info("[ClaudeIntegration.connect] CLI process started, continue_conversation=True")

    async def disconnect(self) -> None:
        """关闭持久 CLI 进程。"""
        if self._client is None:
            return

        logger.info("[ClaudeIntegration.disconnect] CLI process shutting down")
        try:
            await self._client.disconnect()
        except Exception as e:
            logger.warning(f"[ClaudeIntegration.disconnect] error: {e}")
        finally:
            self._client = None
            self._client_ready = False

    def is_connected(self) -> bool:
        """返回 CLI 进程是否已连接。"""
        return self._client_ready and self._client is not None

    async def ensure_connected(self, system_prompt_append: str | None = None) -> None:
        """
        确保 CLI 已连接，未连接或 system prompt 已过期时自动重连。
        """
        needs_reconnect = not self.is_connected() or self._system_prompt_dirty
        if not needs_reconnect:
            return
        await self.connect(system_prompt_append)

    # -------------------------------------------------------------------------
    # Query
    # -------------------------------------------------------------------------

    async def query(
        self,
        prompt: str,
        cwd: str | None = None,
        on_stream: StreamCallback | None = None,
    ) -> tuple[str, str | None, float]:
        """
        通过持久 CLI 进程发送消息。

        Returns: (response_text, new_session_id, cost_usd)
        """
        if self._client is None or not self._client_ready:
            raise RuntimeError(
                "ClaudeIntegration not connected. Call connect() first."
            )

        try:
            result_text = ""
            result_session_id = None
            result_cost = 0.0

            logger.info(
                f"[ClaudeIntegration.query] >>> cwd={cwd or self.approved_directory!r}"
            )

            # 通过持久 client 发送 query，SDK 自动维护 session 继续
            await self._client.query(prompt=prompt)

            async for message in self._client.receive_response():
                msg_type = type(message).__name__

                if msg_type == "ResultMessage":
                    result_text = getattr(message, "result", "") or ""
                    result_session_id = getattr(message, "session_id", None)
                    result_cost = getattr(message, "total_cost_usd", 0.0) or 0.0
                    # 只打印 session_id，不存储也不用于后续
                    logger.info(
                        f"[ClaudeIntegration.query] <<< session_id={result_session_id!r}, cost={result_cost!r}"
                    )

                if on_stream:
                    parsed = self._parse_message(message)
                    if parsed:
                        await on_stream(parsed)

            return (result_text, result_session_id, result_cost)

        except Exception as e:
            logger.exception(f"[ClaudeIntegration.query] error: {e}")
            # CLI 进程可能已崩溃，标记为未就绪
            self._client_ready = False
            raise

    # -------------------------------------------------------------------------
    # Interrupt
    # -------------------------------------------------------------------------

    async def interrupt_current(self) -> bool:
        """Send SIGINT to the running Claude subprocess. Returns True if interrupted."""
        if self._client is None or not self._client_ready:
            return False
        try:
            await self._client.interrupt()
            return True
        except Exception as e:
            logger.warning(f"[ClaudeIntegration.interrupt_current] error: {e}")
            return False

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _parse_message(self, message) -> ClaudeMessage | None:
        """Parse SDK Message into ClaudeMessage."""
        import json

        msg_type = type(message).__name__

        if msg_type == "AssistantMessage":
            for block in getattr(message, "content", []):
                block_type = type(block).__name__
                if block_type == "TextBlock":
                    text = getattr(block, "text", "")
                    if text:
                        return ClaudeMessage(content=text, is_final=False)
                elif block_type == "ToolUseBlock":
                    tool_name = getattr(block, "name", "Unknown")
                    tool_input = getattr(block, "input", "")
                    if isinstance(tool_input, dict):
                        tool_input = json.dumps(tool_input, ensure_ascii=False)
                    return ClaudeMessage(
                        content="",
                        is_final=False,
                        tool_name=tool_name,
                        tool_input=tool_input,
                    )

        elif msg_type == "ResultMessage":
            return None

        return None
