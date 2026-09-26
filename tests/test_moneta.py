"""GET methods over real Moneta tables. The data tests need a Test_Ninov-like database:
TEST_MONETA_ODBC="Driver={ODBC Driver 18 for SQL Server};Server=...;Database=Test_Ninov;..." pytest tests/test_moneta.py
"""

import os

import pytest

from .conftest import api_token, login_tokens

needs_db = pytest.mark.skipif(not os.environ.get("TEST_MONETA_ODBC"), reason="TEST_MONETA_ODBC not set")


def _headers(client, mcp_secret, email="admin@a.bg", scopes=None):
    _, tok = login_tokens(client, email=email, scopes=scopes)
    r = api_token(client, mcp_secret, tok["access_token"])
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.mark.skipif(bool(os.environ.get("TEST_MONETA_ODBC")), reason="only meaningful without a Moneta database")
def test_not_configured_is_503(client, mcp_secret):
    r = client.get("/api/v1/moneta/contragents", headers=_headers(client, mcp_secret))
    assert r.status_code == 503 and "GATEWAY_ERP_ODBC" in r.json()["detail"]


def test_requires_token(client):
    assert client.get("/api/v1/moneta/invoices").status_code == 401


def test_scope_enforced(client, mcp_secret):
    h = _headers(client, mcp_secret, scopes=["reports:read"])
    assert client.get("/api/v1/moneta/contragents", headers=h).status_code == 403


def test_limit_capped(client, mcp_secret):
    h = _headers(client, mcp_secret)
    assert client.get("/api/v1/moneta/items", params={"limit": 500}, headers=h).status_code == 422


@needs_db
def test_contragents_paged_and_search(client, mcp_secret):
    h = _headers(client, mcp_secret)
    r = client.get("/api/v1/moneta/contragents", params={"limit": 5}, headers=h).json()
    assert r["total"] >= 5 and len(r["rows"]) == 5 and "Id" in r["rows"][0]
    r = client.get("/api/v1/moneta/contragents", params={"search": "Фирма 1"}, headers=h).json()
    assert r["total"] >= 1 and all("Фирма 1" in row["Name"] for row in r["rows"])
    one = client.get(f"/api/v1/moneta/contragents/{r['rows'][0]['Id']}", headers=h)
    assert one.status_code == 200 and one.json()["Id"] == r["rows"][0]["Id"]
    assert all("Photo" not in row for row in r["rows"])            # binary columns are left out


@needs_db
def test_search_is_literal(client, mcp_secret):
    h = _headers(client, mcp_secret)
    rows = client.get("/api/v1/moneta/items", params={"search": "100%"}, headers=h).json()["rows"]
    assert rows and all("100%" in row["Name"] for row in rows)
    assert client.get("/api/v1/moneta/items", params={"search": "%"}, headers=h).json()["total"] < 50


@needs_db
def test_invoices_filters_and_lines(client, mcp_secret):
    h = _headers(client, mcp_secret)
    all_ = client.get("/api/v1/moneta/invoices", params={"limit": 200}, headers=h).json()
    dates = [row["DocumentDate"] for row in all_["rows"]]
    assert dates == sorted(dates, reverse=True)                    # newest first
    some = client.get("/api/v1/moneta/invoices", params={"date_from": dates[9][:10], "date_to": dates[0][:10]},
                      headers=h).json()
    assert 1 <= some["total"] <= all_["total"]
    c = all_["rows"][0]["Contragent_Id"]
    by_c = client.get("/api/v1/moneta/invoices", params={"contragent_id": c}, headers=h).json()
    assert by_c["total"] >= 1 and all(row["Contragent_Id"] == c for row in by_c["rows"])
    inv = client.get(f"/api/v1/moneta/invoices/{all_['rows'][0]['Id']}", headers=h).json()
    assert inv["invoice"]["Id"] == all_["rows"][0]["Id"]
    assert inv["line_count"] == len(inv["lines"]) and all(l["master_id"] == inv["invoice"]["Id"] for l in inv["lines"])
    assert client.get("/api/v1/moneta/invoices/does-not-exist", headers=h).status_code == 404
