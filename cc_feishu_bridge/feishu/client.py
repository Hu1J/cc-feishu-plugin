"""Feishu/Lark Open Platform client for receiving and sending messages."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def _stream_to_buffer(stream) -> bytes:
    """Consume a Readable stream into a bytes buffer."""
    chunks = []

    def add_chunk(chunk):
        chunks.append(chunk)

    def done(_):
        pass

    def error(e):
        raise e

    stream.on("data", add_chunk)
    stream.on("end", done)
    stream.on("error", error)

    # Synchronous read for use with asyncio.to_thread
    result = b"".join(chunks)
    return result


def _extract_buffer_from_response(response) -> bytes:
    """Extract binary buffer from lark-oapi response.

    The Feishu SDK can return binary data in several shapes:
      - A Buffer directly
      - An ArrayBuffer
      - A response object with .data as Buffer/ArrayBuffer
      - A response object with .getReadableStream()
      - A response object with .writeFile(path)
      - An async iterable / iterator
      - A Node.js Readable stream
    """
    import io

    # Direct Buffer
    if isinstance(response, (bytes, bytearray)):
        return bytes(response)

    # ArrayBuffer
    if isinstance(response, memoryview):
        return bytes(response)

    resp = response
    content_type = None
    if hasattr(resp, "headers"):
        content_type = resp.headers.get("content-type") or resp.headers.get("Content-Type")

    # Response with .data as Buffer or ArrayBuffer
    if hasattr(resp, "data"):
        data = resp.data
        if isinstance(data, bytes):
            return data
        if isinstance(data, memoryview):
            return bytes(data)
        if isinstance(data, io.BytesIO):
            return data.getvalue()
        # .data might be a readable stream
        if callable(getattr(data, "pipe", None)):
            return _stream_to_buffer(data)

    # Response with .getReadableStream()
    if callable(getattr(resp, "get_readable_stream", None)):
        try:
            stream = resp.get_readable_stream()
            return _stream_to_buffer(stream)
        except Exception:
            pass

    # Response with .getvalue() — e.g. .data.file.getvalue()
    if callable(getattr(resp, "getvalue", None)):
        try:
            return resp.getvalue()
        except Exception:
            pass

    # Node.js Readable stream (has .pipe method)
    if callable(getattr(resp, "pipe", None)):
        return _stream_to_buffer(resp)

    raise RuntimeError(
        f"[feishu] Unable to extract binary data from response: "
        f"unrecognised format (type={type(response).__name__})"
    )


@dataclass
class IncomingMessage:
    """Parsed incoming message from Feishu."""
    message_id: str
    chat_id: str
    user_open_id: str
    content: str           # processed text content
    message_type: str      # "text", "image", "file", "audio", etc.
    create_time: str
    parent_id: str = ""    # 被引用消息的 ID（用户引用/回复某条消息时）
    thread_id: str = ""    # 所在线程的 ID
    raw_content: str = ""  # 原始 JSON 字符串（用于调试和记忆增强）
    chat_type: str = "p2p"  # "p2p" 或 "group"


class FeishuClient:
    def __init__(
        self,
        app_id: str,
        app_secret: str,
        bot_name: str = "Claude",
        data_dir: str = "",
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.bot_name = bot_name
        self.data_dir = data_dir
        self._client = None

    def _get_client(self):
        if self._client is None:
            import lark_oapi as lark
            self._client = (
                lark.Client.builder()
                .app_id(self.app_id)
                .app_secret(self.app_secret)
                .log_level(lark.LogLevel.INFO)
                .build()
            )
        return self._client

    async def get_bot_open_id(self) -> str:
        """Get this bot's open_id from the Bot Info API."""
        import lark_oapi as lark
        import json as json_module
        from lark_oapi.core.model import BaseRequest

        client = self._get_client()

        # lark-oapi 1.5.x removed GetBotInfoRequest; use a raw BaseRequest instead
        class BotInfoRequest(BaseRequest):
            def __init__(inner_self):
                super().__init__()
                inner_self.http_method = lark.HttpMethod.GET
                inner_self.uri = "/open-apis/im/v1/bot_info"
                inner_self.token_types = {lark.AccessTokenType.TENANT}

        request = BotInfoRequest()
        try:
            response = await asyncio.to_thread(client.request, request)
            if response.code == 0 and response.raw and response.raw.content:
                data = json_module.loads(response.raw.content.decode("utf-8"))
                return data.get("data", {}).get("bot", {}).get("open_id", "")
        except Exception as e:
            logger.warning(f"get_bot_open_id() failed: {e}")
        return ""

    async def send_text(self, chat_id: str, text: str) -> str:
        """Send a text message to a chat. Returns message_id."""
        import json
        import lark_oapi as lark
        client = self._get_client()
        request = (
            lark.im.v1.CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                lark.im.v1.CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .content(json.dumps({"text": text}))
                .msg_type("text")
                .build()
            )
            .build()
        )
        response = await asyncio.to_thread(
            client.im.v1.message.create,
            request,
        )
        if not response.success():
            raise RuntimeError(f"Failed to send message: {response.msg}")
        return response.data.message_id

    async def send_text_by_open_id(
        self,
        user_open_id: str,
        text: str,
        reply_to_message_id: str | None = None,
    ) -> str:
        """Send a text message to a specific user by open_id (for group @mention replies).

        In group chats, replying to a user mention requires sending to their open_id
        rather than the group chat_id. Feishu displays this as an @mention to the user.
        """
        import json
        import lark_oapi as lark
        client = self._get_client()

        if reply_to_message_id:
            request = (
                lark.im.v1.ReplyMessageRequest.builder()
                .message_id(reply_to_message_id)
                .request_body(
                    lark.im.v1.ReplyMessageRequestBody.builder()
                    .receive_id(user_open_id)
                    .content(json.dumps({"text": text}))
                    .msg_type("text")
                    .build()
                )
                .build()
            )
            response = await asyncio.to_thread(client.im.v1.message.reply, request)
        else:
            request = (
                lark.im.v1.CreateMessageRequest.builder()
                .receive_id_type("open_id")
                .request_body(
                    lark.im.v1.CreateMessageRequestBody.builder()
                    .receive_id(user_open_id)
                    .content(json.dumps({"text": text}))
                    .msg_type("text")
                    .build()
                )
                .build()
            )
            response = await asyncio.to_thread(client.im.v1.message.create, request)

        if not response.success():
            raise RuntimeError(f"Failed to send message to open_id: {response.msg}")
        return response.data.message_id

    async def get_message(self, message_id: str) -> dict | None:
        """Fetch a message by ID. Returns a plain dict or None on failure.

        The returned dict has the shape:
            {"msg_type": str, "content": str, "sender_id": str}
        """
        import lark_oapi as lark
        client = self._get_client()
        request = (
            lark.im.v1.GetMessageRequest.builder()
            .message_id(message_id)
            .build()
        )
        response = await asyncio.to_thread(client.im.v1.message.get, request)
        if not response.success():
            logger.warning(f"get_message({message_id}) failed: {response.msg}")
            return None
        if not (response.data and response.data.items):
            return None
        item = response.data.items[0]
        return {
            "msg_type": item.msg_type,
            "content": item.body.content if item.body else "",
            "sender_id": item.sender.id if item.sender else "",
        }

    async def add_typing_reaction(self, message_id: str) -> str | None:
        """Add a typing emoji reaction to a message (Feishu typing indicator).

        Feishu has no dedicated typing REST API. The official plugin uses a
        'Typing' emoji reaction on the user's message instead.
        Silently returns None on failure — this is best-effort.
        """
        import lark_oapi as lark
        client = self._get_client()
        request = (
            lark.im.v1.CreateMessageReactionRequest.builder()
            .message_id(message_id)
            .request_body(
                lark.im.v1.CreateMessageReactionRequestBody.builder()
                .reaction_type(
                    lark.im.v1.model.emoji.Emoji.builder()
                    .emoji_type("Typing")
                    .build()
                )
                .build()
            )
            .build()
        )
        try:
            response = await asyncio.to_thread(
                client.im.v1.message_reaction.create,
                request,
            )
            if response.success():
                return response.data.reaction_id
        except Exception:
            pass
        return None

    async def remove_typing_reaction(self, message_id: str, reaction_id: str) -> None:
        """Remove a typing emoji reaction from a message. Silently ignores failures."""
        import lark_oapi as lark
        client = self._get_client()
        request = (
            lark.im.v1.DeleteMessageReactionRequest.builder()
            .message_id(message_id)
            .reaction_id(reaction_id)
            .build()
        )
        try:
            await asyncio.to_thread(
                client.im.v1.message_reaction.delete,
                request,
            )
        except Exception:
            pass

    async def download_media(self, message_id: str, file_key: str, msg_type: str = "image") -> bytes:
        """Download media (image/file) from a Feishu message."""
        import lark_oapi as lark
        client = self._get_client()
        request = (
            lark.im.v1.GetMessageResourceRequest.builder()
            .message_id(message_id)
            .file_key(file_key)
            .type(msg_type)
            .build()
        )
        try:
            response = await asyncio.to_thread(client.im.v1.message_resource.get, request)
            if not response.success():
                raise RuntimeError(f"Failed to download media: {response.msg}")
            # lark-oapi returns response.file as BytesIO — use .read()
            return response.file.read()
        except Exception as e:
            logger.error(f"download_media error: {e}")
            raise

    async def upload_image(self, image_bytes: bytes, image_type: str = "message") -> str:
        """Upload an image to Feishu and return the image_key."""
        import io
        import lark_oapi as lark
        client = self._get_client()
        request = (
            lark.im.v1.CreateImageRequest.builder()
            .request_body(
                lark.im.v1.CreateImageRequestBody.builder()
                .image(io.BytesIO(image_bytes))
                .image_type(image_type)
                .build()
            )
            .build()
        )
        try:
            response = await asyncio.to_thread(client.im.v1.image.create, request)
            if not response.success():
                raise RuntimeError(f"Failed to upload image: {response.msg}")
            logger.info(f"Uploaded image: {response.data.image_key}")
            return response.data.image_key
        except Exception as e:
            logger.error(f"upload_image error: {e}")
            raise

    async def send_image(self, chat_id: str, image_key: str) -> str:
        """Send an image message to a Feishu chat."""
        import json
        import lark_oapi as lark
        client = self._get_client()
        request = (
            lark.im.v1.CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                lark.im.v1.CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .content(json.dumps({"image_key": image_key}))
                .msg_type("image")
                .build()
            )
            .build()
        )
        try:
            response = await asyncio.to_thread(client.im.v1.message.create, request)
            if not response.success():
                raise RuntimeError(f"Failed to send image: {response.msg}")
            logger.info(f"Sent image to {chat_id}: {response.data.message_id}")
            return response.data.message_id
        except Exception as e:
            logger.error(f"send_image error: {e}")
            raise

    async def upload_file(self, file_bytes: bytes, file_name: str, file_type: str | None) -> str:
        """Upload a file to Feishu and return the file_key."""
        import io
        import lark_oapi as lark
        client = self._get_client()
        request = (
            lark.im.v1.CreateFileRequest.builder()
            .request_body(
                lark.im.v1.CreateFileRequestBody.builder()
                .file(io.BytesIO(file_bytes))
                .file_name(file_name)
                .file_type(file_type or "stream")
                .build()
            )
            .build()
        )
        try:
            response = await asyncio.to_thread(client.im.v1.file.create, request)
            if not response.success():
                logger.error(f"upload_file raw response: {response}")
                raise RuntimeError(f"Failed to upload file: {response.msg}")
            logger.info(f"Uploaded file: {response.data.file_key} ({file_name})")
            return response.data.file_key
        except Exception as e:
            logger.error(f"upload_file error: {e}")
            raise

    async def send_file(self, chat_id: str, file_key: str, file_name: str) -> str:
        """Send a file message to a Feishu chat."""
        import json
        import lark_oapi as lark
        client = self._get_client()
        request = (
            lark.im.v1.CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                lark.im.v1.CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .content(json.dumps({"file_key": file_key, "file_name": file_name}))
                .msg_type("file")
                .build()
            )
            .build()
        )
        try:
            response = await asyncio.to_thread(client.im.v1.message.create, request)
            if not response.success():
                raise RuntimeError(f"Failed to send file: {response.msg}")
            logger.info(f"Sent file {file_name} to {chat_id}: {response.data.message_id}")
            return response.data.message_id
        except Exception as e:
            logger.error(f"send_file error: {e}")
            raise

    async def send_interactive(self, chat_id: str, card: dict, reply_to_message_id: str) -> str:
        """Send an interactive card message, replying to a specific message."""
        import json
        import lark_oapi as lark
        client = self._get_client()
        request = (
            lark.im.v1.ReplyMessageRequest.builder()
            .message_id(reply_to_message_id)
            .request_body(
                lark.im.v1.ReplyMessageRequestBody.builder()
                .content(json.dumps(card))
                .msg_type("interactive")
                .build()
            )
            .build()
        )
        response = await asyncio.to_thread(client.im.v1.message.reply, request)
        if not response.success():
            raise RuntimeError(f"Failed to send card: {response.msg}")
        return response.data.message_id

    async def send_text_reply(
        self,
        chat_id: str,
        text: str,
        reply_to_message_id: str,
    ) -> str:
        """Send a text message as a threaded reply to a specific message."""
        import json
        import lark_oapi as lark
        client = self._get_client()
        request = (
            lark.im.v1.ReplyMessageRequest.builder()
            .message_id(reply_to_message_id)
            .request_body(
                lark.im.v1.ReplyMessageRequestBody.builder()
                .content(json.dumps({"text": text}))
                .msg_type("text")
                .build()
            )
            .build()
        )
        response = await asyncio.to_thread(client.im.v1.message.reply, request)
        if not response.success():
            raise RuntimeError(f"Failed to reply: {response.msg}")
        logger.info(f"Replied to {reply_to_message_id} in chat {chat_id}: {response.data.message_id}")
        return response.data.message_id

    async def send_post_reply(
        self,
        chat_id: str,
        markdown_text: str,
        reply_to_message_id: str,
        log_reply: bool = True,
    ) -> str:
        """Send a markdown message as a threaded reply using Feishu post format.

        The text is rendered with Feishu's built-in markdown renderer (bold, code,
        tables, links, etc.) inside a rich text bubble.
        """
        import json
        import lark_oapi as lark
        client = self._get_client()
        content_payload = json.dumps({
            "zh_cn": {
                "content": [[{"tag": "md", "text": markdown_text}]]
            }
        })
        request = (
            lark.im.v1.ReplyMessageRequest.builder()
            .message_id(reply_to_message_id)
            .request_body(
                lark.im.v1.ReplyMessageRequestBody.builder()
                .content(content_payload)
                .msg_type("post")
                .build()
            )
            .build()
        )
        response = await asyncio.to_thread(client.im.v1.message.reply, request)
        if not response.success():
            raise RuntimeError(f"Failed to reply (post): {response.msg}")
        if log_reply:
            logger.info(f"Replied post to {reply_to_message_id} in chat {chat_id}: {response.data.message_id}")
        return response.data.message_id

    async def send_interactive_reply(
        self,
        chat_id: str,
        markdown_text: str,
        reply_to_message_id: str,
        log_reply: bool = True,
    ) -> str:
        """Send a markdown message as a threaded reply using Feishu Interactive Card.

        Used for content containing fenced code blocks or markdown tables — these render
        more richly inside a wide-screen card than in a post bubble.
        """
        card = {
            "schema": "2.0",
            "config": {"wide_screen_mode": True},
            "body": {
                "elements": [{"tag": "markdown", "content": markdown_text}]
            }
        }
        return await self.send_interactive(chat_id, card, reply_to_message_id)

    async def send_edit_diff_card(
        self,
        chat_id: str,
        card: dict,
        reply_to_message_id: str,
        log_reply: bool = True,
    ) -> str:
        """Send a pre-built colored diff card as a threaded reply."""
        msg_id = await self.send_interactive(chat_id, card, reply_to_message_id)
        if log_reply:
            logger.info(f"Replied diff card to {reply_to_message_id} in chat {chat_id}: {msg_id}")
        return msg_id

    async def send_image_reply(
        self,
        chat_id: str,
        image_key: str,
        reply_to_message_id: str,
    ) -> str:
        """Send an image message as a threaded reply."""
        import json
        import lark_oapi as lark
        client = self._get_client()
        request = (
            lark.im.v1.ReplyMessageRequest.builder()
            .message_id(reply_to_message_id)
            .request_body(
                lark.im.v1.ReplyMessageRequestBody.builder()
                .content(json.dumps({"image_key": image_key}))
                .msg_type("image")
                .build()
            )
            .build()
        )
        response = await asyncio.to_thread(client.im.v1.message.reply, request)
        if not response.success():
            raise RuntimeError(f"Failed to reply image: {response.msg}")
        return response.data.message_id

    async def send_file_reply(
        self,
        chat_id: str,
        file_key: str,
        file_name: str,
        reply_to_message_id: str,
    ) -> str:
        """Send a file message as a threaded reply."""
        import json
        import lark_oapi as lark
        client = self._get_client()
        request = (
            lark.im.v1.ReplyMessageRequest.builder()
            .message_id(reply_to_message_id)
            .request_body(
                lark.im.v1.ReplyMessageRequestBody.builder()
                .content(json.dumps({"file_key": file_key, "file_name": file_name}))
                .msg_type("file")
                .build()
            )
            .build()
        )
        response = await asyncio.to_thread(client.im.v1.message.reply, request)
        if not response.success():
            raise RuntimeError(f"Failed to reply file: {response.msg}")
        return response.data.message_id

    def _extract_file_info(self, content_str: str) -> tuple[str, str]:
        """Extract original filename and file_type from file message content."""
        import json
        try:
            content = json.loads(content_str)
            name = content.get("file_name", "file")
            ftype = content.get("file_type", "bin")
            return name, ftype
        except Exception:
            return "file", "bin"

    def parse_incoming_message(self, body: dict) -> IncomingMessage | None:
        """Parse webhook payload into IncomingMessage."""
        try:
            event = body.get("event", {})
            if not event:
                return None

            message = event.get("message", {})
            sender = event.get("sender", {})

            return IncomingMessage(
                message_id=message.get("message_id", ""),
                chat_id=message.get("chat_id", ""),
                user_open_id=sender.get("sender_id", {}).get("open_id", ""),
                content=self._extract_content(message),
                message_type=message.get("msg_type", "text"),
                create_time=message.get("create_time", ""),
                parent_id=message.get("parent_id", ""),
                thread_id=message.get("thread_id", ""),
            )
        except Exception as e:
            logger.error(f"Failed to parse incoming message: {e}")
            return None

    def _extract_content(self, message: dict) -> str:
        """Extract text content from message."""
        msg_type = message.get("msg_type", "")
        content_str = message.get("content", "{}")
        try:
            import json
            content = json.loads(content_str)
            if msg_type == "text":
                return content.get("text", "")
            elif msg_type == "post":
                return content.get("text", "")
            return str(content)
        except Exception:
            return content_str
