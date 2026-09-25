"""OAuth 2.1 Authorization Server for AI clients.

Implements what MCP clients such as Claude.ai, ChatGPT and Cursor need:
* RFC 8414 authorization-server metadata
* RFC 7591 dynamic client registration (restricted to allow-listed redirect URIs)
* Authorization code + PKCE S256 (mandatory), RFC 8707 resource indicators
* Refresh tokens with rotation and reuse detection
* RFC 8693 token exchange, used only by the MCP server to swap the user's
  MCP-audience token for a short-lived REST-API token (no token passthrough)
* RFC 7009 revocation, and a JWKS endpoint for resource servers
"""

import json
import uuid
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import AuthorizationCode, Grant, OAuthClient, RefreshToken, User, utcnow
from ..security import audit, csrf
from ..security import scopes as sc
from ..security.authn import AuthError, authenticate
from ..security.crypto import constant_time_eq, new_token, pkce_s256, sha256_hex
from ..security.keys import jwks
from ..security.ratelimit import client_ip, limit
from ..security.tokens import TokenError, issue_access_token, verify_access_token

router = APIRouter(tags=["oauth"])
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "admin" / "templates"))

TOKEN_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"
ACCESS_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "[::1]"}
OAUTH_CSRF_COOKIE = "oauth_bind"


