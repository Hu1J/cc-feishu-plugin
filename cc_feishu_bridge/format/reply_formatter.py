"""Format Claude's Markdown response for Feishu."""
from __future__ import annotations

import re

FEISHU_MAX_MESSAGE_LENGTH = 4096


class ReplyFormatter:
    def __init__(self):
        self.tool_icons = {
            "Read": "📖",
            "Write": "✏️",
            "Edit": "🔧",
            "Bash": "💻",
            "Glob": "🔍",
            "Grep": "🔎",
            "WebFetch": "🌐",
            "WebSearch": "🌐",
            "Task": "📋",
        }

    def format_text(self, text: str) -> str:
        """Convert Markdown to Feishu-compatible text."""
        if not text:
            return ""
        # Remove markdown code block fences for inline code
        text = re.sub(r"```\w*\n?", "", text)
        text = re.sub(r"`([^`]+)`", r"`\1`", text)
        # Bold
        text = re.sub(r"\*\*(.+?)\*\*", r"**\1**", text)
        # Escape special Feishu chars that interfere with parse_mode
        text = re.sub(r"@", "\\@", text)
        return text.strip()

    def format_tool_call(self, tool_name: str, tool_input: str | None = None) -> str:
        """Format a tool call notification for the user."""
        icon = self.tool_icons.get(tool_name, "🤖")
        msg = f"{icon} **{tool_name}**"
        if tool_input:
            # Send complete input to Feishu (split if needed to respect message limit)
            if len(tool_input) <= FEISHU_MAX_MESSAGE_LENGTH - len(msg) - 5:
                msg += f"\n`{tool_input}`"
            else:
                # Split into chunks if tool_input is very long
                chunks = self.split_messages(tool_input)
                for chunk in chunks:
                    msg += f"\n`{chunk}`"
        return msg

    def split_messages(self, text: str) -> list[str]:
        """Split long text into chunks under Feishu's limit."""
        if len(text) <= FEISHU_MAX_MESSAGE_LENGTH:
            return [text] if text else []

        chunks = []
        lines = text.split("\n")
        current = ""

        for line in lines:
            if len(current) + len(line) + 1 <= FEISHU_MAX_MESSAGE_LENGTH:
                current += line + "\n"
            else:
                if current:
                    chunks.append(current.rstrip())
                # If single line exceeds limit, split by chars
                if len(line) > FEISHU_MAX_MESSAGE_LENGTH:
                    while len(line) > FEISHU_MAX_MESSAGE_LENGTH:
                        chunks.append(line[:FEISHU_MAX_MESSAGE_LENGTH])
                        line = line[FEISHU_MAX_MESSAGE_LENGTH:]
                    current = line + "\n"
                else:
                    current = line + "\n"

        if current.strip():
            chunks.append(current.rstrip())

        return [c for c in chunks if c.strip()]