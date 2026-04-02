import pytest
from unittest.mock import AsyncMock, patch

from cc_feishu_bridge.install.api import FeishuInstallAPI, DeviceAuthResult

def test_device_auth_result_dataclass():
    r = DeviceAuthResult(
        device_code="dc_123",
        verification_uri="https://example.com/verify",
        verification_uri_complete="https://example.com/verify?code=ABCD",
        expires_in=300,
        interval=5,
        user_code="ABCD",
    )
    assert r.device_code == "dc_123"
    assert r.user_code == "ABCD"

def test_init_with_credentials():
    api = FeishuInstallAPI(app_id="app_123", app_secret="secret_456")
    assert api.app_id == "app_123"
    assert api.app_secret == "secret_456"
    assert api._base_url == FeishuInstallAPI.BASE_URL_FEISHU