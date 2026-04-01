import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from cc_feishu_bridge.feishu.media import (
    sanitize_filename,
    mime_to_ext,
    file_type_to_mime,
    make_image_path,
    make_file_path,
    save_bytes,
)
import os
import tempfile


class TestSanitizeFilename:
    def test_replaces_spaces(self):
        assert sanitize_filename("my file name") == "my_file_name"

    def test_replaces_slashes(self):
        assert sanitize_filename("doc/v2/test") == "doc_v2_test"

    def test_keeps_underscores_and_dots(self):
        assert sanitize_filename("my_file.v2.pdf") == "my_file.v2.pdf"

    def test_replaces_special_chars(self):
        assert sanitize_filename("file<>:\"|?*.txt") == "file_______.txt"


class TestMimeToExt:
    def test_png(self):
        assert mime_to_ext("image/png") == ".png"

    def test_jpeg(self):
        assert mime_to_ext("image/jpeg") == ".jpg"

    def test_unknown_returns_bin(self):
        assert mime_to_ext("application/x-unknown") == ".bin"


class TestFileTypeToMime:
    def test_pdf(self):
        assert file_type_to_mime("pdf") == "application/pdf"

    def test_docx(self):
        assert file_type_to_mime("docx") == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    def test_unknown(self):
        assert file_type_to_mime("unknowntype") == "application/octet-stream"


class TestMakeImagePath:
    def test_returns_path_in_received_images(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = make_image_path(tmpdir, "om_abc12345xyz")
            assert "received_images" in path
            assert path.startswith(tmpdir)
            assert os.path.exists(os.path.dirname(path))

    def test_path_contains_message_id_prefix(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = make_image_path(tmpdir, "om_abc12345xyz")
            assert "abc12345" in path


class TestMakeFilePath:
    def test_returns_path_in_received_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = make_file_path(tmpdir, "om_abc12345", "report", "pdf")
            assert "received_files" in path
            assert path.startswith(tmpdir)
            assert os.path.exists(os.path.dirname(path))

    def test_includes_original_filename(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = make_file_path(tmpdir, "om_abc12345", "document", "pdf")
            assert "document" in path

    def test_unknown_file_type_gets_bin_ext(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = make_file_path(tmpdir, "om_abc12345", "data", "unknowntype")
            assert path.endswith(".bin")


class TestSaveBytes:
    def test_writes_and_reads_bytes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.bin")
            save_bytes(path, b"\x89PNG\r\n\x1a\n")
            with open(path, "rb") as f:
                assert f.read() == b"\x89PNG\r\n\x1a\n"

    def test_creates_intermediate_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            nested = os.path.join(tmpdir, "a", "b", "c")
            path = os.path.join(nested, "test.bin")
            save_bytes(path, b"data")
            assert os.path.exists(path)