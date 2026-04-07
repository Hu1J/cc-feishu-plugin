# tests/claude/test_feishu_file_tools.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import tempfile
import os
from unittest.mock import AsyncMock, patch, MagicMock


def test_guess_file_type_image():
    """图片文件被正确识别为图片类型"""
    from cc_feishu_bridge.feishu.media import guess_file_type
    assert guess_file_type(".png") == "png"
    assert guess_file_type(".jpg") == "png"
    assert guess_file_type(".gif") == "gif"
    assert guess_file_type(".webp") == "webp"


def test_guess_file_type_doc():
    """文档文件被识别为对应类型"""
    from cc_feishu_bridge.feishu.media import guess_file_type
    assert guess_file_type(".pdf") == "pdf"
    assert guess_file_type(".docx") == "doc"
    assert guess_file_type(".xlsx") == "xls"


def test_guess_file_type_stream():
    """未知类型默认 stream"""
    from cc_feishu_bridge.feishu.media import guess_file_type
    assert guess_file_type(".xyz") == "stream"