"""Feishu App Registration API — init/begin/poll for creating a bot via QR scan."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Optional

import httpx


@dataclass
class AppRegistrationResult:
    app_id: str
    app_secret: str
    user_open_id: str
    domain: str  # "feishu" or "lark"


@dataclass
class BeginResult:
    device_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int
    user_code: Optional[str] = None


class FeishuInstallAPI:
    BASE_URL_FEISHU = "https://open.feishu.cn"
    BASE_URL_LARK = "https://open.larksuite.com"

    def __init__(self, env: str = "prod"):
        self.env = env
        self._base_url = self.BASE_URL_FEISHU

    def set_domain(self, is_lark: bool):
        self._base_url = self.BASE_URL_LARK if is_lark else self.BASE_URL_FEISHU

    async def init(self) -> dict:
        """Initialize app registration. Returns supported_auth_methods."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._base_url}/oauth/v1/app_registration",
                data={"action": "init"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            return resp.json()

    async def begin(self) -> BeginResult:
        """Start app registration flow. Returns QR URI + device_code."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._base_url}/oauth/v1/app_registration",
                data={
                    "action": "begin",
                    "archetype": "PersonalAgent",
                    "auth_method": "client_secret",
                    "request_user_info": "open_id",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            data = resp.json()

        return BeginResult(
            device_code=data["device_code"],
            verification_uri=data["verification_uri"],
            verification_uri_complete=data["verification_uri_complete"],
            expires_in=data.get("expires_in", 600),
            interval=data.get("interval", 5),
            user_code=data.get("user_code"),
        )

    async def poll(self, device_code: str, timeout: int = 600) -> AppRegistrationResult:
        """
        Poll until user completes QR scan and registration.
        Returns client_id, client_secret, open_id when ready.
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            start = time.monotonic()
            interval = 5

            while time.monotonic() - start < timeout:
                resp = await client.post(
                    f"{self._base_url}/oauth/v1/app_registration",
                    data={
                        "action": "poll",
                        "device_code": device_code,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                data = resp.json()

                if data.get("error"):
                    err = data["error"]
                    if err == "authorization_pending":
                        await asyncio.sleep(interval)
                        continue
                    elif err == "access_denied":
                        raise RuntimeError("用户拒绝了授权 (access_denied)")
                    elif err in ("expired_token", "authorization_timeout"):
                        raise RuntimeError("授权已过期，请重新扫码 (expired)")
                    else:
                        raise RuntimeError(f"授权失败: {err}")

                if data.get("client_id") and data.get("client_secret"):
                    is_lark = data.get("user_info", {}).get("tenant_brand") == "lark"
                    return AppRegistrationResult(
                        app_id=data["client_id"],
                        app_secret=data["client_secret"],
                        user_open_id=data.get("user_info", {}).get("open_id", ""),
                        domain="lark" if is_lark else "feishu",
                    )

                await asyncio.sleep(interval)

            raise RuntimeError("扫码超时，请重新运行安装命令")