# ----------------------------------------------------------------- helpers
def oauth_error(error: str, description: str, status: int = 400) -> JSONResponse:
    return JSONResponse(
        {"error": error, "error_description": description},
        status_code=status,
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


def redirect_matches(registered: str, requested: str) -> bool:
    """Exact match, except loopback redirects where the port is ignored
    (RFC 8252 section 7.3 - native apps such as Claude Code / Cursor)."""
    if registered == requested:
        return True
    r, q = urlparse(registered), urlparse(requested)
    if r.scheme == "http" and r.hostname in {"localhost", "127.0.0.1", "::1"}:
        return (r.scheme, r.hostname, r.path) == (q.scheme, q.hostname, q.path) and not q.query and not q.fragment
    return False


def redirect_allowed_for_dcr(uri: str) -> bool:
    return any(redirect_matches(allowed, uri) for allowed in get_settings().allowed_redirect_uris)


def _client(db: Session, client_id: str | None) -> OAuthClient | None:
    if not client_id or len(client_id) > 100:
        return None
    c = db.execute(select(OAuthClient).where(OAuthClient.client_id == client_id)).scalar_one_or_none()
    return c if c and c.is_enabled else None


def _authenticate_confidential_client(db: Session, request: Request, form_id: str | None, form_secret: str | None):
    """client_secret_basic or client_secret_post."""
    import base64

    cid, secret = form_id, form_secret
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("basic "):
        try:
            cid, secret = base64.b64decode(auth[6:]).decode().split(":", 1)
        except Exception:
            return None
    client = _client(db, cid)
    if not client or not client.client_secret_hash or not secret:
        return None
    return client if constant_time_eq(client.client_secret_hash, sha256_hex(secret)) else None


def _token_response(payload: dict) -> JSONResponse:
    return JSONResponse(payload, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


def _issue_refresh(db: Session, grant: Grant) -> str:
    raw = new_token(32)
    db.add(
        RefreshToken(
            token_hash=sha256_hex(raw),
            grant_id=grant.id,
            expires_at=utcnow() + timedelta(seconds=get_settings().refresh_token_ttl),
        )
    )
    return raw


def revoke_grant(db: Session, grant: Grant, reason: str) -> None:
    if grant.revoked_at is None:
        grant.revoked_at = utcnow()
        grant.revoked_reason = reason[:200]


# ---------------------------------------------------------------- metadata
@router.get("/.well-known/oauth-authorization-server")
def as_metadata():
    s = get_settings()
    return {
        "issuer": s.public_url,
        "authorization_endpoint": f"{s.public_url}/oauth/authorize",
        "token_endpoint": f"{s.public_url}/oauth/token",
        "registration_endpoint": f"{s.public_url}/oauth/register",
        "revocation_endpoint": f"{s.public_url}/oauth/revoke",
        "jwks_uri": f"{s.public_url}/.well-known/jwks.json",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token", TOKEN_EXCHANGE],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_basic", "client_secret_post"],
        "revocation_endpoint_auth_methods_supported": ["none", "client_secret_basic", "client_secret_post"],
        "scopes_supported": sorted(sc.SCOPES) + ["offline_access"],
        "service_documentation": "https://github.com/iamalexninov/mcp-moneta/tree/main/docs",
    }


@router.get("/.well-known/jwks.json")
def jwks_endpoint():
    return JSONResponse(jwks(), headers={"Cache-Control": "public, max-age=300"})


# -------------------------------------------------------- dynamic registration
class RegistrationRequest(BaseModel):
    redirect_uris: list[str] = Field(min_length=1, max_length=5)
    client_name: str = Field(default="Unnamed AI client", max_length=100)
    token_endpoint_auth_method: str = "none"
    grant_types: list[str] = ["authorization_code", "refresh_token"]
    response_types: list[str] = ["code"]
    scope: str | None = None


@router.post("/oauth/register", dependencies=[Depends(limit("dcr", 10, 3600))])
def register_client(body: RegistrationRequest, request: Request, db: Session = Depends(get_db)):
    if body.token_endpoint_auth_method != "none":
        return oauth_error("invalid_client_metadata", "Only public clients with PKCE may self-register")
    if not set(body.grant_types) <= {"authorization_code", "refresh_token"} or body.response_types != ["code"]:
        return oauth_error("invalid_client_metadata", "Unsupported grant or response type")
    for uri in body.redirect_uris:
        if len(uri) > 500 or not redirect_allowed_for_dcr(uri):
            audit.record(db, "oauth.register", "denied", ip=client_ip(request), redirect_uri=uri[:200])
            return oauth_error("invalid_redirect_uri", "Redirect URI is not on the gateway allow-list")

    client = OAuthClient(
        client_id=f"dcr_{uuid.uuid4().hex}",
        client_name="".join(ch for ch in body.client_name if ch.isprintable())[:100],
        redirect_uris=json.dumps(body.redirect_uris),
        client_type="public",
        registered_via="dcr",
    )
    db.add(client)
    audit.record(db, "oauth.register", client_id=client.client_id, ip=client_ip(request), name=client.client_name)
    return JSONResponse(
        {
            "client_id": client.client_id,
            "client_name": client.client_name,
            "redirect_uris": body.redirect_uris,
            "token_endpoint_auth_method": "none",
            "grant_types": body.grant_types,
            "response_types": ["code"],
        },
        status_code=201,
    )


# ------------------------------------------------------------ authorization
def _validate_authorize_params(db: Session, p: dict) -> tuple[OAuthClient | None, str | None]:
    """Returns (client, error). Errors about client/redirect are shown on our
    own page, never redirected (prevents open-redirect abuse)."""
    s = get_settings()
    client = _client(db, p.get("client_id"))
    if not client or client.client_type != "public":
        return None, "Unknown or disabled client."
    registered = json.loads(client.redirect_uris)
    if not any(redirect_matches(r, p.get("redirect_uri") or "") for r in registered):
        return None, "Redirect URI does not match the registered client."
    if p.get("response_type") != "code":
        return client, "Only response_type=code is supported."
    if p.get("code_challenge_method") != "S256" or not (43 <= len(p.get("code_challenge") or "") <= 128):
        return client, "PKCE with S256 is required."
    if p.get("resource") and p["resource"].rstrip("/") != s.mcp_resource_url:
        return client, "Unknown resource (RFC 8707)."
    return client, None


def _render_authorize(request: Request, client: OAuthClient, params: dict, error: str | None = None, status=200):
    binding = request.cookies.get(OAUTH_CSRF_COOKIE) or new_token(16)
    requested = sc.parse(params.get("scope"))
    offered = sc.resolve_requested(requested, "admin")  # upper bound; trimmed to role after login
    resp = templates.TemplateResponse(
        request,
        "authorize.html",
        {
            "client": client,
            "redirect_host": urlparse(params.get("redirect_uri", "")).netloc,
            "is_loopback": urlparse(params.get("redirect_uri", "")).hostname in {"localhost", "127.0.0.1"},
            "params": params,
            "scopes": [(k, sc.SCOPES[k]) for k in sorted(offered) if k in sc.SCOPES],
            "csrf_token": csrf.issue(binding),
            "error": error,
        },
        status_code=status,
    )
    resp.set_cookie(
        OAUTH_CSRF_COOKIE, binding, httponly=True, secure=not get_settings().is_dev, samesite="lax", max_age=1800
    )
    return resp


AUTHZ_PARAMS = ("client_id", "redirect_uri", "response_type", "state", "scope", "code_challenge",
                "code_challenge_method", "resource")


@router.get("/oauth/authorize", response_class=HTMLResponse)
def authorize_page(request: Request, db: Session = Depends(get_db)):
    params = {k: request.query_params.get(k, "")[:1000] for k in AUTHZ_PARAMS}
    client, error = _validate_authorize_params(db, params)
    if client is None:
        return templates.TemplateResponse(request, "error.html", {"message": error}, status_code=400)
    if error:
        return RedirectResponse(
            f"{params['redirect_uri']}?{urlencode({'error': 'invalid_request', 'error_description': error, 'state': params['state']})}",
            status_code=302,
        )
    return _render_authorize(request, client, params)


@router.post("/oauth/authorize", dependencies=[Depends(limit("authorize", 20, 300))])
async def authorize_submit(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    params = {k: str(form.get(k, ""))[:1000] for k in AUTHZ_PARAMS}
    ip = client_ip(request)
    client, error = _validate_authorize_params(db, params)
    if client is None or error:
        return templates.TemplateResponse(request, "error.html", {"message": error}, status_code=400)
    if not csrf.verify(str(form.get("csrf_token", "")), request.cookies.get(OAUTH_CSRF_COOKIE)):
        return _render_authorize(request, client, params, "Session expired, please try again.", 400)

    redirect_uri, state = params["redirect_uri"], params["state"]
    if form.get("action") != "approve":
        audit.record(db, "oauth.consent", "denied", client_id=client.client_id, ip=ip)
        return RedirectResponse(f"{redirect_uri}?{urlencode({'error': 'access_denied', 'state': state})}", 302)

    try:
        user = authenticate(db, str(form.get("email", "")), str(form.get("password", "")),
                            str(form.get("totp", "")) or None, ip)
    except AuthError as e:
        return _render_authorize(request, client, params, str(e), 401)

    chosen = {str(v) for v in form.getlist("scopes")} | {sc.MCP_BASE}
    granted = sc.resolve_requested(sc.parse(params["scope"]), user.role) & chosen
    if granted <= {sc.MCP_BASE}:
        return _render_authorize(request, client, params, "Select at least one permission.", 400)

    code = new_token(32)
    db.add(
        AuthorizationCode(
            code_hash=sha256_hex(code),
            client_id=client.client_id,
            user_id=user.id,
            redirect_uri=redirect_uri,
            code_challenge=params["code_challenge"],
            scopes=" ".join(sorted(granted)),
            resource=get_settings().mcp_resource_url,
            expires_at=utcnow() + timedelta(seconds=get_settings().auth_code_ttl),
        )
    )
    audit.record(db, "oauth.consent", user_id=user.id, tenant_id=user.tenant_id, client_id=client.client_id,
                 ip=ip, scopes=sorted(granted))
    query = {"code": code, "state": state, "iss": get_settings().public_url}  # RFC 9207 iss
    return RedirectResponse(f"{redirect_uri}?{urlencode(query)}", status_code=302)


# -------------------------------------------------------------------- token
# 300/min per IP: the MCP server performs token exchange for all its users from one IP
@router.post("/oauth/token", dependencies=[Depends(limit("token", 300, 60))])
def token(
    request: Request,
    grant_type: str = Form(...),
    code: str | None = Form(None),
    redirect_uri: str | None = Form(None),
    code_verifier: str | None = Form(None),
    client_id: str | None = Form(None),
    client_secret: str | None = Form(None),
    refresh_token: str | None = Form(None),
    resource: str | None = Form(None),
    subject_token: str | None = Form(None),
    subject_token_type: str | None = Form(None),
    audience: str | None = Form(None),
    scope: str | None = Form(None),
    db: Session = Depends(get_db),
):
    s = get_settings()
    ip = client_ip(request)

    if resource and resource.rstrip("/") not in (s.mcp_resource_url, s.api_audience):
        return oauth_error("invalid_target", "Unknown resource")

    # ---- authorization_code
    if grant_type == "authorization_code":
        client = _client(db, client_id)
        if not client or not code or not code_verifier or not redirect_uri:
            return oauth_error("invalid_request", "Missing parameters")
        row = db.get(AuthorizationCode, sha256_hex(code))
        if not row or row.client_id != client.client_id:
            return oauth_error("invalid_grant", "Invalid authorization code")
        if row.used:
            # Code replay => assume theft, revoke anything minted from it (RFC 6749 10.5)
            for g in db.execute(select(Grant).where(Grant.client_id == row.client_id, Grant.user_id == row.user_id,
                                                    Grant.revoked_at.is_(None))).scalars():
                revoke_grant(db, g, "authorization code replay")
            audit.record(db, "oauth.code_replay", "denied", user_id=row.user_id, client_id=row.client_id, ip=ip)
            return oauth_error("invalid_grant", "Authorization code already used")
        row.used = True
        if row.expires_at < utcnow() or row.redirect_uri != redirect_uri:
            return oauth_error("invalid_grant", "Expired code or redirect mismatch")
        if not constant_time_eq(pkce_s256(code_verifier), row.code_challenge):
            audit.record(db, "oauth.pkce_fail", "denied", user_id=row.user_id, client_id=row.client_id, ip=ip)
            return oauth_error("invalid_grant", "PKCE verification failed")
        user = db.get(User, row.user_id)
        grant = Grant(id=str(uuid.uuid4()), user_id=user.id, tenant_id=user.tenant_id, client_id=client.client_id,
                      scopes=row.scopes, resource=row.resource)
        db.add(grant)
        db.flush()
        access, ttl = issue_access_token(subject=user.id, tenant_id=user.tenant_id, role=user.role,
                                         client_id=client.client_id, scopes=sc.parse(row.scopes),
                                         audience=row.resource, grant_id=grant.id, ttl=s.access_token_ttl)
        refresh = _issue_refresh(db, grant)
        audit.record(db, "oauth.token_issued", user_id=user.id, tenant_id=user.tenant_id,
                     client_id=client.client_id, ip=ip, grant=grant.id)
        return _token_response({"access_token": access, "token_type": "Bearer", "expires_in": ttl,
                                "refresh_token": refresh, "scope": row.scopes})

    # ---- refresh_token (rotation + reuse detection)
    if grant_type == "refresh_token":
        client = _client(db, client_id)
        if not client or not refresh_token:
            return oauth_error("invalid_request", "Missing parameters")
        rt = db.get(RefreshToken, sha256_hex(refresh_token))
        grant = db.get(Grant, rt.grant_id) if rt else None
        if not rt or not grant or grant.client_id != client.client_id:
            return oauth_error("invalid_grant", "Invalid refresh token")
        if rt.rotated_at is not None:
            revoke_grant(db, grant, "refresh token reuse detected")
            audit.record(db, "oauth.refresh_reuse", "denied", user_id=grant.user_id, tenant_id=grant.tenant_id,
                         client_id=client.client_id, ip=ip, grant=grant.id)
            return oauth_error("invalid_grant", "Refresh token reuse detected; connection revoked")
        user = grant.user
        if (grant.revoked_at or rt.expires_at < utcnow() or not user.is_active or not user.tenant.is_active):
            return oauth_error("invalid_grant", "Refresh token expired or revoked")
        rt.rotated_at = utcnow()
        # Re-apply RBAC: if the user's role was reduced, the new token shrinks too.
        effective = sc.parse(grant.scopes) & sc.allowed_for_role(user.role)
        grant.last_used_at = utcnow()
        access, ttl = issue_access_token(subject=user.id, tenant_id=user.tenant_id, role=user.role,
                                         client_id=client.client_id, scopes=effective, audience=grant.resource,
                                         grant_id=grant.id, ttl=s.access_token_ttl)
        new_refresh = _issue_refresh(db, grant)
        return _token_response({"access_token": access, "token_type": "Bearer", "expires_in": ttl,
                                "refresh_token": new_refresh, "scope": " ".join(sorted(effective))})

    # ---- token exchange (MCP server only)
    if grant_type == TOKEN_EXCHANGE:
        mcp = _authenticate_confidential_client(db, request, client_id, client_secret)
        if not mcp or mcp.client_type != "mcp_server":
            audit.record(db, "oauth.token_exchange", "denied", ip=ip, reason="client_auth")
            return oauth_error("invalid_client", "Client authentication failed", 401)
        if subject_token_type != ACCESS_TOKEN_TYPE or not subject_token:
            return oauth_error("invalid_request", "subject_token of type access_token required")
        if (audience or s.api_audience).rstrip("/") != s.api_audience:
            return oauth_error("invalid_target", "Unknown audience")
        try:
            claims = verify_access_token(subject_token, audience=s.mcp_resource_url)
        except TokenError:
            return oauth_error("invalid_grant", "Subject token invalid")
        grant = db.get(Grant, claims.get("sid"))
        user = db.get(User, int(claims["sub"]))
        if not grant or grant.revoked_at or not user or not user.is_active or not user.tenant.is_active:
            return oauth_error("invalid_grant", "Connection revoked")
        subject_scopes = sc.parse(claims.get("scope")) & sc.allowed_for_role(user.role)
        wanted = sc.parse(scope) or subject_scopes
        effective = wanted & subject_scopes  # can only narrow, never widen
        grant.last_used_at = utcnow()
        access, ttl = issue_access_token(subject=user.id, tenant_id=user.tenant_id, role=user.role,
                                         client_id=claims["client_id"], scopes=effective, audience=s.api_audience,
                                         grant_id=grant.id, ttl=s.api_token_ttl, actor=mcp.client_id)
        return _token_response({"access_token": access, "issued_token_type": ACCESS_TOKEN_TYPE,
                                "token_type": "Bearer", "expires_in": ttl, "scope": " ".join(sorted(effective))})

    return oauth_error("unsupported_grant_type", "Unsupported grant_type")


# ---------------------------------------------------------------- revocation
@router.post("/oauth/revoke", dependencies=[Depends(limit("revoke", 30, 60))])
def revoke(request: Request, token: str = Form(...), client_id: str | None = Form(None),
           db: Session = Depends(get_db)):
    rt = db.get(RefreshToken, sha256_hex(token))
    if rt:
        grant = db.get(Grant, rt.grant_id)
        if grant and (client_id is None or grant.client_id == client_id):
            revoke_grant(db, grant, "revoked by client")
            audit.record(db, "oauth.revoke", user_id=grant.user_id, tenant_id=grant.tenant_id,
                         client_id=grant.client_id, ip=client_ip(request))
    return JSONResponse({}, status_code=200)  # RFC 7009: always 200
