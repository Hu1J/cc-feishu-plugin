"""Build Feishu interactive card payloads for auth flow."""
from __future__ import annotations


def _to_inapp_web_url(target_url: str) -> str:
    """Wrap a URL in Feishu's in-app web viewer for better mobile experience."""
    import urllib.parse
    lk_meta = urllib.parse.quote(
        '{"page-meta":{"showNavBar":"false","showBottomNavBar":"false"}}'
    )
    sep = "&" if "?" in target_url else "?"
    full_url = f"{target_url}{sep}lk_meta={lk_meta}"
    encoded = urllib.parse.quote(full_url, safe="")
    return f"https://applink.feishu.cn/client/web_url/open?mode=sidebar-semi&max_width=800&reload=false&url={encoded}"


def _card_payload(header_title: str, header_template: str, body_elements: list) -> dict:
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": header_title},
            "template": header_template,
        },
        "body": {"elements": body_elements},
    }


def make_auth_card(verification_url: str, user_code: str, expires_minutes: int = 5) -> dict:
    """Build the pending auth card sent to the user immediately after /feishu auth."""
    inapp_url = _to_inapp_web_url(verification_url)
    return _card_payload(
        header_title="📋 授权 cc-feishu-bridge",
        header_template="blue",
        body_elements=[
            {
                "tag": "markdown",
                "content": (
                    f"**授权码：** `{user_code}`\n\n"
                    f"请在下方点击 **「前往授权」**，完成飞书授权后返回此处。\n"
                    f"链接将在 **{expires_minutes} 分钟** 后过期。\n\n"
                    "授权后机器人可执行文件上传等操作。"
                ),
                "text_size": "normal",
            },
            {
                "tag": "column_set",
                "flex_mode": "none",
                "horizontal_align": "right",
                "columns": [
                    {
                        "tag": "column",
                        "width": "auto",
                        "elements": [
                            {
                                "tag": "button",
                                "text": {"tag": "plain_text", "content": "前往授权"},
                                "type": "primary",
                                "size": "medium",
                                "multi_url": {
                                    "url": inapp_url,
                                    "pc_url": inapp_url,
                                    "android_url": inapp_url,
                                    "ios_url": inapp_url,
                                },
                            }
                        ],
                    }
                ],
            },
            {
                "tag": "markdown",
                "content": f"<font color='grey'>授权链接将在 {expires_minutes} 分钟后失效，届时需重新发起</font>",
                "text_size": "notation",
            },
        ],
    )


def make_auth_success_card() -> dict:
    """Build the success card updated after user completes auth."""
    return _card_payload(
        header_title="✅ 授权成功",
        header_template="green",
        body_elements=[
            {
                "tag": "markdown",
                "content": (
                    "🎉 授权已完成！\n\n"
                    "机器人现在可以上传文件了。\n"
                    "请继续对话或重新发送你的请求。"
                ),
            }
        ],
    )


def make_auth_failed_card(reason: str = "授权失败") -> dict:
    """Build the failed card when auth times out or is denied."""
    return _card_payload(
        header_title=f"❌ {reason}",
        header_template="red",
        body_elements=[
            {
                "tag": "markdown",
                "content": f"⚠️ {reason}\n\n请重新发送 `/feishu auth` 再次尝试。",
            }
        ],
    )