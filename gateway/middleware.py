"""Cross-cutting HTTP hardening."""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_BODY_BYTES = 1_000_000  # 1 MB is plenty for 500 product rows

CSP = (
    "default-src 'none'; style-src 'self'; img-src 'self' data:; form-action 'self' https: http://localhost:* "
    "http://127.0.0.1:* cursor:; frame-ancestors 'none'; base-uri 'none'"
)


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request.state.request_id = str(uuid.uuid4())

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


class _BodyTooLarge(Exception):
    pass


def _is_too_large(exc: BaseException) -> bool:
    if isinstance(exc, _BodyTooLarge):
        return True
    return any(_is_too_large(e) for e in getattr(exc, "exceptions", ()))


class BodySizeLimitMiddleware:
    """Caps request bodies at MAX_BODY_BYTES, whether or not the client sends a
    Content-Length (tunnels and HTTP/2 proxies often forward chunked bodies)."""

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        length = dict(scope["headers"]).get(b"content-length")
        if length is not None and (not length.isdigit() or int(length) > self.max_bytes):
            await JSONResponse({"detail": "Request body too large"}, status_code=413)(scope, receive, send)
            return

        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _BodyTooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except Exception as exc:  # may arrive wrapped in an ExceptionGroup by inner middleware
            if not _is_too_large(exc):
                raise
            if not started:
                await JSONResponse({"detail": "Request body too large"}, status_code=413)(scope, receive, send)
