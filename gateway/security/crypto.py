"""Small crypto helpers: token generation/hashing and field encryption."""

import base64
import hashlib
import hmac
import os
import secrets

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from ..config import get_settings


def new_token(nbytes: int = 32) -> str:
    """URL-safe random secret (256 bits by default)."""
    return secrets.token_urlsafe(nbytes)


def sha256_hex(value: str) -> str:
    """Opaque tokens (codes, refresh tokens) are stored only as SHA-256 hashes,
    so a database leak does not leak usable tokens."""
    return hashlib.sha256(value.encode()).hexdigest()


def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def pkce_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _field_key() -> bytes:
    # Derive a dedicated 256-bit key from the configured secret (HKDF, RFC 5869).
    # In production supply the secret from a KMS / Key Vault.
    secret = get_settings().session_secret.encode()
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=b"moneta-field-enc", info=b"v1").derive(secret)


def encrypt_field(plaintext: str) -> str:
    nonce = os.urandom(12)
    ct = AESGCM(_field_key()).encrypt(nonce, plaintext.encode(), b"moneta")
    return base64.urlsafe_b64encode(nonce + ct).decode()


def decrypt_field(token: str) -> str:
    raw = base64.urlsafe_b64decode(token.encode())
    return AESGCM(_field_key()).decrypt(raw[:12], raw[12:], b"moneta").decode()
