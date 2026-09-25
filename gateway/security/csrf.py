"""Stateless CSRF tokens: HMAC(secret, binding|timestamp|nonce).

The token is bound to a per-browser value (the admin session id, or a random
cookie for the OAuth login page) so it cannot be replayed from another
browser, and it expires after ``max_age`` seconds.
"""

import hashlib
import hmac
import secrets
import time

from ..config import get_settings


def _sig(binding: str, ts: str, nonce: str) -> str:
    key = get_settings().session_secret.encode()
    return hmac.new(key, f"csrf|{binding}|{ts}|{nonce}".encode(), hashlib.sha256).hexdigest()


def issue(binding: str) -> str:
    ts, nonce = str(int(time.time())), secrets.token_urlsafe(12)
    return f"{ts}.{nonce}.{_sig(binding, ts, nonce)}"


def verify(token: str | None, binding: str | None, max_age: int = 1800) -> bool:
    if not token or not binding:
        return False
    try:
        ts, nonce, sig = token.split(".")
        if time.time() - int(ts) > max_age:
            return False
    except ValueError:
        return False
    return hmac.compare_digest(sig, _sig(binding, ts, nonce))
