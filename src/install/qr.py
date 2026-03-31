"""Terminal QR code printing using qrcode-terminal (same as openclaw)."""
from __future__ import annotations

try:
    import qrcode_terminal as qr_terminal
    QRCODE_AVAILABLE = True
except ImportError:
    QRCODE_AVAILABLE = False


def print_qr(url: str) -> None:
    """Print QR code to terminal using qrcode-terminal (auto-sized for terminal)."""
    if not QRCODE_AVAILABLE:
        print(f"\n请用飞书扫码打开链接:\n{url}\n")
        return

    print()
    qr_terminal.qrcode_terminal.draw(url)
    print(f"\n或者直接打开: {url}\n")
