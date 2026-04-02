import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from cc_feishu_bridge.feishu.media import guess_file_type


class TestGuessFileType:
    def test_pdf(self):
        assert guess_file_type(".pdf") == "pdf"

    def test_docx(self):
        assert guess_file_type(".docx") == "docx"

    def test_xlsx(self):
        assert guess_file_type(".xlsx") == "xlsx"

    def test_png(self):
        assert guess_file_type(".png") == "png"

    def test_jpg(self):
        assert guess_file_type(".jpg") == "png"  # 飞书统一用 png

    def test_zip(self):
        assert guess_file_type(".zip") == "zip"

    def test_txt(self):
        assert guess_file_type(".txt") == "txt"

    def test_unknown(self):
        assert guess_file_type(".xyz") == "zip"

    def test_uppercase(self):
        assert guess_file_type(".PDF") == "pdf"


class TestSupportedImageExts:
    def test_supported_image_exts_in_main(self):
        """Verify SUPPORTED_IMAGE_EXTS constant matches media.py coverage."""
        from cc_feishu_bridge.main import SUPPORTED_IMAGE_EXTS
        assert ".png" in SUPPORTED_IMAGE_EXTS
        assert ".jpg" in SUPPORTED_IMAGE_EXTS
        assert ".jpeg" in SUPPORTED_IMAGE_EXTS
        assert ".gif" in SUPPORTED_IMAGE_EXTS
        assert ".webp" in SUPPORTED_IMAGE_EXTS
        assert ".bmp" in SUPPORTED_IMAGE_EXTS
        assert ".pdf" not in SUPPORTED_IMAGE_EXTS  # pdf 是文件不是图片