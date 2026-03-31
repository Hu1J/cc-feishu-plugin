#!/usr/bin/env python3
"""Nuitka build script for cc-feishu-bridge CLI binary."""
from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

APP_NAME = "cc-feishu-bridge"
DIST_DIR = Path("dist")


def get_cache_dir() -> Path:
    """Get platform-specific Nuitka cache directory."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    return Path.home() / ".cache" / "cc-feishu-bridge-nuitka" / f"{system}-{machine}"


def build_onefile() -> Path:
    """Build single-file executable with Nuitka."""
    import nuitka
    nuitka_version = getattr(nuitka, "__version__", "unknown")
    print(f"Using Nuitka {nuitka_version}")

    cache_dir = get_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)

    shutil.rmtree(DIST_DIR / APP_NAME, ignore_errors=True)
    DIST_DIR.mkdir(exist_ok=True)

    compile_cmd = [
        sys.executable, "-m", "nuitka",
        "--onefile",
        "--enable-console",
        "--assume-yes-for-downloads",
        f"--python-flag=no_site",
        f"--output-dir={DIST_DIR}",
        f"--paths={Path.cwd()}",
        "--include-data-dir=./src=src",
        "--windows-icon-from-ico=none",
        "run.py",
    ]

    print(f"\nRunning: {' '.join(compile_cmd)}\n")
    result = subprocess.run(compile_cmd)

    if result.returncode != 0:
        print("Build FAILED")
        sys.exit(1)

    binary = DIST_DIR / APP_NAME
    if platform.system() == "Windows":
        binary = DIST_DIR / f"{APP_NAME}.exe"

    if binary.exists():
        size_mb = binary.stat().st_size / 1024 / 1024
        print(f"\n{'='*50}")
        print(f"Build SUCCEEDED: {binary}")
        print(f"Size: {size_mb:.1f} MB")
        print(f"{'='*50}\n")
    else:
        files = list(DIST_DIR.iterdir())
        print(f"Dist contents: {files}")
        binary = files[0] if files else None

    return binary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=f"Build {APP_NAME} binary with Nuitka")
    parser.add_argument("--clean", action="store_true", help="Remove old build artifacts")
    args = parser.parse_args()

    if args.clean:
        cache = get_cache_dir()
        print(f"Cleaning Nuitka cache: {cache}")
        shutil.rmtree(cache, ignore_errors=True)
        print("Cache cleaned.")

    binary = build_onefile()
    print(f"Binary ready: {binary}")
