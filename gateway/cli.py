"""Operator CLI.

  python -m gateway.cli init-db
  python -m gateway.cli create-admin --tenant "Acme Ltd" --email admin@acme.bg --name "Admin"
  python -m gateway.cli register-mcp-server        # prints the MCP server client secret ONCE
  python -m gateway.cli seed-demo --tenant "Acme Ltd"
  python -m gateway.cli rotate-keys
  python -m gateway.cli verify-audit
  python -m gateway.cli check-moneta             # test the connection to the Moneta tables
"""

import argparse
import getpass
import random
import sys
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from .config import get_settings
from .db import init_db, session_scope
from .models import Customer, OAuthClient, Order, OrderLine, Product, Tenant, User, utcnow
from .security import audit
from .security.crypto import new_token, sha256_hex
from .security.keys import generate_key
from .security.passwords import hash_password

MCP_CLIENT_ID = "moneta-mcp-server"


def _tenant(db, name: str, create: bool = False) -> Tenant:
    t = db.execute(select(Tenant).where(Tenant.name == name)).scalar_one_or_none()
    if not t and create:
        t = Tenant(name=name)
        db.add(t)
        db.flush()
    if not t:
        sys.exit(f"Tenant '{name}' not found")
    return t


def cmd_create_admin(a):
    password = a.password or getpass.getpass("Password (min 12 chars): ")
    with session_scope() as db:
        if db.execute(select(User).where(User.email == a.email.lower())).first():
            sys.exit(f"User {a.email} already exists")
        t = _tenant(db, a.tenant, create=True)
        u = User(tenant_id=t.id, email=a.email.lower(), full_name=a.name, password_hash=hash_password(password),
                 role=a.role)
        db.add(u)
        db.flush()
        audit.record(db, "cli.user_create", tenant_id=t.id, target=u.id, role=a.role)
    print(f"Created {a.role} {a.email} in tenant '{a.tenant}'")


def cmd_register_mcp(a):
    secret = new_token(32)
    with session_scope() as db:
        c = db.execute(select(OAuthClient).where(OAuthClient.client_id == MCP_CLIENT_ID)).scalar_one_or_none()
        if c is None:
            c = OAuthClient(client_id=MCP_CLIENT_ID, client_name="Moneta MCP Server", client_type="mcp_server",
                            registered_via="cli", redirect_uris="[]")
            db.add(c)
        c.client_secret_hash = sha256_hex(secret)
        audit.record(db, "cli.mcp_secret_rotated", client_id=MCP_CLIENT_ID)
    print("MCP server credentials (store in a secret manager; shown only once):")
    print(f"  MCP_CLIENT_ID={MCP_CLIENT_ID}")
    print(f"  MCP_CLIENT_SECRET={secret}")


def cmd_seed(a):
    rnd = random.Random(42)
    with session_scope() as db:
        t = _tenant(db, a.tenant)
        if db.execute(select(Product).where(Product.tenant_id == t.id)).first():
            print("Tenant already has products; skipping")
            return
        cats = {"Office": ["Paper A4 500", "Stapler", "Desk organiser", "Ballpoint pen x10", "Notebook A5"],
                "IT": ["USB-C cable 1m", "Wireless mouse", "Keyboard BG/US", "27in monitor", "Laptop stand"],
                "Coffee": ["Espresso beans 1kg", "Paper cups x100", "Sugar sticks x500", "Milk 1L", "Filter coffee"]}
        products = []
        for cat, names in cats.items():
            for i, n in enumerate(names):
                products.append(Product(tenant_id=t.id, sku=f"{cat[:3].upper()}-{i + 1:03d}", name=n, category=cat,
                                        unit_price=Decimal(rnd.randint(200, 40000)) / 100, stock_qty=rnd.randint(20, 500)))
        customers = [Customer(tenant_id=t.id, code=f"C{i:04d}", name=n, city=c) for i, (n, c) in enumerate([
            ("Sofia Tech OOD", "Sofia"), ("Plovdiv Trade EOOD", "Plovdiv"), ("Varna Marine AD", "Varna"),
            ("Burgas Logistics", "Burgas"), ("Ruse Foods", "Ruse")], start=1)]
        db.add_all(products + customers)
        db.flush()
        creator = db.execute(select(User).where(User.tenant_id == t.id)).scalars().first()
        for n in range(120):
            lines = rnd.sample(products, rnd.randint(1, 4))
            o = Order(tenant_id=t.id, order_number=f"SO-{n + 1:06d}", customer=rnd.choice(customers), status="confirmed",
                      idempotency_key=f"seed-{n}", created_by_user_id=creator.id, created_via_client_id="seed",
                      created_at=utcnow() - timedelta(days=rnd.randint(0, 180)),
                      total_net=0, total_vat=0, total_gross=0)
            net = vat = Decimal(0)
            for p in lines:
                q = rnd.randint(1, 10)
                ln = (p.unit_price * q).quantize(Decimal("0.01"))
                net += ln
                vat += (ln * p.vat_rate / 100).quantize(Decimal("0.01"))
                o.lines.append(OrderLine(product=p, quantity=q, unit_price=p.unit_price, vat_rate=p.vat_rate, line_net=ln))
            o.total_net, o.total_vat, o.total_gross = net, vat, net + vat
            db.add(o)
    print(f"Seeded demo data for '{a.tenant}'")


def cmd_check_moneta(a):
    """Test the GATEWAY_ERP_ODBC connection and show what the API will see."""
    import json

    from .services import moneta

    try:
        info = moneta.status()
    except Exception as e:  # show the real driver/connection error to the operator
        sys.exit(f"Could not connect to the Moneta database: {getattr(e, 'detail', e)}")
    print(json.dumps(info, indent=2, ensure_ascii=False, default=str))


def cmd_verify_audit(a):
    with session_scope() as db:
        ok, broken = audit.verify_chain(db)
    print("Audit chain OK" if ok else f"Audit chain BROKEN at id {broken}")
    sys.exit(0 if ok else 2)


def main(argv=None):
    p = argparse.ArgumentParser(prog="gateway.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db").set_defaults(fn=lambda a: (init_db(), print("Tables created")))
    ca = sub.add_parser("create-admin")
    ca.add_argument("--tenant", required=True)
    ca.add_argument("--email", required=True)
    ca.add_argument("--name", required=True)
    ca.add_argument("--role", default="admin", choices=["admin", "manager", "sales", "viewer"])
    ca.add_argument("--password", help="omit to be prompted (recommended; avoids shell history)")
    ca.set_defaults(fn=cmd_create_admin)
    sub.add_parser("register-mcp-server").set_defaults(fn=cmd_register_mcp)
    sd = sub.add_parser("seed-demo")
    sd.add_argument("--tenant", required=True)
    sd.set_defaults(fn=cmd_seed)
    sub.add_parser("rotate-keys").set_defaults(fn=lambda a: print(f"New signing key: {generate_key().kid}"))
    sub.add_parser("verify-audit").set_defaults(fn=cmd_verify_audit)
    sub.add_parser("check-moneta").set_defaults(fn=cmd_check_moneta)
    a = p.parse_args(argv)
    if a.cmd not in ("init-db", "check-moneta") and get_settings().auto_create_tables:
        init_db()
    a.fn(a)


if __name__ == "__main__":
    main()
