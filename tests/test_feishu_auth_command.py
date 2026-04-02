"""Integration tests for /stop and /feishu auth commands."""
import pytest, asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from cc_feishu_bridge.feishu.message_handler import MessageHandler, HandlerResult
from cc_feishu_bridge.feishu.client import IncomingMessage


class FakeSession:
    session_id = "sess_test"
    sdk_session_id = None
    user_id = "ou_test"
    chat_id = "oc_test"
    project_path = "/tmp"
    created_at = None
    last_used = None
    total_cost = 0.0
    message_count = 0


@pytest.fixture
def handler():
    """Build a minimal MessageHandler with all dependencies mocked."""
    from cc_feishu_bridge.feishu.client import FeishuClient
    from cc_feishu_bridge.security.auth import Authenticator
    from cc_feishu_bridge.security.validator import SecurityValidator
    from cc_feishu_bridge.claude.integration import ClaudeIntegration
    from cc_feishu_bridge.claude.session_manager import SessionManager
    from cc_feishu_bridge.format.reply_formatter import ReplyFormatter
    import datetime

    # Use plain MagicMock without spec to avoid call_args interference
    feishu = MagicMock()
    feishu.app_id = "app_123"
    feishu.app_secret = "sec_456"
    feishu.send_text = AsyncMock(return_value="msg_ok")
    feishu.send_interactive = AsyncMock(return_value="msg_card")
    feishu.update_message = AsyncMock()
    feishu.add_typing_reaction = AsyncMock(return_value="rx_123")
    feishu.remove_typing_reaction = AsyncMock()
    feishu.get_message = AsyncMock(return_value=None)
    feishu.send_text_reply = AsyncMock(return_value="msg_reply_ok")

    auth = MagicMock()
    auth.authenticate.return_value = MagicMock(authorized=True)

    validator = MagicMock()
    validator.validate.return_value = (True, None)

    claude = MagicMock()
    claude.interrupt_current = AsyncMock(return_value=True)
    claude.query = AsyncMock(return_value=("Claude response text", None, 0.0))

    sessions = MagicMock()
    sessions.get_active_session.return_value = MagicMock(
        session_id="sess_test", sdk_session_id=None,
        user_id="ou_test", chat_id="oc_test",
        project_path="/tmp", created_at=datetime.datetime.now(),
        last_used=datetime.datetime.now(), total_cost=0.0, message_count=0
    )

    formatter = MagicMock()
    formatter.format_text.side_effect = lambda x: x
    formatter.split_messages.side_effect = lambda x: [x] if x else []
    formatter.format_tool_call.return_value = "🔧 Tool"

    handler = MessageHandler(
        feishu_client=feishu,
        authenticator=auth,
        validator=validator,
        claude=claude,
        session_manager=sessions,
        formatter=formatter,
        approved_directory="/tmp",
        data_dir="/tmp",
    )
    return handler


def make_msg(content: str) -> IncomingMessage:
    return IncomingMessage(
        message_id="om_test",
        chat_id="oc_test",
        user_open_id="ou_test",
        content=content,
        message_type="text",
        create_time="",
        parent_id="",
        thread_id="",
    )


@pytest.mark.asyncio
async def test_feishu_auth_command_triggers_flow(handler):
    """Sending /feishu auth should start auth flow and return immediately."""
    msg = make_msg("/feishu auth")
    with patch("cc_feishu_bridge.feishu.auth_flow.run_auth_flow") as mock_flow:
        # Commands are handled immediately in handle() — no queue involved
        await handler.handle(msg)
        mock_flow.assert_called_once()
        call_kwargs = mock_flow.call_args.kwargs
        assert call_kwargs["user_open_id"] == "ou_test"
        assert call_kwargs["chat_id"] == "oc_test"
        assert call_kwargs["message_id"] == "om_test"
        assert call_kwargs["app_id"] == "app_123"
        assert "im:message" in call_kwargs["scopes"]


@pytest.mark.asyncio
async def test_feishu_help_command(handler):
    """Sending /feishu without subcommand should send help text via reply."""
    msg = make_msg("/feishu")
    # Commands are handled immediately in handle() — no queue involved
    await handler.handle(msg)
    # send_text_reply(chat_id, text, reply_to_message_id) — text is 2nd positional arg
    handler.feishu.send_text_reply.assert_called()
    call_args = handler.feishu.send_text_reply.call_args
    _, text, _ = call_args[0]
    assert "cc-feishu-bridge" in text
    assert "/new" in text
    assert "/status" in text
    assert "/stop" in text
    assert "/feishu auth" in text


@pytest.mark.asyncio
async def test_unknown_command_returns_error(handler):
    """Unknown / command should send error text via reply."""
    msg = make_msg("/foobar")
    # Commands are handled immediately in handle() — no queue involved
    await handler.handle(msg)
    handler.feishu.send_text_reply.assert_called()
    _, text, _ = handler.feishu.send_text_reply.call_args[0]
    assert "未知命令" in text


@pytest.mark.asyncio
async def test_stop_command_when_no_active_query(handler):
    """Sending /stop when no query is running should send no-active-query message."""
    handler._worker_task = None
    msg = make_msg("/stop")
    # Call _handle_stop directly to bypass the queue/worker mechanics
    result = await handler._handle_stop(msg)
    assert result.success
    handler.feishu.send_text_reply.assert_called()
    _, text, _ = handler.feishu.send_text_reply.call_args[0]
    assert "当前没有正在运行的查询" in text
    handler.claude.interrupt_current.assert_not_called()


@pytest.mark.asyncio
async def test_stop_command_interrupts_active_query(handler):
    """Sending /stop while a query is running should interrupt it."""
    handler._worker_task = None
    # Set up a real background task — simulates an actively-running query
    async def dummy_task():
        await asyncio.sleep(10)

    handler._worker_task = asyncio.create_task(dummy_task())
    # Give the task a chance to actually start
    await asyncio.sleep(0)

    msg = make_msg("/stop")
    result = await handler._handle_stop(msg)
    assert result.success
    handler.claude.interrupt_current.assert_called_once()
    assert handler._worker_task is None