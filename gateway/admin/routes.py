"""Administrator panel (server-rendered, no JavaScript).

Each customer company is a tenant; its admins manage only their own users,
AI connections and audit trail. Protections: server-side sessions with
idle timeout, __Host- cookie prefix, SameSite=Strict, CSRF token on every
POST, MFA (TOTP) enforced outside dev, strict CSP, rate-limited login.
"""

from datetime import timedelta
from pathlib import Path
from urllib.parse import quote

import pyotp
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import AdminSession, AuditLog, Grant, OAuthClient, User, utcnow
from ..oauth.routes import revoke_grant
from ..security import audit, csrf
from ..security import scopes as sc
from ..security.authn import AuthError, authenticate
from ..security.crypto import decrypt_field, encrypt_field, new_token, sha256_hex
from ..security.passwords import hash_password
from ..security.ratelimit import client_ip, limit

router = APIRouter(prefix="/admin", include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
PRELOGIN_COOKIE = "admin_prelogin"


def cookie_name() -> str:
    # __Host- prefix: browser enforces Secure, Path=/ and no Domain (no subdomain leakage)
    return "admin_session" if get_settings().is_dev else "__Host-admin_session"


class AdminContext:
    def __init__(self, session: AdminSession, raw_sid: str):
        self.session, self.user, self.raw_sid = session, session.user, raw_sid
        self.csrf_token = csrf.issue(raw_sid)


class _LoginRedirect(Exception):
    pass


def current_admin(request: Request, db: Session = Depends(get_db)) -> AdminContext:
    raw = request.cookies.get(cookie_name())
    sess = db.get(AdminSession, sha256_hex(raw)) if raw else None
    if not sess or sess.expires_at < utcnow() or not sess.user.is_active or sess.user.role not in sc.ADMIN_PANEL_ROLES:
        raise HTTPException(303, headers={"Location": "/admin/login"})
    sess.expires_at = utcnow() + timedelta(seconds=get_settings().admin_session_ttl)  # sliding idle timeout
    ctx = AdminContext(sess, raw)
    # Enforce MFA for administrators outside development.
    if not get_settings().is_dev and not sess.user.mfa_secret_enc and not request.url.path.startswith("/admin/mfa"):
        raise HTTPException(303, headers={"Location": "/admin/mfa"})
    return ctx


async def checked_form(request: Request, ctx: AdminContext = Depends(current_admin)):
    form = await request.form()
    if not csrf.verify(str(form.get("csrf_token", "")), ctx.raw_sid):
        raise HTTPException(403, "CSRF validation failed")
    return form


def render(request: Request, name: str, ctx: AdminContext | None = None, status: int = 200, **kw):
    return templates.TemplateResponse(
        request, name, {"admin": ctx, "settings": get_settings(), **kw}, status_code=status
    )


# ---------------------------------------------------------------- login
@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str | None = None):
    binding = request.cookies.get(PRELOGIN_COOKIE) or new_token(16)
    resp = render(request, "login.html", csrf_token=csrf.issue(binding), error=error)
    resp.set_cookie(PRELOGIN_COOKIE, binding, httponly=True, secure=not get_settings().is_dev, samesite="strict")
    return resp


@router.post("/login", dependencies=[Depends(limit("admin-login", 10, 300))])
def login(
    request: Request,
    email: str = Form(..., max_length=254),
    password: str = Form(..., max_length=256),
    totp: str = Form("", max_length=10),
    csrf_token: str = Form(""),
    db: Session = Depends(get_db),
):
    if not csrf.verify(csrf_token, request.cookies.get(PRELOGIN_COOKIE)):
        return login_page(request, "Session expired, please try again.")
    try:
        user = authenticate(db, email, password, totp or None, client_ip(request))
    except AuthError as e:
        return login_page(request, str(e))
    if user.role not in sc.ADMIN_PANEL_ROLES:
        audit.record(db, "admin.login", "denied", user_id=user.id, tenant_id=user.tenant_id, ip=client_ip(request))
        return login_page(request, "This account cannot access the administrator panel.")

    raw = new_token(32)  # fresh session id on every login (no session fixation)
    db.add(AdminSession(id_hash=sha256_hex(raw), user_id=user.id, ip=client_ip(request),
                        expires_at=utcnow() + timedelta(seconds=get_settings().admin_session_ttl)))
    audit.record(db, "admin.login", user_id=user.id, tenant_id=user.tenant_id, ip=client_ip(request))
    resp = RedirectResponse("/admin", status_code=303)
    resp.set_cookie(cookie_name(), raw, httponly=True, secure=not get_settings().is_dev, samesite="strict",
                    path="/", max_age=8 * 3600)
    resp.delete_cookie(PRELOGIN_COOKIE)
    return resp


