"""Claude Code integration via claude-agent-sdk."""
from __future__ import annotations

import asyncio
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
        self._query_lock: asyncio.Lock = asyncio.Lock()  # 保证同一时间只有一个 query 在执行
        self._interrupt_lock: asyncio.Lock = asyncio.Lock()  # 保证 interrupt 不能重入

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
        import time as time_module

        if self._client is not None:
            logger.info(f"[ClaudeIntegration.connect] existing client found, disconnecting first...")
            t0 = time_module.time()
            await self.disconnect()
            logger.info(f"[ClaudeIntegration.connect] disconnect took {time_module.time() - t0:.1f}s")

        from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
        from cc_feishu_bridge.claude.memory_tools import get_memory_mcp_server
        from cc_feishu_bridge.claude.feishu_file_tools import get_feishu_file_mcp_server

        self._system_prompt_append = system_prompt_append
        self._system_prompt_dirty = False

        t = time_module.time()
        logger.info("[ClaudeIntegration.connect] getting memory MCP server...")
        memory_server = get_memory_mcp_server()
        logger.info(f"[ClaudeIntegration.connect] memory MCP server ready in {time_module.time()-t:.1f}s")

        t = time_module.time()
        logger.info("[ClaudeIntegration.connect] getting feishu_file MCP server...")
        feishu_server = get_feishu_file_mcp_server()
        logger.info(f"[ClaudeIntegration.connect] feishu_file MCP server ready in {time_module.time()-t:.1f}s")

        logger.info(f"[ClaudeIntegration.connect] creating ClaudeSDKClient, cli_path={self.cli_path!r}, cwd={self.approved_directory!r}")

        options = ClaudeAgentOptions(
            cwd=self.approved_directory or ".",
            # NOTE: 不传 cli_path，让 SDK 使用内置的 bundled CLI。
            # 显式指定 cli_path 在 Windows 上会导致 initialize() 超时，
            # 因为 claude.CMD 这个 npm 包装器在 anyio.open_process 中
            # 处理时存在问题。
            include_partial_messages=True,
            permission_mode="bypassPermissions",
            continue_conversation=True,
            mcp_servers={
                "memory": memory_server,
                "feishu_file": feishu_server,
            },
        )

        if system_prompt_append:
            options.system_prompt = {
                "type": "preset",
                "preset": "claude_code",
                "append": system_prompt_append,
            }

        self._client = ClaudeSDKClient(options=options)

        # SDK connect 有概率在 Windows 上超时，重试最多 3 次
        last_err = None
        for attempt in range(3):
            logger.info(f"[ClaudeIntegration.connect] attempt {attempt + 1}/3, calling _client.connect()...")
            t_connect = time_module.time()
            try:
                await self._client.connect()
                elapsed = time_module.time() - t_connect
                logger.info(f"[ClaudeIntegration.connect] attempt {attempt + 1} succeeded in {elapsed:.1f}s")
                break
            except Exception as e:
                elapsed = time_module.time() - t_connect
                last_err = e
                logger.warning(f"[ClaudeIntegration.connect] attempt {attempt + 1} failed after {elapsed:.1f}s: {e}")
                if attempt < 2:
                    logger.info(f"[ClaudeIntegration.connect] recreating client for retry...")
                    # 重置 client，准备重试
                    self._client = ClaudeSDKClient(options=options)
        else:
            # 3 次全失败
            self._client = None
            self._client_ready = False
            logger.error(f"[ClaudeIntegration.connect] all 3 attempts failed")
            raise last_err

        self._client_ready = True
        logger.info("[ClaudeIntegration.connect] CLI process started, continue_conversation=True")

    async def disconnect(self) -> None:
        """关闭持久 CLI 进程。"""
        if self._client is None:
            logger.info("[ClaudeIntegration.disconnect] no client, returning")
            return

        logger.info("[ClaudeIntegration.disconnect] CLI process shutting down...")
        try:
            await self._client.disconnect()
            logger.info("[ClaudeIntegration.disconnect] disconnect() returned successfully")
        except Exception as e:
            logger.warning(f"[ClaudeIntegration.disconnect] error: {e}")
        finally:
            self._client = None
            self._client_ready = False
            logger.info("[ClaudeIntegration.disconnect] client set to None, ready=False")

    def is_connected(self) -> bool:
        """返回 CLI 进程是否已连接。"""
        return self._client_ready and self._client is not None

    async def ensure_connected(self, system_prompt_append: str | None = None) -> None:
        """
        确保 CLI 已连接，未连接或 system prompt 已过期时自动重连。
        """
        connected = self.is_connected()
        dirty = self._system_prompt_dirty
        logger.info(f"[ClaudeIntegration.ensure_connected] is_connected={connected}, dirty={dirty}")
        needs_reconnect = not connected or dirty
        if not needs_reconnect:
            logger.info("[ClaudeIntegration.ensure_connected] no reconnect needed")
            return
        logger.info(f"[ClaudeIntegration.ensure_connected] calling connect()...")
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

        协程锁保证同一时间只有一个 query 在执行，避免消息流并发消费混乱。

        Returns: (response_text, new_session_id, cost_usd)
        """
        if self._client is None or not self._client_ready:
            raise RuntimeError(
                "ClaudeIntegration not connected. Call connect() first."
            )

        import time as time_module
        try:
            async with self._query_lock:
                result_text = ""
                result_session_id = None
                result_cost = 0.0

                logger.info(
                    f"[ClaudeIntegration.query] >>> cwd={cwd or self.approved_directory!r}"
                )

                t_query = time_module.time()
                # 通过持久 client 发送 query，SDK 自动维护 session 继续
                await self._client.query(prompt=prompt)

                async for message in self._client.receive_response():
                    msg_type = type(message).__name__

                    if msg_type == "ResultMessage":
                        result_text = getattr(message, "result", "") or ""
                        result_session_id = getattr(message, "session_id", None)
                        result_cost = getattr(message, "total_cost_usd", 0.0) or 0.0
                        elapsed = time_module.time() - t_query
                        # 只打印 session_id，不存储也不用于后续
                        logger.info(
                            f"[ClaudeIntegration.query] <<< session_id={result_session_id!r}, cost={result_cost!r}, elapsed={elapsed:.1f}s"
                        )

                    if on_stream:
                        parsed = self._parse_message(message)
                        if parsed:
                            await on_stream(parsed)

                return (result_text, result_session_id, result_cost)

        except Exception as e:
            elapsed = time_module.time() - t_query
            logger.exception(f"[ClaudeIntegration.query] error after {elapsed:.1f}s: {e}")
            # CLI 进程可能已崩溃，标记为未就绪
            self._client_ready = False
            raise

    # -------------------------------------------------------------------------
    # Interrupt
    # -------------------------------------------------------------------------

    async def interrupt_current(self) -> bool:
        """
        Send SIGINT to the running Claude subprocess.

        SIGINT 让 query() 里的 async for receive_response() 抛异常退出，
        锁释放后我们再 drain 掉残留消息。
        """
        if self._client is None or not self._client_ready:
            return False
        async with self._interrupt_lock:
            try:
                await self._client.interrupt()
                logger.info("[ClaudeIntegration.interrupt_current] interrupt sent, draining...")

                # 等 query() 的 receive_response 退出并释放锁后，再 drain 残留
                async for _ in self._client.receive_response():
                    pass
                logger.info("[ClaudeIntegration.interrupt_current] stream drained")
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
