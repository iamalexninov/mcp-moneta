"""Cross-cutting HTTP hardening."""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

MAX_BODY_BYTES = 1_000_000  # 1 MB is plenty for 500 product rows

CSP = (
    "default-src 'none'; style-src 'self'; img-src 'self' data:; form-action 'self' https: http://localhost:* "
    "http://127.0.0.1:* cursor:; frame-ancestors 'none'; base-uri 'none'"
)


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request.state.request_id = str(uuid.uuid4())
        length = request.headers.get("content-length")
        if length and (not length.isdigit() or int(length) > MAX_BODY_BYTES):
            return JSONResponse({"detail": "Request body too large"}, status_code=413)

        response = await call_next(request)
        h = response.headers
        h["X-Request-ID"] = request.state.request_id
        h["X-Content-Type-Options"] = "nosniff"
        h["X-Frame-Options"] = "DENY"
        h["Referrer-Policy"] = "no-referrer"
        h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        h["Cross-Origin-Opener-Policy"] = "same-origin"
        h["Content-Security-Policy"] = CSP
        if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
            h["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        if request.url.path.startswith(("/admin", "/oauth", "/api")):
            h.setdefault("Cache-Control", "no-store")
        return response
