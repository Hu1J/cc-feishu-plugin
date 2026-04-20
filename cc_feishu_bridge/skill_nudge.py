"""Hermes-style skill nudge — triggers skill review after N tool calls.

This module tracks tool call count per session and triggers a background
review when the threshold is reached, asking Claude Code to consider
creating or updating a skill based on recent conversation patterns.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)


@dataclass
class SkillNudgeConfig:
    enabled: bool = True
    interval: int = 10  # trigger after N tool calls


@dataclass
class SkillNudge:
    """Tracks tool call count and triggers review when threshold is hit."""
    config: SkillNudgeConfig
    _count: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _pending: bool = False  # True while a review is in flight

    def reset(self) -> None:
        with self._lock:
            self._count = 0
            self._pending = False

    def increment(self) -> bool:
        """Increment tool call count. Returns True if review should be triggered."""
        if not self.config.enabled:
            return False
        with self._lock:
            if self._pending:
                return False
            self._count += 1
            if self._count >= self.config.interval:
                self._pending = True
                return True
            return False

    def mark_review_done(self) -> None:
        """Call when review is complete to reset counter."""
        with self._lock:
            self._count = 0
            self._pending = False


# Global nudge instance per MessageHandler (set after config is known)
_nudge: SkillNudge | None = None


def make_nudge(config: SkillNudgeConfig) -> SkillNudge:
    global _nudge
    _nudge = SkillNudge(config=config)
    return _nudge


def get_nudge() -> SkillNudge | None:
    return _nudge


# Review prompt shown to Claude Code when nudge fires
SKILL_NUDGE_PROMPT = """\
回顾上面的对话，思考以下问题：

1. 这段对话中有没有值得沉淀为可复用技能（Skill）的做法？
   适合存为 Skill 的场景：
   - 解决了非平凡问题，且解决方法可推广
   - 发现了一种新的工作流程或技巧
   - 克服了错误并找到了正确方法
   - 用户要求记住某个流程

2. 如果已有相关 Skill，有没有学到新东西可以更新它？

3. 如果要创建/更新 Skill，请直接写入文件：
   - 路径：~/.claude/skills/<skill-name>/SKILL.md
   - 格式：YAML frontmatter (name/description/author/version) + Markdown body
   - author 字段填你的用户名，表示这是你自己创建的

注意：
- 只创建真正有价值的 Skill，不要为了"有"而创建
- 如果有相关 Skill 已存在，优先更新它而不是创建新的
- 更新 Skill 时只改正文 instructions，不要动 frontmatter 的 name/description
"""


async def trigger_skill_review(
    make_claude_query: Callable[..., Awaitable[tuple]],
    project_path: str,
) -> None:
    """Trigger a background skill review by calling Claude Code.

    Args:
        make_claude_query: a callable that runs a Claude query and returns
            (response_text, session_id, cost)
        project_path: the current project path for Claude context
    """
    nudge = get_nudge()
    if not nudge or not nudge.config.enabled:
        return

    logger.info("[skill_nudge] triggering skill review")

    try:
        prompt = f"项目路径：{project_path}\n\n{SKILL_NUDGE_PROMPT}"
        response, _, _ = await make_claude_query(prompt=prompt)
        logger.info(f"[skill_nudge] review done: {response[:200] if response else '(empty)'}")
    except Exception as e:
        logger.warning(f"[skill_nudge] review failed: {e}")
    finally:
        if nudge:
            nudge.mark_review_done()
