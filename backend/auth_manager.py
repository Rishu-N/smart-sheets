"""OTP generation, session management, and rate limiting for LAN auth."""

import secrets
import socket
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class OTPRequest:
    request_id: str
    name: str
    ip: str
    otp: str  # 6-digit zero-padded string
    created_at: float
    expires_at: float
    attempts: int = 0
    used: bool = False


@dataclass
class Session:
    session_token: str  # UUID v4
    user_id: str  # UUID v4
    display_name: str
    ip: str
    color: str
    connected_at: float
    is_host: bool = False


# 16 distinct colors for user presence
_COLOR_POOL = [
    "#3B82F6", "#EF4444", "#10B981", "#F59E0B", "#8B5CF6",
    "#EC4899", "#06B6D4", "#F97316", "#6366F1", "#14B8A6",
    "#E11D48", "#84CC16", "#A855F7", "#0EA5E9", "#D946EF",
    "#22D3EE",
]


class AuthManager:
    def __init__(self, otp_expiry: int = 300, max_attempts: int = 3, lockout_seconds: int = 120):
        self._otp_requests: dict[str, OTPRequest] = {}
        self._sessions: dict[str, Session] = {}  # keyed by session_token
        self._ip_lockouts: dict[str, float] = {}  # IP -> lockout_expires_at
        self._ip_request_timestamps: dict[str, list[float]] = {}
        self._otp_expiry = otp_expiry
        self._max_attempts = max_attempts
        self._lockout_seconds = lockout_seconds
        self._color_index = 0
        self._host_ips = self._detect_host_ips()

    @staticmethod
    def _detect_host_ips() -> set[str]:
        """Detect all IP addresses belonging to this machine."""
        ips = {"127.0.0.1", "::1", "localhost"}
        # Add LAN IP via socket trick
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ips.add(s.getsockname()[0])
            s.close()
        except Exception:
            pass
        # Add all IPs from hostname resolution
        try:
            hostname = socket.gethostname()
            ips.add(hostname)
            for info in socket.getaddrinfo(hostname, None):
                ips.add(info[4][0])
        except Exception:
            pass
        return ips

    def is_host(self, ip: str) -> bool:
        return ip in self._host_ips

    def check_rate_limit(self, ip: str) -> bool:
        """Return True if request is allowed (under 10 req/min)."""
        now = time.time()
        timestamps = self._ip_request_timestamps.get(ip, [])
        # Remove timestamps older than 60 seconds
        timestamps = [t for t in timestamps if now - t < 60]
        self._ip_request_timestamps[ip] = timestamps

        if len(timestamps) >= 10:
            return False

        timestamps.append(now)
        return True

    def is_locked_out(self, ip: str) -> tuple[bool, int]:
        """Return (is_locked, seconds_remaining)."""
        expires = self._ip_lockouts.get(ip, 0)
        if time.time() < expires:
            return True, int(expires - time.time())
        # Clear expired lockout
        self._ip_lockouts.pop(ip, None)
        return False, 0

    def create_otp_request(self, name: str, ip: str) -> OTPRequest:
        now = time.time()
        otp = f"{secrets.randbelow(1_000_000):06d}"
        request_id = f"req_{uuid.uuid4().hex[:12]}"

        req = OTPRequest(
            request_id=request_id,
            name=name,
            ip=ip,
            otp=otp,
            created_at=now,
            expires_at=now + self._otp_expiry,
        )
        self._otp_requests[request_id] = req
        return req

    def verify_otp(self, request_id: str, otp: str, ip: str) -> Session | dict:
        req = self._otp_requests.get(request_id)

        if not req:
            return {"status": "invalid", "error": "Request not found"}

        if req.used:
            return {"status": "invalid", "error": "OTP already used"}

        if time.time() > req.expires_at:
            return {"status": "expired", "error": "OTP has expired"}

        if req.ip != ip:
            return {"status": "invalid", "error": "IP mismatch"}

        if req.otp != otp:
            req.attempts += 1
            remaining = self._max_attempts - req.attempts

            if remaining <= 0:
                # Lock out the IP
                self._ip_lockouts[ip] = time.time() + self._lockout_seconds
                # Invalidate this request
                del self._otp_requests[request_id]
                return {
                    "status": "locked_out",
                    "retry_after": self._lockout_seconds,
                }

            return {
                "status": "invalid",
                "attempts_remaining": remaining,
            }

        # OTP matches — create session
        req.used = True
        session = Session(
            session_token=f"tok_{uuid.uuid4().hex}",
            user_id=f"user_{uuid.uuid4().hex[:12]}",
            display_name=req.name,
            ip=ip,
            color=self._next_color(),
            connected_at=time.time(),
        )
        self._sessions[session.session_token] = session

        # Clean up used request
        del self._otp_requests[request_id]

        return session

    def create_open_session(self, ip: str, token_hint: str = "") -> Session:
        """Create a session for an open-LAN guest without OTP (no auth required)."""
        # Reuse if a session for this IP already exists
        for s in self._sessions.values():
            if not s.is_host and s.ip == ip:
                return s

        session = Session(
            session_token=token_hint if token_hint.startswith("tok_") else f"tok_{uuid.uuid4().hex}",
            user_id=f"user_{uuid.uuid4().hex[:12]}",
            display_name=f"Guest",
            ip=ip,
            color=self._next_color(),
            connected_at=time.time(),
        )
        self._sessions[session.session_token] = session
        return session

    def create_host_session(self, ip: str) -> Session:
        """Create a session for the host (no OTP needed)."""
        # Check if host already has a session
        for s in self._sessions.values():
            if s.is_host and s.ip == ip:
                return s

        session = Session(
            session_token=f"tok_{uuid.uuid4().hex}",
            user_id="host",
            display_name="Host",
            ip=ip,
            color="#6c8cff",
            connected_at=time.time(),
            is_host=True,
        )
        self._sessions[session.session_token] = session
        return session

    def validate_session(self, token: str) -> Session | None:
        return self._sessions.get(token)

    def get_active_sessions(self) -> list[dict]:
        return [
            {
                "user_id": s.user_id,
                "display_name": s.display_name,
                "ip": s.ip,
                "color": s.color,
                "connected_at": s.connected_at,
                "is_host": s.is_host,
            }
            for s in self._sessions.values()
        ]

    def disconnect_session(self, user_id: str) -> bool:
        to_remove = None
        for token, s in self._sessions.items():
            if s.user_id == user_id:
                to_remove = token
                break
        if to_remove:
            del self._sessions[to_remove]
            return True
        return False

    def cleanup_expired(self) -> int:
        """Remove expired OTP requests. Returns count removed."""
        now = time.time()
        expired = [k for k, v in self._otp_requests.items() if now > v.expires_at]
        for k in expired:
            del self._otp_requests[k]
        return len(expired)

    def _next_color(self) -> str:
        color = _COLOR_POOL[self._color_index % len(_COLOR_POOL)]
        self._color_index += 1
        return color


_auth_manager: AuthManager | None = None


def get_auth_manager() -> AuthManager:
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = AuthManager()
    return _auth_manager


def init_auth_manager(otp_expiry: int = 300, max_attempts: int = 3, lockout_seconds: int = 120) -> AuthManager:
    global _auth_manager
    _auth_manager = AuthManager(otp_expiry, max_attempts, lockout_seconds)
    return _auth_manager
