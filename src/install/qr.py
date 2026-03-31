"""Terminal QR code printing."""
from __future__ import annotations

try:
    import qrcode
    QRCODE_AVAILABLE = True
except ImportError:
    QRCODE_AVAILABLE = False


def print_qr(url: str) -> None:
    """Print QR code to terminal using qrcode library."""
    if not QRCODE_AVAILABLE:
        print(f"\n请用飞书扫码打开链接:\n{url}\n")
        return

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    # Print as ASCII
    for row in img.getdata():
        for pixel in row:
            print("  " if pixel else "██", end="")
        print()
    print(f"\n或者直接打开: {url}\n")
