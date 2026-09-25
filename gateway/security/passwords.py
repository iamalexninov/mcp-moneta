"""Password hashing with Argon2id (OWASP recommended parameters)."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# OWASP 2024+: Argon2id, m=19 MiB, t=2, p=1 minimum. We use m=64 MiB, t=3.
_ph = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2)

# A real hash of a random string, used to equalise timing for unknown users.
_DUMMY_HASH = _ph.hash("timing-equaliser-not-a-real-password")

MIN_LENGTH = 12


def hash_password(password: str) -> str:
    validate_password_strength(password)
    return _ph.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Constant-work verification, also when the user does not exist."""
    try:
        return _ph.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _ph.check_needs_rehash(password_hash)


def validate_password_strength(password: str) -> None:
    """NIST SP 800-63B: length over complexity rules; block trivial passwords."""
    if len(password) < MIN_LENGTH:
        raise ValueError(f"Password must be at least {MIN_LENGTH} characters")
    if len(password) > 256:
        raise ValueError("Password too long")
    if len(set(password)) < 5:
        raise ValueError("Password is too repetitive")
