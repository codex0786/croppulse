"""Password hashing, signed access tokens and a small in-process rate limiter.

Standard library only (hashlib PBKDF2 + HMAC-SHA256). Tokens are short-lived,
stateless bearer tokens: ``v1.<user_id>.<expiry_epoch>.<signature>``. Changing
``CROPPULSE_SECRET_KEY`` invalidates every issued token.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from croppulse.config import get_settings

_ALGO = "pbkdf2_sha256"


def hash_password(password: str, iterations: int | None = None) -> str:
    if len(password) < 10:
        raise ValueError("Password must be at least 10 characters")
    iterations = iterations or get_settings().password_hash_iterations
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"{_ALGO}${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, it, salt_b64, dk_b64 = encoded.split("$")
    except ValueError:
        return False
    if algo != _ALGO:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt_b64), int(it))
    return hmac.compare_digest(dk, base64.b64decode(dk_b64))


def _sign(payload: str) -> str:
    key = get_settings().secret_key.encode()
    sig = hmac.new(key, payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode().rstrip("=")


def issue_token(user_id: str, ttl_minutes: int | None = None) -> tuple[str, int]:
    ttl = ttl_minutes or get_settings().token_ttl_minutes
    exp = int(time.time()) + ttl * 60
    payload = f"v1.{user_id}.{exp}"
    return f"{payload}.{_sign(payload)}", exp


@dataclass(frozen=True)
class TokenClaims:
    user_id: str
    expires_at: int


def verify_token(token: str) -> TokenClaims | None:
    parts = token.split(".")
    if len(parts) != 4 or parts[0] != "v1":
        return None
    payload = ".".join(parts[:3])
    if not hmac.compare_digest(_sign(payload), parts[3]):
        return None
    try:
        exp = int(parts[2])
    except ValueError:
        return None
    if exp < time.time():
        return None
    return TokenClaims(user_id=parts[1], expires_at=exp)


class RateLimiter:
    """Sliding-window limiter keyed by an opaque string (e.g. hashed client + route).

    In-process only: adequate for a single API instance. A multi-instance deployment
    needs a shared store (documented in docs/OPERATIONS.md).
    """

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_seconds: float = 60.0) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window_seconds:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


rate_limiter = RateLimiter()


def anonymize(value: str) -> str:
    """Stable, non-reversible identifier for logs (e.g. client IPs)."""
    key = get_settings().secret_key.encode()
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()[:16]
