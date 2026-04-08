import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from cc_feishu_bridge.feishu.should_respond import _is_bot_mentioned
from cc_feishu_bridge.feishu.client import IncomingMessage

BOT_OPEN_ID = "ou_bot"

def make_group_message(chat_id, raw_content, user_open_id="ou_member1"):
    return IncomingMessage(
        message_id="msg1",
        chat_id=chat_id,
        user_open_id=user_open_id,
        content="hello",
        message_type="text",
        create_time="123456",
        raw_content=raw_content,
        chat_type="group",
    )

def make_p2p_message(user_open_id="ou_user1"):
    return IncomingMessage(
        message_id="msg2",
        chat_id="och_p2p",
        user_open_id=user_open_id,
        content="hello",
        message_type="text",
        create_time="123456",
        raw_content='{"text":"hi"}',
        chat_type="p2p",
    )


class TestPreferenceInjectionCondition:
    """测试偏好注入条件判断逻辑"""

    def test_p2p_should_inject(self):
        """P2P 私聊 → 应注入偏好"""
        msg = make_p2p_message()
        should_inject = (
            msg.chat_type == "p2p"
            or _is_bot_mentioned(msg.raw_content, BOT_OPEN_ID)
        )
        assert should_inject is True

    def test_group_mention_mode_mentioned_should_inject(self):
        """群聊 mention 模式，被 @ → 应注入偏好"""
        raw = '{"text":"@Claude hello","mentions":[{"open_id":"ou_bot","name":"Claude"}]}'
        msg = make_group_message("och_group1", raw)
        should_inject = (
            msg.chat_type == "p2p"
            or _is_bot_mentioned(msg.raw_content, BOT_OPEN_ID)
        )
        assert should_inject is True

    def test_group_open_mode_mentioned_should_inject(self):
        """群聊 open 模式，被 @ → 应注入偏好"""
        raw = '{"text":"@Claude hi","mentions":[{"open_id":"ou_bot","name":"Claude"}]}'
        msg = make_group_message("och_group2", raw)
        should_inject = (
            msg.chat_type == "p2p"
            or _is_bot_mentioned(msg.raw_content, BOT_OPEN_ID)
        )
        assert should_inject is True

    def test_group_open_mode_no_mention_should_not_inject(self):
        """群聊 open 模式，未被 @ → 不应注入偏好"""
        raw = '{"text":"hello world"}'
        msg = make_group_message("och_group3", raw)
        should_inject = (
            msg.chat_type == "p2p"
            or _is_bot_mentioned(msg.raw_content, BOT_OPEN_ID)
        )
        assert should_inject is False

    def test_group_mention_mode_not_mentioned_should_not_inject(self):
        """群聊 mention 模式，未被 @ → 不应注入偏好（should_respond 已返回 False）"""
        raw = '{"text":"just chat"}'
        msg = make_group_message("och_group4", raw)
        should_inject = (
            msg.chat_type == "p2p"
            or _is_bot_mentioned(msg.raw_content, BOT_OPEN_ID)
        )
        assert should_inject is False