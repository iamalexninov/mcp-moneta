"""Calls the gateway REST API on behalf of the signed-in user.

No token passthrough (forbidden by the MCP spec): the user's token has
audience = MCP server and is useless against the API. We exchange it
(RFC 8693) for a 5-minute API token, authenticating as the MCP server's
confidential client. The gateway re-checks the user, their role and the
connection on every exchange and every API call.
"""

import hashlib
import time

import httpx
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.mcpserver.exceptions import ToolError

from .config import get_settings

TOKEN_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"
ACCESS_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"


class GatewayClient:
    def __init__(self) -> None:
        self._cache: dict[str, tuple[str, float]] = {}  # sha256(user token) -> (api token, expiry)

    def _http(self) -> httpx.AsyncClient:
        s = get_settings()
        return httpx.AsyncClient(base_url=s.gateway_internal_url.rstrip("/"), timeout=s.http_timeout,
                                 follow_redirects=False)

    async def _api_token(self) -> str:
        user_token = get_access_token()
        if user_token is None:
            raise ToolError("Not authenticated")
        key = hashlib.sha256(user_token.token.encode()).hexdigest()
        cached = self._cache.get(key)
        if cached and cached[1] - 30 > time.time():
            return cached[0]

        s = get_settings()
        async with self._http() as http:
            resp = await http.post(
                "/oauth/token",
                data={"grant_type": TOKEN_EXCHANGE, "subject_token": user_token.token,
                      "subject_token_type": ACCESS_TOKEN_TYPE, "audience": s.api_audience},
                auth=(s.client_id, s.client_secret),
            )
        if resp.status_code != 200:
            raise ToolError("Your Moneta connection is no longer authorized. Reconnect the connector.")
        body = resp.json()
        # prune expired entries, then cache
        now = time.time()
        self._cache = {k: v for k, v in self._cache.items() if v[1] > now}
        self._cache[key] = (body["access_token"], now + int(body.get("expires_in", 60)))
        return body["access_token"]

    async def request(self, method: str, path: str, **kwargs) -> dict | list:
        token = await self._api_token()
        async with self._http() as http:
            resp = await http.request(method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs)
        if resp.status_code in (200, 201):
            return resp.json()
        detail = _detail(resp)
        if resp.status_code == 401:
            raise ToolError("Authorization expired or revoked. Reconnect the Moneta connector.")
        if resp.status_code == 403:
            raise ToolError(f"Permission denied: {detail}. Ask your Moneta administrator for access.")
        if resp.status_code == 429:
            raise ToolError("Rate limit reached. Wait a minute and try again.")
        if resp.status_code >= 500:
            raise ToolError("Moneta gateway error. Try again later.")
        raise ToolError(f"Request rejected ({resp.status_code}): {detail}")


def _detail(resp: httpx.Response) -> str:
    try:
        d = resp.json().get("detail")
    except ValueError:
        return resp.reason_phrase
    if isinstance(d, list):  # pydantic validation errors
        return "; ".join(f"{'.'.join(str(x) for x in e.get('loc', [])[1:])}: {e.get('msg')}" for e in d)[:500]
    return str(d)[:500]


gateway = GatewayClient()
