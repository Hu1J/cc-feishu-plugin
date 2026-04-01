#!/usr/bin/env python3
"""PyInstaller build script for cc-feishu-bridge CLI binary."""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Build constants
APP_NAME = "cc-feishu-bridge"
ENTRY_SCRIPT = "run.py"
SPEC_DIR = Path("build")
DIST_DIR = Path("dist")


# Hidden imports needed because we use dynamic imports inside cc_feishu_bridge/
HIDDEN_IMPORTS = [
    "cc_feishu_bridge.config",
    "cc_feishu_bridge.feishu.client",
    "cc_feishu_bridge.feishu.message_handler",
    "cc_feishu_bridge.security.auth",
    "cc_feishu_bridge.security.validator",
    "cc_feishu_bridge.claude.integration",
    "cc_feishu_bridge.claude.session_manager",
    "cc_feishu_bridge.format.reply_formatter",
    "cc_feishu_bridge.install.api",
    "cc_feishu_bridge.install.qr",
    "cc_feishu_bridge.install.flow",
    "qrcode",
    "qrcode_terminal",
    "PIL",
]


def ensure_clean() -> None:
    """Remove old build artifacts."""
    for d in [SPEC_DIR, DIST_DIR]:
        if d.exists():
            shutil.rmtree(d)


def install_pyinstaller() -> None:
    """Ensure pyinstaller is installed."""
    try:
        subprocess.run(
            [sys.executable, "-c", "import PyInstaller"],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError:
        print("Installing PyInstaller...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "pyinstaller"],
            check=True,
        )


def write_spec(path: Path) -> None:
    """Generate a .spec file for PyInstaller."""
    hidden_imports_block = ",\n    ".join(f'"{m}"' for m in HIDDEN_IMPORTS)
    spec_content = f'''# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['{ENTRY_SCRIPT}'],
    pathex=['{Path.cwd().resolve()}'],
    binaries=[],
    datas=[],
    hiddenimports=[
    {hidden_imports_block},
    ],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='{APP_NAME}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    console=True,
)
'''
    path.write_text(spec_content, encoding="utf-8")
    print(f"Generated spec file: {path}")


def build(spec_file: str | None = None) -> Path:
    """Run PyInstaller and return path to the binary."""
    system = platform.system()
    machine = platform.machine()

    print(f"\n{'='*50}")
    print(f"Building {APP_NAME} for {system} ({machine})")
    print(f"{'='*50}\n")

    install_pyinstaller()

    # Write spec file in project root so paths resolve correctly
    if spec_file is None:
        SPEC_DIR.mkdir(exist_ok=True)
        spec_path = Path(f"{APP_NAME}.spec")
        write_spec(spec_path)
        spec_file = str(spec_path)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--distpath", str(DIST_DIR),
        "--workpath", str(SPEC_DIR),
        "--clean",
        "--noconfirm",
        str(spec_file),
    ]

    print(f"Running: {' '.join(cmd)}\n")
    result = subprocess.run(cmd)

    if result.returncode != 0:
        print("Build FAILED")
        sys.exit(1)

    binary = DIST_DIR / APP_NAME
    if system == "Windows":
        binary = DIST_DIR / f"{APP_NAME}.exe"

    if binary.exists():
        size_mb = binary.stat().st_size / 1024 / 1024
        print(f"\n{'='*50}")
        print(f"Build SUCCEEDED: {binary}")
        print(f"Size: {size_mb:.1f} MB")
        print(f"{'='*50}\n")
    else:
        # Try to find the output
        files = list(DIST_DIR.iterdir())
        print(f"Dist contents: {files}")
        if not files:
            print("Build FAILED: no output found")
            sys.exit(1)
        binary = files[0]

    return binary


def run() -> None:
    """Build for current platform."""
    binary = build()
    print(f"Binary ready: {binary}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=f"Build {APP_NAME} binary with PyInstaller")
    parser.add_argument("--clean", action="store_true", help="Clean build artifacts first")
    args = parser.parse_args()

    if args.clean:
        ensure_clean()

    run()
