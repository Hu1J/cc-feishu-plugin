"""Claude Code integration via claude-agent-sdk."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Awaitable

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
            )

            client = ClaudeSDKClient(options=options)

            if session_id:
                options.continue_session = True

            result_text = ""
            result_session_id = session_id
            result_cost = 0.0

            async with client:
                async for event in await client.query(prompt=prompt, session_id=session_id):
                    if on_stream:
                        msg = self._parse_event(event)
                        if msg:
                            await on_stream(msg)

                # Get result inside the async with block before exiting
                result = await client.get_result()
                if result:
                    result_text = result.result or ""
                    result_session_id = result.session_id
                    result_cost = result.total_cost_usd or 0.0

            return (
                result_text,
                result_session_id,
                result_cost,
            )

        except ImportError:
            logger.error("claude-agent-sdk not installed")
            raise RuntimeError("claude-agent-sdk is required. Install with: pip install claude-agent-sdk")

    def _parse_event(self, event) -> ClaudeMessage | None:
        """Parse SDK event into ClaudeMessage."""
        event_type = getattr(event, "type", None)

        if event_type == "stream_delta":
            content = getattr(event, "content", "")
            if content:
                return ClaudeMessage(content=content, is_final=False)

        elif event_type == "assistant":
            content = getattr(event, "content", "")
            if content:
                return ClaudeMessage(content=content, is_final=False)

        elif event_type == "tool_use":
            tool_name = getattr(event, "name", "Unknown")
            tool_input = getattr(event, "input", "")
            if isinstance(tool_input, dict):
                import json
                tool_input = json.dumps(tool_input)[:200]
            return ClaudeMessage(
                content="",
                is_final=False,
                tool_name=tool_name,
                tool_input=tool_input,
            )

        return None