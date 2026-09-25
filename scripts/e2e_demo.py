"""End-to-end demo: behaves exactly like Claude.ai connecting to the MCP server.

1. Discovers the auth server from the MCP server's 401 + protected-resource metadata
2. Registers a client dynamically (RFC 7591)
3. Signs in on the consent page with PKCE (what the user does in the browser)
4. Exchanges the code for tokens
5. Calls MCP tools over Streamable HTTP with the bearer token

Usage (both servers running):
  python scripts/e2e_demo.py --email admin@demo.bg --password '...'
"""

import argparse
import asyncio
import base64
import hashlib
import json
import re
import secrets
from urllib.parse import parse_qs, urlparse

import httpx
import httpx2
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

REDIRECT = "https://claude.ai/api/mcp/auth_callback"


def oauth_login(mcp_url: str, email: str, password: str, totp: str | None) -> str:
    with httpx.Client(timeout=15) as http:
        r = http.post(mcp_url, json={})
        assert r.status_code == 401, r.status_code
        meta_url = re.search(r'resource_metadata="([^"]+)"', r.headers["www-authenticate"]).group(1)
        prm = http.get(meta_url).json()
        issuer = prm["authorization_servers"][0]
        asm = http.get(f"{issuer}/.well-known/oauth-authorization-server").json()
        print("1. discovered authorization server:", issuer)

        reg = http.post(asm["registration_endpoint"], json={
            "client_name": "E2E demo (acts like Claude)", "redirect_uris": [REDIRECT],
            "token_endpoint_auth_method": "none"}).json()
        client_id = reg["client_id"]
        print("2. registered client:", client_id)

        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        params = {"response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT, "state": "xyz",
                  "scope": " ".join(prm.get("scopes_supported", [])), "code_challenge": challenge,
                  "code_challenge_method": "S256", "resource": prm["resource"]}
        page = http.get(asm["authorization_endpoint"], params=params)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        scopes = re.findall(r'name="scopes" value="([^"]+)"', page.text)
        form = {**params, "csrf_token": csrf, "email": email, "password": password, "totp": totp or "",
                "action": "approve", "scopes": scopes}
        r = http.post(asm["authorization_endpoint"], data=form)
        assert r.status_code == 302, r.text[:500]
        q = parse_qs(urlparse(r.headers["location"]).query)
        assert q["state"] == ["xyz"]
        print("3. user approved scopes:", scopes)

        tok = http.post(asm["token_endpoint"], data={
            "grant_type": "authorization_code", "code": q["code"][0], "redirect_uri": REDIRECT,
            "client_id": client_id, "code_verifier": verifier}).json()
        print("4. got access token (expires in", tok["expires_in"], "s) scopes:", tok["scope"])
        return tok["access_token"]


async def call_tools(mcp_url: str, token: str) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx2.AsyncClient(headers=headers, timeout=30) as http:
        async with streamable_http_client(mcp_url, http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                tools = await session.list_tools()
                print("5. tools:", [t.name for t in tools.tools])
                for name, args in [
                    ("sales_report", {"date_from": "2026-01-01", "date_to": "2026-12-31", "group_by": "category"}),
                    ("search_customers", {"query": "Sofia"}),
                    ("import_products", {"items": [{"sku": "DEMO-001", "name": "Demo product", "unit_price": 9.99}]}),
                    ("create_order", {"customer_code": "C0001", "lines": [{"sku": "OFF-001", "quantity": 2}]}),
                ]:
                    res = await session.call_tool(name, args)
                    text = res.content[0].text if res.content else ""
                    compact = " ".join(text.split())[:160]
                    print(f"   {name} -> error={res.is_error}: {compact}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mcp-url", default="http://localhost:8001/mcp")
    p.add_argument("--email", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--totp")
    a = p.parse_args()
    token = oauth_login(a.mcp_url, a.email, a.password, a.totp)
    asyncio.run(call_tools(a.mcp_url, token))


if __name__ == "__main__":
    main()
