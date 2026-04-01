import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from cc_feishu_bridge.feishu.client import FeishuClient, IncomingMessage


def test_parse_incoming_text_message():
    client = FeishuClient(app_id="cli_test", app_secret="secret")
    body = {
        "event": {
            "message": {
                "message_id": "om_123",
                "chat_id": "oc_456",
                "msg_type": "text",
                "content": '{"text": "hello world"}',
                "create_time": "1234567890",
            },
            "sender": {
                "sender_id": {"open_id": "ou_789"},
            },
        }
    }
    msg = client.parse_incoming_message(body)
    assert msg is not None
    assert msg.message_id == "om_123"
    assert msg.content == "hello world"
    assert msg.user_open_id == "ou_789"


def test_parse_incoming_empty_body():
    client = FeishuClient(app_id="cli_test", app_secret="secret")
    msg = client.parse_incoming_message({})
    assert msg is None


def test_parse_non_text_message():
    client = FeishuClient(app_id="cli_test", app_secret="secret")
    body = {
        "event": {
            "message": {
                "message_id": "om_123",
                "chat_id": "oc_456",
                "msg_type": "image",
                "content": '{"file_key": "img_xxx"}',
                "create_time": "1234567890",
            },
            "sender": {
                "sender_id": {"open_id": "ou_789"},
            },
        }
    }
    msg = client.parse_incoming_message(body)
    assert msg is not None
    assert msg.message_type == "image"


def test_client_accepts_data_dir():
    client = FeishuClient(app_id="cli_test", app_secret="secret", data_dir="/tmp/test")
    assert client.data_dir == "/tmp/test"


def test_client_data_dir_defaults_to_empty():
    client = FeishuClient(app_id="cli_test", app_secret="secret")
    assert client.data_dir == ""


def test_extract_file_info():
    client = FeishuClient(app_id="cli_test", app_secret="secret")
    name, ftype = client._extract_file_info('{"file_name": "report", "file_type": "pdf"}')
    assert name == "report"
    assert ftype == "pdf"


def test_extract_file_info_invalid_json():
    client = FeishuClient(app_id="cli_test", app_secret="secret")
    name, ftype = client._extract_file_info("not json")
    assert name == "file"
    assert ftype == "bin"
