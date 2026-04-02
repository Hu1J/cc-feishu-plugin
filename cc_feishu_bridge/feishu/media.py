"""Media file utilities — path generation, saving, MIME type mapping."""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Tuple


# MIME type → 文件扩展名
MIME_TO_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/svg+xml": ".svg",
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/zip": ".zip",
    "text/plain": ".txt",
    "text/html": ".html",
    "text/css": ".css",
    "text/javascript": ".js",
    "application/json": ".json",
    "application/octet-stream": ".bin",
}

# 飞书 file_type → MIME type（参考飞书文档）
FILE_TYPE_TO_MIME = {
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "zip": "application/zip",
    "txt": "text/plain",
    "csv": "text/csv",
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "mp4": "video/mp4",
    "avi": "video/x-msvideo",
}


def mime_to_ext(mime_type: str) -> str:
    """MIME type → 文件扩展名（含点号）。未知类型默认 .bin。"""
    return MIME_TO_EXT.get(mime_type, ".bin")


def file_type_to_mime(file_type: str) -> str:
    """飞书 file_type（如 'pdf'）→ MIME type。未知默认 application/octet-stream。"""
    return FILE_TYPE_TO_MIME.get(file_type.lower(), "application/octet-stream")


def sanitize_filename(name: str) -> str:
    """将文件名中的特殊字符替换为下划线，防止路径注入。"""
    return re.sub(r"[^a-zA-Z0-9._]", "_", name)


def make_image_path(data_dir: str, message_id: str) -> str:
    """生成图片本地存储路径（不含扩展名）。"""
    ts = time.strftime("%Y%m%d_%H%M%S")
    filename = f"img_{ts}_{message_id}"
    images_dir = os.path.join(data_dir, "received_images")
    os.makedirs(images_dir, exist_ok=True)
    return os.path.join(images_dir, filename)


def make_file_path(data_dir: str, message_id: str, original_name: str, file_type: str) -> str:
    """生成文件本地存储路径。"""
    ts = time.strftime("%Y%m%d_%H%M%S")
    safe_name = sanitize_filename(original_name) if original_name else "file"
    ext = mime_to_ext(file_type_to_mime(file_type))
    filename = f"file_{ts}_{message_id}_{safe_name}{ext}"
    files_dir = os.path.join(data_dir, "received_files")
    os.makedirs(files_dir, exist_ok=True)
    return os.path.join(files_dir, filename)


def save_bytes(path: str, data: bytes) -> None:
    """将字节写入文件。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


# 扩展名 → 飞书 file_type
EXT_TO_FILE_TYPE = {
    ".pdf": "pdf",
    ".doc": "doc",
    ".docx": "docx",
    ".xls": "xls",
    ".xlsx": "xlsx",
    ".ppt": "ppt",
    ".pptx": "pptx",
    ".zip": "zip",
    ".txt": "txt",
    ".csv": "csv",
    ".png": "png",
    ".jpg": "png",   # 飞书图片统一用 png
    ".jpeg": "png",
    ".gif": "gif",
    ".webp": "webp",
    ".bmp": "bmp",
}


def guess_file_type(ext: str) -> str:
    """扩展名（如 '.pdf'）→ 飞书 file_type（如 'pdf'）。未知默认 'bin'。"""
    return EXT_TO_FILE_TYPE.get(ext.lower(), "bin")