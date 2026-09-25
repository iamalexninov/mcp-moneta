"""Primary authentication: password + optional TOTP, with lockout.

Shared by the admin panel login and the OAuth consent/login page.
"""

from datetime import timedelta

import pyotp
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import User, utcnow
from . import audit
from .crypto import decrypt_field
from .passwords import hash_password, needs_rehash, verify_password


class AuthError(Exception):
    """Deliberately generic message: never reveal whether the email exists."""

    def __init__(self, message: str = "Invalid email, password or code") -> None:
        super().__init__(message)


def authenticate(db: Session, email: str, password: str, totp_code: str | None, ip: str) -> User:
    s = get_settings()
    email = (email or "").strip().lower()[:254]
    user = db.execute(select(User).where(func.lower(User.email) == email)).scalar_one_or_none()

    if user and user.locked_until and user.locked_until > utcnow():
        # still run the hash so response time does not reveal the lock
        verify_password(None, password)
        audit.record(db, "login", "denied", user_id=user.id, tenant_id=user.tenant_id, ip=ip, reason="locked")
        raise AuthError("Account temporarily locked. Try again later.")

    ok = verify_password(user.password_hash if user else None, password)
    if ok and user and user.mfa_secret_enc:
        totp = pyotp.TOTP(decrypt_field(user.mfa_secret_enc))
        ok = bool(totp_code) and totp.verify(totp_code.strip(), valid_window=1)

    if not ok or not user or not user.is_active or not user.tenant.is_active:
        if user:
            user.failed_logins += 1
            if user.failed_logins >= s.max_failed_logins:
                user.locked_until = utcnow() + timedelta(minutes=s.lockout_minutes)
                user.failed_logins = 0
            audit.record(db, "login", "denied", user_id=user.id, tenant_id=user.tenant_id, ip=ip)
        else:
            audit.record(db, "login", "denied", ip=ip, reason="unknown_user")
        raise AuthError()

    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = utcnow()
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    return user
