"""SmartSheet entry point — starts server, opens browser, prints LAN URL + QR code."""

import os
import socket
import sys

import qrcode
import uvicorn

from backend.config import load_config


def get_lan_ip() -> str:
    """Determine the machine's LAN IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        # Connect to an external address (doesn't actually send data)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def print_qr_to_terminal(url: str) -> None:
    """Print QR code as ASCII art to the terminal."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=1,
        border=1,
    )
    qr.add_data(url)
    qr.make(fit=True)
    qr.print_ascii(invert=True)


def main():
    # Change working directory to the smartsheet project root
    project_root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(project_root)

    config = load_config("config.json")

    lan_ip = get_lan_ip()
    localhost_url = f"http://localhost:{config.port}"
    lan_url = f"http://{lan_ip}:{config.port}"

    # Print startup banner
    print()
    print("=" * 56)
    print("  SmartSheet — AI-Powered Spreadsheet")
    print("=" * 56)
    print()
    print(f"  Local:   {localhost_url}")
    print(f"  LAN:     {lan_url}")
    print()
    print("  Share this QR code with LAN collaborators:")
    print()
    print_qr_to_terminal(lan_url)
    print()
    print("=" * 56)
    print()

    # Start uvicorn (browser open is handled in FastAPI lifespan)
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=config.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
