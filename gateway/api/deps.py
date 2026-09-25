"""Authentication/authorization for the REST API.

Every request must carry a Bearer JWT with audience = ``<public_url>/api``
(minted by token exchange for the MCP server). On each call we:
1. verify signature/issuer/audience/expiry (ES256, pinned algorithm),
2. confirm the grant (user's AI connection) is not revoked,
3. confirm the user and tenant are still active,
4. intersect token scopes with the user's *current* role,
5. require the scope the endpoint needs.
"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import Grant, User
from ..security import scopes as sc
from ..security.ratelimit import limiter
from ..security.tokens import TokenError, verify_access_token


@dataclass(frozen=True)
class Principal:
    user_id: int
    tenant_id: int
    role: str
    client_id: str
    actor: str | None
    scopes: frozenset[str]
    grant_id: str


def _unauthorized(msg: str) -> HTTPException:
    return HTTPException(401, msg, headers={"WWW-Authenticate": 'Bearer error="invalid_token"'})


def get_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise _unauthorized("Missing bearer token")
    try:
        claims = verify_access_token(auth[7:].strip(), audience=get_settings().api_audience)
    except TokenError:
        raise _unauthorized("Invalid token")

    grant = db.get(Grant, claims.get("sid"))
    user = db.get(User, int(claims["sub"]))
    if not grant or grant.revoked_at is not None or not user or not user.is_active or not user.tenant.is_active:
        raise _unauthorized("Token revoked")
    if user.tenant_id != claims.get("tid") or grant.user_id != user.id:
        raise _unauthorized("Token/tenant mismatch")

    # Per-user rate limit, independent of IP (the MCP server is one IP).
    limiter.check(f"api-user:{user.id}", 120, 60)

    principal = Principal(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        client_id=claims.get("client_id", ""),
        actor=(claims.get("act") or {}).get("sub"),
        scopes=frozenset(sc.parse(claims.get("scope")) & sc.allowed_for_role(user.role)),
        grant_id=grant.id,
    )
    request.state.principal = principal
    return principal


def require(scope: str):
    def _dep(p: Annotated[Principal, Depends(get_principal)]) -> Principal:
        if scope not in p.scopes:
            raise HTTPException(403, f"Missing scope: {scope}")
        return p

    return _dep