@router.post("/logout")
def logout(request: Request, ctx: AdminContext = Depends(current_admin), form=Depends(checked_form),
           db: Session = Depends(get_db)):
    db.delete(ctx.session)
    audit.record(db, "admin.logout", user_id=ctx.user.id, tenant_id=ctx.user.tenant_id, ip=client_ip(request))
    resp = RedirectResponse("/admin/login", status_code=303)
    resp.delete_cookie(cookie_name(), path="/")
    return resp


# ------------------------------------------------------------ dashboard
@router.get("", response_class=HTMLResponse)
def dashboard(request: Request, ctx: AdminContext = Depends(current_admin), db: Session = Depends(get_db)):
    tid = ctx.user.tenant_id
    stats = {
        "users": db.scalar(select(func.count()).select_from(User).where(User.tenant_id == tid)),
        "connections": db.scalar(select(func.count()).select_from(Grant).where(
            Grant.tenant_id == tid, Grant.revoked_at.is_(None))),
        "events_24h": db.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.tenant_id == tid, AuditLog.ts >= utcnow() - timedelta(days=1))),
        "denied_24h": db.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.tenant_id == tid, AuditLog.outcome == "denied", AuditLog.ts >= utcnow() - timedelta(days=1))),
    }
    return render(request, "dashboard.html", ctx, stats=stats)


@router.get("/agents", response_class=HTMLResponse)
def agents(request: Request, ctx: AdminContext = Depends(current_admin)):
    return render(request, "agents.html", ctx)


# ---------------------------------------------------------------- users
@router.get("/users", response_class=HTMLResponse)
def users(request: Request, ctx: AdminContext = Depends(current_admin), db: Session = Depends(get_db),
          error: str | None = None, message: str | None = None):
    rows = db.execute(select(User).where(User.tenant_id == ctx.user.tenant_id).order_by(User.email)).scalars().all()
    return render(request, "users.html", ctx, users=rows, roles=list(sc.ROLES), role_scopes=sc.ROLES,
                  error=error, message=message)


@router.post("/users")
def create_user(request: Request, ctx: AdminContext = Depends(current_admin), form=Depends(checked_form),
                db: Session = Depends(get_db)):
    email = str(form.get("email", "")).strip().lower()[:254]
    role = str(form.get("role", "viewer"))
    if role not in sc.ROLES or "@" not in email:
        return users(request, ctx, db, error="Invalid email or role")
    if db.scalar(select(func.count()).select_from(User).where(func.lower(User.email) == email)):
        return users(request, ctx, db, error="A user with this email already exists")
    try:
        pw_hash = hash_password(str(form.get("password", "")))
    except ValueError as e:
        return users(request, ctx, db, error=str(e))
    user = User(tenant_id=ctx.user.tenant_id, email=email, full_name=str(form.get("full_name", ""))[:200],
                password_hash=pw_hash, role=role)
    db.add(user)
    db.flush()
    audit.record(db, "admin.user_create", user_id=ctx.user.id, tenant_id=ctx.user.tenant_id,
                 ip=client_ip(request), target=user.id, role=role)
    return RedirectResponse("/admin/users", status_code=303)


def _tenant_user(db: Session, ctx: AdminContext, user_id: int) -> User:
    user = db.get(User, user_id)
    if not user or user.tenant_id != ctx.user.tenant_id:  # no cross-tenant access (IDOR)
        raise HTTPException(404)
    return user


