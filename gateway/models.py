"""ORM models.

Two groups of tables:
* Gateway/security tables (tenants, users, OAuth clients, grants, tokens, audit).
* Demo ERP tables (products, customers, orders). In a real Moneta deployment
  these are replaced by Moneta's own tables/views through the service layer
  (see docs/05-mssql-connection.md, "Mapping to the real Moneta schema").

Every business row carries ``tenant_id``; the service layer always filters by
the tenant taken from the verified token, never from user input.
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    Numeric,
    UniqueConstraint,
)
from sqlalchemy import DateTime as _DateTime
from sqlalchemy import Unicode, UnicodeText
from sqlalchemy.dialects.mssql import DATETIME2
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


# SQL Server types: NVARCHAR for text (Cyrillic/Bulgarian safe), NVARCHAR(MAX)
# instead of deprecated TEXT, DATETIME2 instead of DATETIME.
String = Unicode
Text = UnicodeText
DateTime = _DateTime().with_variant(DATETIME2(), "mssql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # stored as naive UTC


# --------------------------------------------------------------------- tenants
class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="viewer")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # TOTP secret, encrypted at rest with AES-GCM (see security/crypto.py)
    mfa_secret_enc: Mapped[str | None] = mapped_column(String(255), nullable=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    tenant: Mapped[Tenant] = relationship()


# ----------------------------------------------------------------------- OAuth
class OAuthClient(Base):
    """An AI application (Claude, ChatGPT, Cursor...) or the MCP server itself."""

    __tablename__ = "oauth_clients"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[str] = mapped_column(String(100), unique=True)
    client_name: Mapped[str] = mapped_column(String(200))
    redirect_uris: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    # Confidential clients (the MCP server) have a secret; AI chat apps are public + PKCE.
    client_secret_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # "public" | "mcp_server"
    client_type: Mapped[str] = mapped_column(String(20), default="public")
    registered_via: Mapped[str] = mapped_column(String(20), default="dcr")  # dcr | admin | cli
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuthorizationCode(Base):
    __tablename__ = "oauth_codes"
    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)  # SHA-256, never the raw code
    client_id: Mapped[str] = mapped_column(String(100))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    redirect_uri: Mapped[str] = mapped_column(String(500))
    code_challenge: Mapped[str] = mapped_column(String(128))
    scopes: Mapped[str] = mapped_column(String(500))
    resource: Mapped[str] = mapped_column(String(500))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class Grant(Base):
    """One user's consent for one AI client ("a connection"). Revoking it kills
    every access and refresh token issued under it, immediately."""

    __tablename__ = "oauth_grants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # uuid4, JWT claim "sid"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"))
    client_id: Mapped[str] = mapped_column(String(100))
    scopes: Mapped[str] = mapped_column(String(500))
    resource: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    user: Mapped[User] = relationship()


class RefreshToken(Base):
    __tablename__ = "oauth_refresh_tokens"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    grant_id: Mapped[str] = mapped_column(ForeignKey("oauth_grants.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ----------------------------------------------------------------------- audit
class AuditLog(Base):
    """Append-only, hash-chained. In SQL Server the app login is DENIED
    UPDATE/DELETE on this table (sql/mssql/02_security.sql)."""

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    tenant_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    action: Mapped[str] = mapped_column(String(100))
    outcome: Mapped[str] = mapped_column(String(20))  # success | denied | error
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="{}")
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


# ------------------------------------------------------------- demo ERP tables
class Product(Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("tenant_id", "sku", name="uq_products_tenant_sku"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    sku: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("20.00"))
    stock_qty: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_customers_tenant_code"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_orders_tenant_idem"),
        UniqueConstraint("tenant_id", "order_number", name="uq_orders_tenant_number"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    order_number: Mapped[str] = mapped_column(String(32))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    total_net: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    total_vat: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    total_gross: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(64))
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_via_client_id: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    customer: Mapped[Customer] = relationship()
    lines: Mapped[list["OrderLine"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderLine(Base):
    __tablename__ = "order_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    line_net: Mapped[Decimal] = mapped_column(Numeric(18, 2))

    order: Mapped[Order] = relationship(back_populates="lines")
    product: Mapped[Product] = relationship()


class AdminSession(Base):
    """Server-side admin panel sessions (revocable, idle-timeout)."""

    __tablename__ = "admin_sessions"
    id_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    # TOTP secret being enrolled (encrypted), moved to the user once confirmed
    mfa_pending_enc: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user: Mapped[User] = relationship()
