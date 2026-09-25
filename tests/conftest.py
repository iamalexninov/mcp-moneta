import base64
import hashlib
import os
import re
import secrets
import tempfile
from urllib.parse import parse_qs, urlparse

_tmp = tempfile.mkdtemp()
# Set TEST_DATABASE_URL to run the suite against SQL Server (use an EMPTY throwaway database).
os.environ["GATEWAY_DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.pop("GATEWAY_DB_SCHEMA", None)
os.environ["GATEWAY_AUTO_CREATE_TABLES"] = "true"
os.environ["GATEWAY_KEYS_DIR"] = f"{_tmp}/keys"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from gateway import cli  # noqa: E402
from gateway.config import get_settings  # noqa: E402
from gateway.main import app  # noqa: E402
from gateway.security.ratelimit import limiter  # noqa: E402

PASSWORD = "Str0ng-Test-Passw0rd!"
REDIRECT = "https://claude.ai/api/mcp/auth_callback"
_mcp_secret: dict = {}


def pytest_configure(config):
    cli.main(["init-db"])
    cli.main(["create-admin", "--tenant", "Tenant A", "--email", "admin@a.bg", "--name", "A", "--password", PASSWORD])
    cli.main(["create-admin", "--tenant", "Tenant A", "--email", "viewer@a.bg", "--name", "V", "--role", "viewer",
              "--password", PASSWORD])
    cli.main(["create-admin", "--tenant", "Tenant B", "--email", "admin@b.bg", "--name", "B", "--password", PASSWORD])
    cli.main(["seed-demo", "--tenant", "Tenant A"])
    cli.main(["seed-demo", "--tenant", "Tenant B"])


@pytest.fixture
def client():
    limiter.reset()
    return TestClient(app, base_url="http://testserver", follow_redirects=False)


@pytest.fixture(scope="session")
def mcp_secret():
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        cli.main(["register-mcp-server"])
    return re.search(r"MCP_CLIENT_SECRET=(\S+)", buf.getvalue()).group(1)


def register(client) -> str:
    r = client.post("/oauth/register", json={"client_name": "Test", "redirect_uris": [REDIRECT]})
    assert r.status_code == 201, r.text
    return r.json()["client_id"]


def pkce():
    v = secrets.token_urlsafe(48)
    c = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()
    return v, c


def authorize(client, client_id, email="admin@a.bg", password=PASSWORD, scopes=None, challenge=None):
    verifier, ch = pkce()
    challenge = challenge or ch
    params = {"response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT, "state": "s1",
              "scope": "mcp", "code_challenge": challenge, "code_challenge_method": "S256",
              "resource": get_settings().mcp_resource_url}
    page = client.get("/oauth/authorize", params=params)
    assert page.status_code == 200, page.text
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    all_scopes = re.findall(r'name="scopes" value="([^"]+)"', page.text)
    form = {**params, "csrf_token": csrf, "email": email, "password": password, "action": "approve",
            "scopes": scopes if scopes is not None else all_scopes}
    r = client.post("/oauth/authorize", data=form)
    return r, verifier


def login_tokens(client, email="admin@a.bg", scopes=None):
    cid = register(client)
    r, verifier = authorize(client, cid, email=email, scopes=scopes)
    assert r.status_code == 302, r.text
    code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]
    t = client.post("/oauth/token", data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
                                          "client_id": cid, "code_verifier": verifier})
    assert t.status_code == 200, t.text
    return cid, t.json()


def api_token(client, mcp_secret, mcp_token, scope=None):
    data = {"grant_type": "urn:ietf:params:oauth:grant-type:token-exchange", "subject_token": mcp_token,
            "subject_token_type": "urn:ietf:params:oauth:token-type:access_token"}
    if scope:
        data["scope"] = scope
    r = client.post("/oauth/token", data=data, auth=("moneta-mcp-server", mcp_secret))
    return r
