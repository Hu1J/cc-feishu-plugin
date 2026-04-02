import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from unittest.mock import AsyncMock, MagicMock

from cc_feishu_bridge.feishu.message_handler import MessageHandler, StreamAccumulator, HandlerResult
from cc_feishu_bridge.feishu.client import IncomingMessage


def _text_msg(msg_id, text, user_open_id="ou_user1", parent_id="", thread_id=""):
    return IncomingMessage(
        message_id=msg_id,
        chat_id="chat_abc",
        user_open_id=user_open_id,
        content=text,
        message_type="text",
        create_time="1234567890",
        parent_id=parent_id,
        thread_id=thread_id,
    )


def _make_handler():
    from cc_feishu_bridge.security.auth import Authenticator
    from cc_feishu_bridge.security.validator import SecurityValidator
    from cc_feishu_bridge.claude.integration import ClaudeIntegration
    from cc_feishu_bridge.claude.session_manager import SessionManager
    from cc_feishu_bridge.format.reply_formatter import ReplyFormatter

    auth = Authenticator(allowed_users=["ou_user1"])
    validator = SecurityValidator(approved_directory="/tmp")
    claude = MagicMock(spec=ClaudeIntegration)
    sm = MagicMock(spec=SessionManager)
    sm.get_active_session.return_value = None
    fm = MagicMock(spec=ReplyFormatter)

    feishu = MagicMock()
    feishu.add_typing_reaction = AsyncMock(return_value="r_123")
    feishu.remove_typing_reaction = AsyncMock()
    feishu.send_text_reply = AsyncMock()
    feishu.get_message = AsyncMock(return_value=None)

    return MessageHandler(
        feishu_client=feishu,
        authenticator=auth,
        validator=validator,
        claude=claude,
        session_manager=sm,
        formatter=fm,
        approved_directory="/tmp",
        data_dir="/tmp",
    )


def test_handle_queues_message_and_returns_immediately():
    """handle() should return immediately without blocking."""
    handler = _make_handler()
    handler.claude.query = AsyncMock(return_value=("response", None, 0.0))
    handler.feishu.get_message = AsyncMock(return_value=None)

    async def do_handle():
        msg = _text_msg("om_1", "hello")
        # Verify handle returns promptly (does not wait for query to finish)
        import time
        start = time.time()
        result = await handler.handle(msg)
        elapsed = time.time() - start
        assert result.success
        assert elapsed < 0.5, f"handle() took {elapsed:.2f}s — should return immediately"
        # Give worker loop a chance to run
        await asyncio.sleep(0.1)
        # Worker should have processed the message and emptied the queue
        assert handler._get_queue().empty()

    asyncio.get_event_loop().run_until_complete(do_handle())


def test_worker_processes_queued_messages_in_order():
    """Messages should be processed FIFO."""
    handler = _make_handler()
    handler.claude.query = AsyncMock(return_value=("response", None, 0.0))
    handler.feishu.get_message = AsyncMock(return_value=None)

    async def run():
        await handler.handle(_text_msg("om_1", "first"))
        await handler.handle(_text_msg("om_2", "second"))
        await asyncio.sleep(0.5)
        calls = handler.claude.query.call_args_list
        assert len(calls) >= 2
        assert "first" in calls[0][1]["prompt"]
        assert "second" in calls[1][1]["prompt"]

    asyncio.get_event_loop().run_until_complete(run())


def test_stream_accumulator_sends_with_message_id():
    """StreamAccumulator should call send_fn with (chat_id, message_id, text)."""
    sent_args = []

    async def capture_send(chat_id, msg_id, text):
        sent_args.append((chat_id, msg_id, text))

    acc = StreamAccumulator("chat_abc", "om_reply_to", capture_send)
    asyncio.get_event_loop().run_until_complete(acc.add_text("hello"))
    asyncio.get_event_loop().run_until_complete(acc.flush())
    assert sent_args == [("chat_abc", "om_reply_to", "hello")]


def test_stop_cancels_worker():
    """Sending /stop should cancel the running worker."""
    handler = _make_handler()
    handler.claude.query = AsyncMock(side_effect=lambda **kw: asyncio.sleep(10))
    handler.feishu.get_message = AsyncMock(return_value=None)

    async def run():
        await handler.handle(_text_msg("om_1", "test"))
        await asyncio.sleep(0.1)
        stop_result = await handler._handle_stop(_text_msg("om_2", "/stop"))
        assert stop_result.success
        assert handler._worker_task is None

    asyncio.get_event_loop().run_until_complete(run())