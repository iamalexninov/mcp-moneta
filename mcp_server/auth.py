"""Bearer token verification for the MCP server (OAuth resource server).

Tokens are ES256 JWTs issued by the gateway. We verify them locally with the
gateway's published JWKS: signature, pinned algorithm, issuer, expiry and,
critically, that the audience is *this* MCP server (RFC 8707), so tokens
minted for any other service are rejected.
"""

import time

import httpx
import jwt
from mcp.server.auth.provider import AccessToken

from .config import get_settings


class JwksCache:
    def __init__(self, ttl: int = 300) -> None:
        self._keys: dict[str, object] = {}
        self._fetched = 0.0
        self._ttl = ttl

    async def get(self, kid: str):
        stale = time.time() - self._fetched > self._ttl
        if kid not in self._keys or stale:
            # Refetch at most every 10 s, even for unknown kids (prevents JWKS hammering).
            if time.time() - self._fetched > 10 or stale:
                await self._refresh()
        return self._keys.get(kid)

    async def _refresh(self) -> None:
        s = get_settings()
        async with httpx.AsyncClient(timeout=s.http_timeout) as client:
            resp = await client.get(f"{s.gateway_internal_url.rstrip('/')}/.well-known/jwks.json")
            resp.raise_for_status()
        keys = {}
        for jwk in resp.json().get("keys", []):
            if jwk.get("alg") == "ES256" and jwk.get("kty") == "EC":
                keys[jwk["kid"]] = jwt.algorithms.ECAlgorithm.from_jwk(jwk)
        self._keys, self._fetched = keys, time.time()


class GatewayTokenVerifier:
    def __init__(self) -> None:
        self.jwks = JwksCache()

    async def verify_token(self, token: str) -> AccessToken | None:
        s = get_settings()
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "ES256":
                return None
            key = await self.jwks.get(header.get("kid", ""))
            if key is None:
                return None
            claims = jwt.decode(
                token, key, algorithms=["ES256"], audience=s.public_url, issuer=s.issuer_url.rstrip("/"),
                options={"require": ["exp", "iat", "iss", "aud", "sub"]}, leeway=10,
            )
        except (jwt.PyJWTError, httpx.HTTPError, ValueError):
            return None
        return AccessToken(
            token=token,
            client_id=claims.get("client_id", ""),
            scopes=claims.get("scope", "").split(),
            expires_at=claims["exp"],
            resource=s.public_url,
            subject=claims["sub"],
            claims={"iss": claims["iss"], "tid": claims.get("tid"), "sid": claims.get("sid")},
        )
