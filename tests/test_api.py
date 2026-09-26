
import jwt

from gateway.db import session_scope
from gateway.models import Grant
from gateway.security import audit
from gateway.security.keys import load_keys

from .conftest import api_token, login_tokens


def _api(client, mcp_secret, email="admin@a.bg", scopes=None):
    _, tok = login_tokens(client, email=email, scopes=scopes)
    r = api_token(client, mcp_secret, tok["access_token"])
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, tok


def test_no_token_401(client):
    assert client.get("/api/v1/me").status_code == 401


def test_mcp_audience_token_rejected_by_api(client):
    _, tok = login_tokens(client)
    r = client.get("/api/v1/me", headers={"Authorization": f"Bearer {tok['access_token']}"})
    assert r.status_code == 401  # audience confusion / token passthrough blocked


def test_alg_none_and_foreign_key_rejected(client):
    forged = jwt.encode({"sub": "1", "aud": "x"}, key=None, algorithm="none")
    assert client.get("/api/v1/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    hs = jwt.encode({"sub": "1"}, "secret", algorithm="HS256", headers={"kid": load_keys()[0].kid})
    assert client.get("/api/v1/me", headers={"Authorization": f"Bearer {hs}"}).status_code == 401


def test_sales_report(client, mcp_secret):
    h, _ = _api(client, mcp_secret)
    r = client.get("/api/v1/reports/sales", params={"date_from": "2026-01-01", "date_to": "2026-12-31",
                                                    "group_by": "month"}, headers=h)
    assert r.status_code == 200 and r.json()["order_count"] > 0


def test_report_period_limit(client, mcp_secret):
    h, _ = _api(client, mcp_secret)
    r = client.get("/api/v1/reports/sales", params={"date_from": "2020-01-01", "date_to": "2026-12-31"}, headers=h)
    assert r.status_code == 422


def test_viewer_cannot_create_order(client, mcp_secret):
    h, _ = _api(client, mcp_secret, email="viewer@a.bg")
    r = client.post("/api/v1/orders", headers=h, json={"customer_code": "C0001", "lines": [{"sku": "OFF-001", "quantity": 1}],
                                                        "idempotency_key": "viewer-attempt-1"})
    assert r.status_code == 403


def test_unticked_scope_is_enforced(client, mcp_secret):
    h, _ = _api(client, mcp_secret, scopes=["reports:read"])
    r = client.get("/api/v1/products", headers=h)
    assert r.status_code == 403


def test_import_dry_run_then_commit(client, mcp_secret):
    h, _ = _api(client, mcp_secret)
    body = {"items": [{"sku": "NEW-100", "name": "New thing", "unit_price": "12.50"}], "dry_run": True}
    r = client.post("/api/v1/products/import", headers=h, json=body)
    assert r.json()["created"] == 1
    assert client.get("/api/v1/products", params={"q": "NEW-100"}, headers=h).json() == []
    body["dry_run"] = False
    client.post("/api/v1/products/import", headers=h, json=body)
    assert len(client.get("/api/v1/products", params={"q": "NEW-100"}, headers=h).json()) == 1


def test_import_rejects_unknown_fields_and_bad_sku(client, mcp_secret):
    h, _ = _api(client, mcp_secret)
    r = client.post("/api/v1/products/import", headers=h,
                    json={"items": [{"sku": "X1", "name": "a", "unit_price": 1, "tenant_id": 2}]})
    assert r.status_code == 422
    r = client.post("/api/v1/products/import", headers=h,
                    json={"items": [{"sku": "'; DROP TABLE products;--", "name": "a", "unit_price": 1}]})
    assert r.status_code == 422


def test_order_prices_from_db_and_idempotent(client, mcp_secret):
    h, _ = _api(client, mcp_secret)
    body = {"customer_code": "C0002", "lines": [{"sku": "IT-001", "quantity": 1}], "idempotency_key": "idem-test-0001"}
    a = client.post("/api/v1/orders", headers=h, json=body)
    b = client.post("/api/v1/orders", headers=h, json=body)
    assert a.status_code == b.status_code == 201
    assert a.json()["order_number"] == b.json()["order_number"] and b.json()["idempotent_replay"]
    assert a.json()["status"] == "draft"
    r = client.post("/api/v1/orders", headers=h, json={**body, "idempotency_key": "idem-test-0002",
                                                       "lines": [{"sku": "IT-001", "quantity": 1, "unit_price": 0}]})
    assert r.status_code == 422  # client-supplied price field refused


def test_tenant_isolation(client, mcp_secret):
    ha, _ = _api(client, mcp_secret, email="admin@a.bg")
    hb, _ = _api(client, mcp_secret, email="admin@b.bg")
    body = {"items": [{"sku": "ONLY-A", "name": "Tenant A secret", "unit_price": 1}], "dry_run": False}
    client.post("/api/v1/products/import", headers=ha, json=body)
    assert client.get("/api/v1/products", params={"q": "ONLY-A"}, headers=hb).json() == []


def test_like_wildcards_escaped(client, mcp_secret):
    h, _ = _api(client, mcp_secret)
    assert client.get("/api/v1/products", params={"q": "%"}, headers=h).json() == []


def test_revocation_is_immediate(client, mcp_secret):
    h, tok = _api(client, mcp_secret)
    assert client.get("/api/v1/me", headers=h).status_code == 200
    sid = jwt.decode(tok["access_token"], options={"verify_signature": False})["sid"]
    with session_scope() as db:
        db.get(Grant, sid).revoked_at = __import__("gateway.models", fromlist=["utcnow"]).utcnow()
    assert client.get("/api/v1/me", headers=h).status_code == 401


def test_audit_chain_detects_tampering(client):
    from gateway.models import AuditLog
    from sqlalchemy import select
    with session_scope() as db:
        assert audit.verify_chain(db)[0]
        row = db.execute(select(AuditLog).order_by(AuditLog.id).limit(1)).scalar_one()
        original = row.detail
        row.detail = '{"tampered": true}'
        db.flush()
        ok, broken = audit.verify_chain(db)
        assert not ok and broken == row.id
        row.detail = original


def test_security_headers(client):
    r = client.get("/admin/login")
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]


def test_admin_requires_login_and_csrf(client):
    assert client.get("/admin").status_code == 303
    r = client.post("/admin/login", data={"email": "admin@a.bg", "password": "x" * 12, "csrf_token": "forged"})
    assert "Session expired" in r.text


def test_chunked_body_accepted_but_size_capped(client):
    # tunnels/HTTP2 proxies forward bodies without Content-Length: must work
    import json as _json
    body = _json.dumps({"redirect_uris": ["https://claude.ai/api/mcp/auth_callback"]}).encode()
    r = client.post("/oauth/register", content=iter([body]), headers={"content-type": "application/json"})
    assert r.status_code == 201
    big = iter([b"x" * 600_000, b"x" * 600_000])
    r = client.post("/oauth/register", content=big, headers={"content-type": "application/json"})
    assert r.status_code == 413
