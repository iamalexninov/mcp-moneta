"""Moneta AI Gateway: REST API + OAuth 2.1 server + admin panel.

Run:  uvicorn gateway.main:app --port 8000
"""

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .admin.routes import router as admin_router
from .api.routes import router as api_router
from .config import get_settings
from .db import init_db
from .middleware import SecurityMiddleware
from .oauth.routes import router as oauth_router
from .security.keys import load_keys

log = logging.getLogger("gateway")


def create_app() -> FastAPI:
    s = get_settings()
    s.check_production_safety()
    if s.auto_create_tables:
        init_db()
    load_keys()

    app = FastAPI(
        title="Moneta AI Gateway",
        version="0.1.0",
        description="Secure REST API between AI assistants (via MCP) and Moneta ERP.",
        # Interactive docs only in dev: do not advertise the attack surface in prod.
        docs_url="/docs" if s.is_dev else None,
        redoc_url=None,
        openapi_url="/openapi.json" if s.is_dev else None,
    )
    app.add_middleware(SecurityMiddleware)
    # No CORS middleware on purpose: no browser origin needs to call this API
    # directly (AI clients call from their servers; the admin panel is same-origin).

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        # Return field paths + messages, never echo the submitted input back.
        errors = [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]
        return JSONResponse({"detail": errors}, status_code=422)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        rid = getattr(request.state, "request_id", "-")
        log.exception("Unhandled error request_id=%s", rid)
        return JSONResponse({"detail": "Internal error", "request_id": rid}, status_code=500)

    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "admin" / "static")), name="static")
    app.include_router(oauth_router)
    app.include_router(api_router)
    app.include_router(admin_router)

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/admin")

    @app.get("/healthz", include_in_schema=False)
    def health():
        return {"status": "ok"}

    return app


app = create_app()
