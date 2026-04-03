"""Banner — terminal ASCII art and log file header."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path


BLUE = "\033[34m"
PURPLE = "\033[35m"
RED = "\033[31m"
WHITE = "\033[37m"
RESET = "\033[0m"

TERMINAL_ART = """  {RED}cc-feishu-bridge  v{version}{RESET}
"""


def print_banner(version: str) -> None:
    """Print the large ASCII art banner to terminal (sys.__stdout__)."""
    try:
        out = sys.__stdout__
        out.write(TERMINAL_ART.format(BLUE=BLUE, PURPLE=PURPLE, RED=RED, RESET=RESET, version=version))
        out.write("\n")
        out.flush()
    except (OSError, IOError):
        pass  # Never crash on banner output


def write_log_banner(log_file: str, version: str) -> None:
    """Write mini banner to log file if it is empty or doesn't exist."""
    p = Path(log_file)
    p.parent.mkdir(parents=True, exist_ok=True)

    if p.exists() and p.stat().st_size > 0:
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    banner = (
        f"{'=' * 40}\n"
        f"  cc-feishu-bridge  v{version}\n"
        f"  started at {timestamp}\n"
        f"{'=' * 40}\n\n"
    )
    with open(p, "a", encoding="utf-8") as f:
        f.write(banner)
