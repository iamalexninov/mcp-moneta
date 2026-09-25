from urllib.parse import parse_qs, urlparse

import jwt

from gateway.config import get_settings

from .conftest import PASSWORD, REDIRECT, api_token, authorize, login_tokens, register


def test_metadata_advertises_pkce_and_dcr(client):
    m = client.get("/.well-known/oauth-authorization-server").json()
    assert m["code_challenge_methods_supported"] == ["S256"]
    assert m["registration_endpoint"].endswith("/oauth/register")
    assert "none" in m["token_endpoint_auth_methods_supported"]


def test_dcr_rejects_unlisted_redirect(client):
    r = client.post("/oauth/register", json={"redirect_uris": ["https://evil.example/cb"]})
    assert r.status_code == 400 and r.json()["error"] == "invalid_redirect_uri"


def test_dcr_rejects_confidential_self_registration(client):
    r = client.post("/oauth/register", json={"redirect_uris": [REDIRECT], "token_endpoint_auth_method": "client_secret_basic"})
    assert r.status_code == 400


def test_loopback_redirect_any_port(client):
    r = client.post("/oauth/register", json={"redirect_uris": ["http://127.0.0.1:53682/callback"]})
    assert r.status_code == 201


def test_authorize_unknown_redirect_is_not_followed(client):
    cid = register(client)
    r = client.get("/oauth/authorize", params={"client_id": cid, "redirect_uri": "https://evil.example/cb",
                                               "response_type": "code", "code_challenge": "x" * 43,
                                               "code_challenge_method": "S256"})
    assert r.status_code == 400 and "location" not in r.headers


def test_pkce_plain_rejected(client):
    cid = register(client)
    r = client.get("/oauth/authorize", params={"client_id": cid, "redirect_uri": REDIRECT, "response_type": "code",
                                               "code_challenge": "x" * 43, "code_challenge_method": "plain"})
    assert r.status_code == 302 and "error=invalid_request" in r.headers["location"]


def test_wrong_password_gives_generic_error(client):
    cid = register(client)
    r, _ = authorize(client, cid, password="wrong-password-123")
    assert r.status_code == 401 and "Invalid email, password or code" in r.text


def test_full_flow_and_token_claims(client):
    _, tok = login_tokens(client)
    claims = jwt.decode(tok["access_token"], options={"verify_signature": False})
    assert claims["aud"] == get_settings().mcp_resource_url
    assert claims["tid"] and claims["sid"]
    assert jwt.get_unverified_header(tok["access_token"])["alg"] == "ES256"


def test_pkce_verifier_mismatch(client):
    cid = register(client)
    r, _ = authorize(client, cid)
    code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]
    t = client.post("/oauth/token", data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
                                          "client_id": cid, "code_verifier": "A" * 50})
    assert t.status_code == 400 and t.json()["error"] == "invalid_grant"


def test_code_replay_revokes(client, mcp_secret):
    cid = register(client)
    r, verifier = authorize(client, cid)
    code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT, "client_id": cid,
            "code_verifier": verifier}
    first = client.post("/oauth/token", data=data)
    assert first.status_code == 200
    assert client.post("/oauth/token", data=data).status_code == 400
    # the tokens from the first redemption are now dead
    assert api_token(client, mcp_secret, first.json()["access_token"]).status_code == 400


def test_refresh_rotation_and_reuse_detection(client, mcp_secret):
    cid, tok = login_tokens(client)
    r1 = client.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
                                           "client_id": cid})
    assert r1.status_code == 200 and r1.json()["refresh_token"] != tok["refresh_token"]
    # attacker replays the old refresh token -> whole connection revoked
    r2 = client.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
                                           "client_id": cid})
    assert r2.status_code == 400 and r2.json()["error"] == "invalid_grant"
    r3 = client.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": r1.json()["refresh_token"],
                                           "client_id": cid})
    assert r3.status_code == 400


def test_token_exchange_requires_mcp_client_auth(client, mcp_secret):
    _, tok = login_tokens(client)
    assert api_token(client, "wrong-secret", tok["access_token"]).status_code == 401
    ok = api_token(client, mcp_secret, tok["access_token"])
    assert ok.status_code == 200
    claims = jwt.decode(ok.json()["access_token"], options={"verify_signature": False})
    assert claims["aud"] == get_settings().api_audience and claims["act"]["sub"] == "moneta-mcp-server"


def test_token_exchange_can_only_narrow(client, mcp_secret):
    _, tok = login_tokens(client, scopes=["reports:read"])
    r = api_token(client, mcp_secret, tok["access_token"], scope="reports:read orders:write")
    assert r.status_code == 200 and "orders:write" not in r.json()["scope"]


def test_lockout_after_repeated_failures(client):
    cid = register(client)
    for _ in range(5):
        authorize(client, cid, email="viewer@a.bg", password="bad-password-xyz")
    r, _ = authorize(client, cid, email="viewer@a.bg", password=PASSWORD)
    assert r.status_code == 401 and "locked" in r.text
    # unlock for other tests
    from gateway.db import session_scope
    from gateway.models import User
    from sqlalchemy import select
    with session_scope() as db:
        u = db.execute(select(User).where(User.email == "viewer@a.bg")).scalar_one()
        u.locked_until = None
