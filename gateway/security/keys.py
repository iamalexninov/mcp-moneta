"""ES256 (ECDSA P-256) signing keys and JWKS publication.

Asymmetric keys mean the MCP server (and any other resource server) can
verify tokens with the *public* key only; only the gateway can mint tokens.
Keys are rotated with ``python -m gateway.cli rotate-keys``: the previous
public key stays in the JWKS so in-flight tokens remain valid until expiry.
"""

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from ..config import get_settings
from .crypto import new_token


@dataclass
class SigningKey:
    kid: str
    private_key: ec.EllipticCurvePrivateKey

    @property
    def public_jwk(self) -> dict:
        jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(self.private_key.public_key()))
        jwk.update(kid=self.kid, use="sig", alg="ES256")
        return jwk


def _keys_dir() -> Path:
    d = Path(get_settings().keys_dir)
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    return d


def generate_key() -> SigningKey:
    key = ec.generate_private_key(ec.SECP256R1())
    kid = new_token(12)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    path = _keys_dir() / f"{kid}.pem"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    (_keys_dir() / "current").write_text(kid)
    load_keys.cache_clear()
    return SigningKey(kid, key)


@lru_cache
def load_keys() -> tuple[SigningKey, list[SigningKey]]:
    """Returns (current signing key, all keys incl. previous for verification)."""
    d = _keys_dir()
    current_file = d / "current"
    if not current_file.exists():
        generate_key()
    current_kid = current_file.read_text().strip()
    keys = []
    for pem in sorted(d.glob("*.pem"), key=lambda p: p.stat().st_mtime, reverse=True)[:3]:
        priv = serialization.load_pem_private_key(pem.read_bytes(), password=None)
        keys.append(SigningKey(pem.stem, priv))
    current = next(k for k in keys if k.kid == current_kid)
    return current, keys


def jwks() -> dict:
    _, keys = load_keys()
    return {"keys": [k.public_jwk for k in keys]}
