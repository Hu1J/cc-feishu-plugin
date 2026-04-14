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
        if cli_path == "claude":
            resolved = shutil.which("claude")
            self.cli_path = resolved if resolved else cli_path
        else:
            self.cli_path = cli_path
        self.max_turns = max_turns
        self.approved_directory = approved_directory
        self._options: Any = None  # 持久化的 ClaudeAgentOptions
        self._client: Any = None  # 临时引用，当前 query 的 client
        self._consume_task: asyncio.Task | None = None
        self._system_prompt_append: str | None = None
        self._query_lock = asyncio.Lock()  # 保证同一时间只有一个 query 在执行
        self._interrupt_lock = asyncio.Lock()  # 保证 interrupt 不能重入

    # -------------------------------------------------------------------------
    # Options 初始化
    # -------------------------------------------------------------------------

    def _init_options(self, system_prompt_append: str | None = None,
                      continue_conversation: bool = True) -> None:
        """
        构建持久化 ClaudeAgentOptions，供整个 worker 生命周期复用。
        system prompt 更新只需重新调用此方法。
        """
        from claude_agent_sdk import ClaudeAgentOptions
        from cc_feishu_bridge.claude.memory_tools import get_memory_mcp_server
        from cc_feishu_bridge.claude.feishu_file_tools import get_feishu_file_mcp_server

        memory_server = get_memory_mcp_server()
        feishu_server = get_feishu_file_mcp_server()

        options = ClaudeAgentOptions(
            cwd=self.approved_directory or ".",
            # NOTE: 不传 cli_path，让 SDK 使用内置的 bundled CLI。
            # 显式指定 cli_path 在 Windows 上会导致 initialize() 超时。
            include_partial_messages=True,
            permission_mode="bypassPermissions",
            continue_conversation=continue_conversation,
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

        self._options = options
        self._system_prompt_append = system_prompt_append

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
        每个 query 内部创建独立 client，用完即销毁。
        receive_response() 消费逻辑包进 _consume() 异步函数，
        用 asyncio.create_task 启动，interrupt 时可单独 cancel。
        """
        if self._options is None:
            raise RuntimeError(
                "ClaudeIntegration not initialized. Call _init_options() first."
            )

        import time as time_module

        async with self._query_lock:
            t_query = time_module.time()
            # 每次 query 创建新 client，用完即销毁
            from claude_agent_sdk import ClaudeSDKClient
            async with ClaudeSDKClient(options=self._options) as client:
                # 临时持有 client，让 interrupt_current() 能访问
                self._client = client

                # 发送 prompt
                await client.query(prompt=prompt)

                # 后台消费任务（和官方示例一致）
                async def _consume():
                    result_text = ""
                    result_session_id = None
                    result_cost = 0.0
                    async for message in client.receive_response():
                        msg_type = type(message).__name__
                        if msg_type == "ResultMessage":
                            result_text = getattr(message, "result", "") or ""
                            result_session_id = getattr(message, "session_id", None)
                            result_cost = getattr(message, "total_cost_usd", 0.0) or 0.0
                            elapsed = time_module.time() - t_query
                            logger.info(
                                f"[query] <<< session_id={result_session_id!r}, "
                                f"cost={result_cost!r}, elapsed={elapsed:.1f}s"
                            )
                        if on_stream:
                            parsed = self._parse_message(message)
                            if parsed:
                                await on_stream(parsed)
                    return (result_text, result_session_id, result_cost)

                self._consume_task = asyncio.create_task(_consume())
                result = await self._consume_task

            # async with 退出后 client 已销毁，清除引用
            self._client = None
            self._consume_task = None
            return result

    # -------------------------------------------------------------------------
    # Interrupt
    # -------------------------------------------------------------------------

    async def interrupt_current(self) -> bool:
        """
        和官方示例完全对齐：interrupt + await consume_task。
        两个锁都保留：_query_lock 保证同一时间只有一个 query，
        _interrupt_lock 保证 interrupt 不重入。
        """
        if self._client is None:
            return False

        async with self._interrupt_lock:
            await self._client.interrupt()
            if self._consume_task is not None:
                await self._consume_task
            logger.info("[interrupt_current] done")
            return True

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