@router.post("/users/{user_id}/update")
def update_user(user_id: int, request: Request, ctx: AdminContext = Depends(current_admin),
                form=Depends(checked_form), db: Session = Depends(get_db)):
    user = _tenant_user(db, ctx, user_id)
    if user.id == ctx.user.id:
        return users(request, ctx, db, error="You cannot change your own account here")
    action = form.get("action")
    if action == "toggle":
        user.is_active = not user.is_active
        if not user.is_active:  # disabling a user kills all their AI connections at once
            for g in db.execute(select(Grant).where(Grant.user_id == user.id, Grant.revoked_at.is_(None))).scalars():
                revoke_grant(db, g, "user disabled")
    elif action == "role" and form.get("role") in sc.ROLES:
        user.role = str(form.get("role"))
    elif action == "reset_mfa":
        user.mfa_secret_enc = None
    elif action == "unlock":
        user.locked_until, user.failed_logins = None, 0
    else:
        raise HTTPException(400)
    audit.record(db, f"admin.user_{action}", user_id=ctx.user.id, tenant_id=ctx.user.tenant_id,
                 ip=client_ip(request), target=user.id)
    return RedirectResponse("/admin/users", status_code=303)


# ------------------------------------------------------------------ MFA
@router.get("/mfa", response_class=HTMLResponse)
def mfa_page(request: Request, ctx: AdminContext = Depends(current_admin), error: str | None = None):
    secret = pyotp.random_base32()
    ctx.session.mfa_pending_enc = encrypt_field(secret)
    uri = pyotp.TOTP(secret).provisioning_uri(name=ctx.user.email, issuer_name="Moneta AI Gateway")
    return render(request, "mfa.html", ctx, secret=secret, uri=uri, uri_quoted=quote(uri), error=error,
                  enabled=bool(ctx.user.mfa_secret_enc))


@router.post("/mfa")
def mfa_confirm(request: Request, ctx: AdminContext = Depends(current_admin), form=Depends(checked_form),
                db: Session = Depends(get_db)):
    pending = ctx.session.mfa_pending_enc
    code = str(form.get("code", "")).strip()
    if not pending or not pyotp.TOTP(decrypt_field(pending)).verify(code, valid_window=1):
        return mfa_page(request, ctx, error="Code did not match, scan the new secret and try again")
    ctx.user.mfa_secret_enc, ctx.session.mfa_pending_enc = pending, None
    audit.record(db, "admin.mfa_enabled", user_id=ctx.user.id, tenant_id=ctx.user.tenant_id, ip=client_ip(request))
    return RedirectResponse("/admin", status_code=303)


# ------------------------------------------------------ AI connections
@router.get("/connections", response_class=HTMLResponse)
def connections(request: Request, ctx: AdminContext = Depends(current_admin), db: Session = Depends(get_db)):
    grants = db.execute(select(Grant).where(Grant.tenant_id == ctx.user.tenant_id)
                        .order_by(Grant.created_at.desc()).limit(200)).scalars().all()
    client_ids = {g.client_id for g in grants}
    clients = {c.client_id: c for c in db.execute(
        select(OAuthClient).where(OAuthClient.client_id.in_(client_ids))).scalars()} if client_ids else {}
    return render(request, "connections.html", ctx, grants=grants, clients=clients)


@router.post("/connections/{grant_id}/revoke")
def revoke_connection(grant_id: str, request: Request, ctx: AdminContext = Depends(current_admin),
                      form=Depends(checked_form), db: Session = Depends(get_db)):
    grant = db.get(Grant, grant_id)
    if not grant or grant.tenant_id != ctx.user.tenant_id:
        raise HTTPException(404)
    revoke_grant(db, grant, f"revoked by admin {ctx.user.id}")
    audit.record(db, "admin.connection_revoke", user_id=ctx.user.id, tenant_id=ctx.user.tenant_id,
                 ip=client_ip(request), grant=grant.id, client=grant.client_id)
    return RedirectResponse("/admin/connections", status_code=303)


# ---------------------------------------------------------------- audit
@router.get("/audit", response_class=HTMLResponse)
def audit_page(request: Request, ctx: AdminContext = Depends(current_admin), db: Session = Depends(get_db)):
    rows = db.execute(select(AuditLog).where(AuditLog.tenant_id == ctx.user.tenant_id)
                      .order_by(AuditLog.id.desc()).limit(200)).scalars().all()
    ok, broken_at = audit.verify_chain(db)
    return render(request, "audit.html", ctx, rows=rows, chain_ok=ok, broken_at=broken_at)
