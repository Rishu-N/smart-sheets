"""Host notification dispatch — terminal print + OS desktop notification."""

import logging

logger = logging.getLogger("smartsheet")


def print_otp_to_terminal(name: str, otp: str, expires_in: int) -> None:
    minutes = expires_in // 60
    seconds = expires_in % 60
    print()
    print(f"  [JOIN REQUEST] {name} wants to join.")
    print(f"  OTP: {otp}  (expires in {minutes}:{seconds:02d})")
    print()


def send_desktop_notification(title: str, message: str, timeout: int = 30) -> bool:
    """Send OS-level desktop notification via plyer. Returns True on success."""
    try:
        from plyer import notification
        notification.notify(
            title=title,
            message=message,
            timeout=timeout,
            app_name="SmartSheet",
        )
        return True
    except ImportError:
        logger.warning("plyer not installed — skipping desktop notification")
        return False
    except Exception as e:
        logger.warning(f"Desktop notification failed: {e}")
        return False
