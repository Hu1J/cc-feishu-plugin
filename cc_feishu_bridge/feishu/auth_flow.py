"""OAuth Device Authorization flow for /feishu auth command."""
from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)


async def run_auth_flow(
    *,
    app_id: str,
    app_secret: str,
    user_open_id: str,
    chat_id: str,
    message_id: str,
    send_card_fn,
    update_card_fn,
    save_token_fn,
    scopes: list[str],
) -> None:
    """
    Orchestrate the full Device Auth flow:

    1. Call device_auth_begin → get verification URL + card
    2. Send pending card to chat
    3. Background poll device_auth_poll
    4. On success: update card to green, save token
    5. On failure/timeout: update card to red

    Runs as background task; does NOT block message handler.
    """
    from cc_feishu_bridge.install.api import FeishuInstallAPI

    api = FeishuInstallAPI(app_id=app_id, app_secret=app_secret)

    # Step 1: Begin device auth
    try:
        result = await api.device_auth_begin(scopes)
    except Exception as e:
        logger.error(f"device_auth_begin failed: {e}")
        await send_card_fn(chat_id, _make_error_card(str(e)), reply_to=message_id)
        return

    # Step 2: Send initial pending card
    from cc_feishu_bridge.feishu.card import make_auth_card
    card_json = make_auth_card(
        verification_url=result.verification_uri_complete,
        user_code=result.user_code,
        expires_minutes=int(result.expires_in // 60),
    )
    await send_card_fn(chat_id, card_json, reply_to=message_id)

    # Step 3: Background poll
    asyncio.create_task(
        _poll_auth_result(
            api=api,
            device_code=result.device_code,
            timeout=result.expires_in,
            interval=result.interval,
            user_open_id=user_open_id,
            chat_id=chat_id,
            message_id=message_id,
            update_card_fn=update_card_fn,
            save_token_fn=save_token_fn,
        )
    )


async def _poll_auth_result(
    api,
    device_code: str,
    timeout: int,
    interval: int,
    user_open_id: str,
    chat_id: str,
    message_id: str,
    update_card_fn,
    save_token_fn,
) -> None:
    """Poll until auth completes or times out. Update card on result."""
    from cc_feishu_bridge.feishu.card import make_auth_success_card, make_auth_failed_card

    start = time.monotonic()
    last_error = "轮询超时"

    while time.monotonic() - start < timeout:
        await asyncio.sleep(interval)
        try:
            token_data = await api.device_auth_poll(device_code)
        except Exception as e:
            last_error = str(e)
            continue

        if token_data is None:
            # authorization_pending — keep polling
            continue

        # Auth successful! Save token and update card to green
        try:
            save_token_fn(user_open_id, token_data)
        except Exception as e:
            logger.warning(f"Failed to save user token: {e}")

        try:
            success_card = make_auth_success_card()
            await update_card_fn(message_id, success_card)
        except Exception as e:
            logger.warning(f"Failed to update auth card to success: {e}")

        logger.info(f"User {user_open_id} auth successful")
        return

    # Timeout or error — update card to red
    try:
        failed_card = make_auth_failed_card(reason=last_error)
        await update_card_fn(message_id, failed_card)
    except Exception as e:
        logger.warning(f"Failed to update auth card to failed: {e}")


def _make_error_card(error_msg: str) -> str:
    """Build an error card when device_auth_begin itself fails."""
    from cc_feishu_bridge.feishu.card import make_auth_failed_card
    return make_auth_failed_card(reason=f"发起授权失败: {error_msg}")