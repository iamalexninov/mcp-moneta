"""JWT access tokens (RFC 9068 profile) signed with ES256."""

import time
import uuid

import jwt

from ..config import get_settings
from .keys import load_keys

ALGORITHM = "ES256"


class TokenError(Exception):
    pass


def issue_access_token(
    *,
    subject: int,
    tenant_id: int,
    role: str,
    client_id: str,
    scopes: set[str],
    audience: str,
    grant_id: str,
    ttl: int,
    actor: str | None = None,
) -> tuple[str, int]:
    s = get_settings()
    key, _ = load_keys()
    now = int(time.time())
    claims = {
        "iss": s.public_url,
        "sub": str(subject),
        "aud": audience,
        "iat": now,
        "nbf": now,
        "exp": now + ttl,
        "jti": str(uuid.uuid4()),
        "client_id": client_id,
        "scope": " ".join(sorted(scopes)),
        "tid": tenant_id,
        "role": role,
        "sid": grant_id,
    }
    if actor:  # RFC 8693 delegation: who is acting on behalf of the user
        claims["act"] = {"sub": actor}
    token = jwt.encode(claims, key.private_key, algorithm=ALGORITHM, headers={"kid": key.kid, "typ": "at+jwt"})
    return token, ttl


def verify_access_token(token: str, audience: str) -> dict:
    """Verify signature, issuer, audience, expiry. Raises TokenError."""
    s = get_settings()
    _, keys = load_keys()
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as e:
        raise TokenError("malformed token") from e
    if header.get("alg") != ALGORITHM:  # blocks alg=none / HS256 confusion
        raise TokenError("unexpected algorithm")
    key = next((k for k in keys if k.kid == header.get("kid")), None)
    if key is None:
        raise TokenError("unknown key id")
    try:
        return jwt.decode(
            token,
            key.private_key.public_key(),
            algorithms=[ALGORITHM],
            audience=audience,
            issuer=s.public_url,
            options={"require": ["exp", "iat", "iss", "aud", "sub", "jti"]},
            leeway=10,
        )
    except jwt.PyJWTError as e:
        raise TokenError(str(e)) from e
