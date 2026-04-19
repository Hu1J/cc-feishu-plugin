"""Tests for group chat support: mention detection, access control, session isolation."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestGroupChatMentionDetection:
    """Test mention detection from Feishu event mentions[] array."""

    def test_group_chat_event_with_bot_mention_sets_mention_bot_true(self):
        """When bot is @mentioned in group chat, mention_bot=True."""
        from cc_feishu_bridge.feishu.ws_client import FeishuWSClient

        cb = AsyncMock()
        client = FeishuWSClient(
            app_id="id",
            app_secret="secret",
            bot_open_id="ou_bot123",
            on_message=cb,
        )

        mock_event = MagicMock()
        mock_event.event.message.message_id = "msg_1"
        mock_event.event.message.chat_id = "oc_group_abc"
        mock_event.event.message.chat_type = "group"
        mock_event.event.message.msg_type = "text"
        mock_event.event.message.content = '{"text":"@_user_1 帮我查下"}'
        mock_event.event.message.create_time = "1234567890"
        mock_event.event.message.parent_id = ""
        mock_event.event.message.thread_id = ""
        mock_event.event.message.mentions = [
            MagicMock(
                key="@_user_1",
                id=MagicMock(open_id="ou_bot123"),
                name="CC",
            )
        ]

        mock_sender = MagicMock()
        mock_sender.sender_id.open_id = "ou_user_xyz"
        mock_event.event.sender = mock_sender

        async def run_test():
            client._handle_p2p_message(mock_event)
            await asyncio.sleep(0)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run_test())
        finally:
            asyncio.set_event_loop(None)
            loop.close()

        cb.assert_called_once()
        msg = cb.call_args[0][0]
        assert msg.is_group_chat is True
        assert msg.chat_type == "group"
        assert msg.mention_bot is True
        assert msg.mention_ids == ["ou_bot123"]

    def test_group_chat_event_without_mention_sets_mention_bot_false(self):
        """Group chat message without @CC has mention_bot=False."""
        from cc_feishu_bridge.feishu.ws_client import FeishuWSClient

        cb = AsyncMock()
        client = FeishuWSClient(
            app_id="id",
            app_secret="secret",
            bot_open_id="ou_bot123",
            on_message=cb,
        )

        mock_event = MagicMock()
        mock_event.event.message.message_id = "msg_2"
        mock_event.event.message.chat_id = "oc_group_abc"
        mock_event.event.message.chat_type = "group"
        mock_event.event.message.msg_type = "text"
        mock_event.event.message.content = '{"text":"大家好"}'
        mock_event.event.message.create_time = "1234567890"
        mock_event.event.message.parent_id = ""
        mock_event.event.message.thread_id = ""
        mock_event.event.message.mentions = []

        mock_sender = MagicMock()
        mock_sender.sender_id.open_id = "ou_user_xyz"
        mock_event.event.sender = mock_sender

        async def run_test():
            client._handle_p2p_message(mock_event)
            await asyncio.sleep(0)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run_test())
        finally:
            asyncio.set_event_loop(None)
            loop.close()

        cb.assert_called_once()
        msg = cb.call_args[0][0]
        assert msg.is_group_chat is True
        assert msg.mention_bot is False
        assert msg.mention_ids == []

    def test_p2p_event_still_works(self):
        """P2P messages are not treated as group chat."""
        from cc_feishu_bridge.feishu.ws_client import FeishuWSClient

        cb = AsyncMock()
        client = FeishuWSClient(
            app_id="id",
            app_secret="secret",
            bot_open_id="ou_bot123",
            on_message=cb,
        )

        mock_event = MagicMock()
        mock_event.event.message.message_id = "msg_3"
        mock_event.event.message.chat_id = "p2p_abc"
        mock_event.event.message.chat_type = "p2p"
        mock_event.event.message.msg_type = "text"
        mock_event.event.message.content = '{"text":"hello"}'
        mock_event.event.message.create_time = "1234567890"
        mock_event.event.message.parent_id = ""
        mock_event.event.message.thread_id = ""
        mock_event.event.message.mentions = []

        mock_sender = MagicMock()
        mock_sender.sender_id.open_id = "ou_user_xyz"
        mock_event.event.sender = mock_sender

        async def run_test():
            client._handle_p2p_message(mock_event)
            await asyncio.sleep(0)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run_test())
        finally:
            asyncio.set_event_loop(None)
            loop.close()

        cb.assert_called_once()
        msg = cb.call_args[0][0]
        assert msg.is_group_chat is False
        assert msg.chat_type == "p2p"
        assert msg.mention_bot is False


class TestGroupAccessControl:
    """Test per-group access control via _check_group_access."""

    def test_no_group_config_defaults_to_require_mention(self):
        """With no group config, mention is required."""
        from cc_feishu_bridge.feishu.message_handler import MessageHandler

        handler = MessageHandler(
            feishu_client=MagicMock(),
            authenticator=MagicMock(),
            validator=MagicMock(),
            claude=MagicMock(),
            session_manager=MagicMock(),
            formatter=MagicMock(),
            approved_directory="/tmp",
            feishu_groups={},
        )

        # Group message with mention → allowed
        msg_with_mention = MagicMock()
        msg_with_mention.is_group_chat = True
        msg_with_mention.chat_id = "oc_unknown_group"
        msg_with_mention.mention_bot = True
        msg_with_mention.user_open_id = "ou_user"
        assert handler._check_group_access(msg_with_mention) is True

        # Group message without mention → denied
        msg_no_mention = MagicMock()
        msg_no_mention.is_group_chat = True
        msg_no_mention.chat_id = "oc_unknown_group"
        msg_no_mention.mention_bot = False
        msg_no_mention.user_open_id = "ou_user"
        assert handler._check_group_access(msg_no_mention) is False

    def test_disabled_group_rejects_all(self):
        """Group with enabled=False is always rejected."""
        from cc_feishu_bridge.feishu.message_handler import MessageHandler
        from cc_feishu_bridge.config import GroupConfigEntry

        handler = MessageHandler(
            feishu_client=MagicMock(),
            authenticator=MagicMock(),
            validator=MagicMock(),
            claude=MagicMock(),
            session_manager=MagicMock(),
            formatter=MagicMock(),
            approved_directory="/tmp",
            feishu_groups={
                "oc_disabled_group": GroupConfigEntry(enabled=False),
            },
        )

        msg = MagicMock()
        msg.is_group_chat = True
        msg.chat_id = "oc_disabled_group"
        msg.mention_bot = True
        msg.user_open_id = "ou_user"
        assert handler._check_group_access(msg) is False

    def test_require_mention_false_bypasses_mention_check(self):
        """Group with require_mention=False responds to all group messages."""
        from cc_feishu_bridge.feishu.message_handler import MessageHandler
        from cc_feishu_bridge.config import GroupConfigEntry

        handler = MessageHandler(
            feishu_client=MagicMock(),
            authenticator=MagicMock(),
            validator=MagicMock(),
            claude=MagicMock(),
            session_manager=MagicMock(),
            formatter=MagicMock(),
            approved_directory="/tmp",
            feishu_groups={
                "oc_open_group": GroupConfigEntry(enabled=True, require_mention=False),
            },
        )

        msg = MagicMock()
        msg.is_group_chat = True
        msg.chat_id = "oc_open_group"
        msg.mention_bot = False  # Not mentioned
        msg.user_open_id = "ou_user"
        assert handler._check_group_access(msg) is True

    def test_allow_from_restricts_sender(self):
        """Group with allow_from only allows listed users."""
        from cc_feishu_bridge.feishu.message_handler import MessageHandler
        from cc_feishu_bridge.config import GroupConfigEntry

        handler = MessageHandler(
            feishu_client=MagicMock(),
            authenticator=MagicMock(),
            validator=MagicMock(),
            claude=MagicMock(),
            session_manager=MagicMock(),
            formatter=MagicMock(),
            approved_directory="/tmp",
            feishu_groups={
                "oc_private_group": GroupConfigEntry(enabled=True, allow_from=["ou_allowed_user"]),
            },
        )

        # Allowed user → passes
        allowed_msg = MagicMock()
        allowed_msg.is_group_chat = True
        allowed_msg.chat_id = "oc_private_group"
        allowed_msg.mention_bot = True
        allowed_msg.user_open_id = "ou_allowed_user"
        assert handler._check_group_access(allowed_msg) is True

        # Non-allowed user → rejected
        denied_msg = MagicMock()
        denied_msg.is_group_chat = True
        denied_msg.chat_id = "oc_private_group"
        denied_msg.mention_bot = True
        denied_msg.user_open_id = "ou_stranger"
        assert handler._check_group_access(denied_msg) is False

    def test_p2p_message_passes_without_check(self):
        """P2P messages always pass group access check."""
        from cc_feishu_bridge.feishu.message_handler import MessageHandler

        handler = MessageHandler(
            feishu_client=MagicMock(),
            authenticator=MagicMock(),
            validator=MagicMock(),
            claude=MagicMock(),
            session_manager=MagicMock(),
            formatter=MagicMock(),
            approved_directory="/tmp",
            feishu_groups={},
        )

        msg = MagicMock()
        msg.is_group_chat = False
        msg.chat_id = "p2p_abc"
        msg.mention_bot = False
        msg.user_open_id = "ou_user"
        assert handler._check_group_access(msg) is True
