import re

from .conftest import PASSWORD, login_tokens


def _login(client):
    page = client.get("/admin/login")
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    r = client.post("/admin/login", data={"email": "admin@a.bg", "password": PASSWORD, "csrf_token": csrf})
    assert r.status_code == 303 and r.headers["location"] == "/admin"


def test_admin_pages_render(client):
    login_tokens(client)  # make sure there is a connection to list
    _login(client)
    for path in ["/admin", "/admin/agents", "/admin/users", "/admin/connections", "/admin/audit", "/admin/mfa"]:
        r = client.get(path)
        assert r.status_code == 200, (path, r.text[:300])
    assert "Hash chain verified" in client.get("/admin/audit").text


def test_viewer_cannot_use_admin_panel(client):
    page = client.get("/admin/login")
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    r = client.post("/admin/login", data={"email": "viewer@a.bg", "password": PASSWORD, "csrf_token": csrf})
    assert "cannot access the administrator panel" in r.text


def test_admin_post_without_csrf_rejected(client):
    _login(client)
    r = client.post("/admin/users", data={"email": "x@a.bg", "full_name": "X", "password": "Another-Strong-Pw1",
                                          "role": "viewer"})
    assert r.status_code == 403


def test_admin_revokes_connection(client):
    _, tok = login_tokens(client)
    _login(client)
    page = client.get("/admin/connections").text
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    gid = re.search(r'/admin/connections/([0-9a-f-]{36})/revoke', page).group(1)
    assert client.post(f"/admin/connections/{gid}/revoke", data={"csrf_token": csrf}).status_code == 303
