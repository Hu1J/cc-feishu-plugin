"""Claude Code integration via claude-agent-sdk."""
from __future__ import annotations

import logging
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
        self.cli_path = cli_path
        self.max_turns = max_turns
        self.approved_directory = approved_directory
        self._active_client: Optional[Any] = None

    async def interrupt_current(self) -> bool:
        """Send SIGINT to the running Claude subprocess. Returns True if interrupted."""
        if self._active_client is None:
            return False
        try:
            await self._active_client.interrupt()
            return True
        except Exception:
            return False

    async def query(
        self,
        prompt: str,
        session_id: str | None = None,
        cwd: str | None = None,
        on_stream: StreamCallback | None = None,
    ) -> tuple[str, str | None, float]:
        """
        Send a message to Claude Code and get the response.

        Returns: (response_text, new_session_id, cost_usd)
        """
        try:
            from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

            options = ClaudeAgentOptions(
                cwd=cwd or self.approved_directory or ".",
                max_turns=self.max_turns,
                cli_path=self.cli_path,
                include_partial_messages=True,
                permission_mode="bypassPermissions",
            )

            client = ClaudeSDKClient(options=options)

            if session_id:
                options.continue_conversation = True

            result_text = ""
            result_session_id = session_id
            result_cost = 0.0

            async with client:
                self._active_client = client
                try:
                    await client.query(prompt=prompt, session_id=session_id)

                    async for message in client.receive_response():
                        msg_type = type(message).__name__

                        # Extract result from final ResultMessage
                        if msg_type == "ResultMessage":
                            result_text = getattr(message, "result", "") or ""
                            result_session_id = getattr(message, "session_id", session_id) or session_id
                            result_cost = getattr(message, "total_cost_usd", 0.0) or 0.0

                        if on_stream:
                            parsed = self._parse_message(message)
                            if parsed:
                                await on_stream(parsed)
                finally:
                    self._active_client = None

            return (
                result_text,
                result_session_id,
                result_cost,
            )

        except ImportError:
            logger.error("claude-agent-sdk not installed")
            raise RuntimeError("claude-agent-sdk is required. Install with: pip install claude-agent-sdk")

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
                        tool_input = json.dumps(tool_input)[:200]
                    return ClaudeMessage(
                        content="",
                        is_final=False,
                        tool_name=tool_name,
                        tool_input=tool_input,
                    )

        elif msg_type == "ResultMessage":
            # Result is extracted separately; don't send through stream callback
            return None

        return None