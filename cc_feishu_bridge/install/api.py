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


@dataclass
class DeviceAuthResult:
    device_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int
    user_code: str


class FeishuInstallAPI:
    """
    Feishu App Registration API using OAuth Device Flow.

    Endpoints (from @larksuite/openclaw-lark-tools feishu-auth.js):
      - init   : POST /oauth/v1/app/registration  action=init
      - begin  : POST /oauth/v1/app/registration  action=begin, archetype=PersonalAgent
      - poll   : POST /oauth/v1/app/registration  action=poll, device_code=xxx

    Base URLs:
      - Feishu: https://accounts.feishu.cn
      - Lark  : https://accounts.larksuite.com
    """

    BASE_URL_FEISHU = "https://accounts.feishu.cn"
    BASE_URL_LARK = "https://accounts.larksuite.com"

    def __init__(self, app_id: str = "", app_secret: str = "", env: str = "prod"):
        self.app_id = app_id
        self.app_secret = app_secret
        self.env = env
        self._base_url = self.BASE_URL_FEISHU
        self._client: Optional[httpx.AsyncClient] = None

    def set_domain(self, is_lark: bool):
        self._base_url = self.BASE_URL_LARK if is_lark else self.BASE_URL_FEISHU

    def _url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    async def _get_client(self) -> httpx.AsyncClient:
        """Return a shared client with cookie persistence (for nonce tracking)."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                cookies=httpx.Cookies(),
                follow_redirects=True,
            )
        return self._client

    async def close(self):
        """Close the shared HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def init(self) -> dict:
        """Initialize app registration. Returns { nonce, supported_auth_methods }."""
        client = await self._get_client()
        resp = await client.post(
            self._url("/oauth/v1/app/registration"),
            data={"action": "init"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        return resp.json()

    async def begin(self) -> BeginResult:
        """
        Start app registration flow.
        The server associates this call with the nonce from init() via session cookie.
        Returns QR URI + device_code.
        """
        client = await self._get_client()
        resp = await client.post(
            self._url("/oauth/v1/app/registration"),
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
        client = await self._get_client()
        start = time.monotonic()
        interval = 5

        while time.monotonic() - start < timeout:
            resp = await client.post(
                self._url("/oauth/v1/app/registration"),
                data={
                    "action": "poll",
                    "device_code": device_code,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            data = resp.json()

            # authorization_pending means user hasn't completed yet — keep polling
            if data.get("error") == "authorization_pending":
                await asyncio.sleep(interval)
                continue
            elif data.get("error") == "access_denied":
                raise RuntimeError("用户拒绝了授权 (access_denied)")
            elif data.get("error") in ("expired_token", "authorization_timeout"):
                raise RuntimeError("授权已过期，请重新扫码 (expired)")
            elif data.get("error"):
                raise RuntimeError(f"授权失败: {data['error']}")

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

    async def device_auth_begin(self, scopes: list[str]) -> DeviceAuthResult:
        """Start OAuth Device Authorization flow for user auth."""
        client = await self._get_client()
        resp = await client.post(
            self._url("/oauth/v1/device_authorization"),
            data={
                "client_id": self.app_id,
                "client_secret": self.app_secret,
                "scope": " ".join(scopes),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        data = resp.json()
        if data.get("error"):
            raise RuntimeError(f"Device auth error: {data['error']}")
        return DeviceAuthResult(
            device_code=data["device_code"],
            verification_uri=data["verification_uri"],
            verification_uri_complete=data["verification_uri_complete"],
            expires_in=data.get("expires_in", 300),
            interval=data.get("interval", 5),
            user_code=data.get("user_code", ""),
        )

    async def device_auth_poll(self, device_code: str) -> dict | None:
        """Poll for user authorization. Returns token dict on success, None if still pending."""
        client = await self._get_client()
        resp = await client.post(
            self._url("/oauth/v1/device_authorization/token"),
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": device_code,
                "client_id": self.app_id,
                "client_secret": self.app_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        data = resp.json()
        if data.get("error") == "authorization_pending":
            return None  # Still waiting
        if data.get("error"):
            raise RuntimeError(f"Auth failed: {data['error']}")
        return {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token", ""),
            "expires_in": data.get("expires_in", 0),
            "token_type": data.get("token_type", "Bearer"),
        }
