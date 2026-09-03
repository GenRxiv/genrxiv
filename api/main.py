"""
GenRxiv API — main FastAPI application.

Mounts all routers: auth, articles, OAI-PMH, sitemap, web UI.
Initializes database schema on startup.
"""
import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from config import config
from db import init_pool, init_schema
from auth import router as auth_router
from articles import router as articles_router
from oai import router as oai_router
from sitemap import router as sitemap_router
from web import router as web_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB pool and schema on startup."""
    logger = logging.getLogger("genrxiv")
    init_pool()
    init_schema()
    logger.info("Database schema initialized")
    os.makedirs(config.files_dir, exist_ok=True)
    yield


app = FastAPI(
    title="GenRxiv API",
    description="An open archive for AI-generated research.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

# ─── Rate limiting ─────────────────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address, default_limits=["200 per minute"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ─── Security headers middleware ───────────────────────────────────────────

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        # HSTS only makes sense over HTTPS; Cloudflare handles TLS termination
        if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


app.add_middleware(SecurityHeadersMiddleware)


# Mount routers
app.include_router(auth_router)
app.include_router(articles_router)
app.include_router(oai_router)
app.include_router(sitemap_router)
app.include_router(web_router)

# Static files (CSS, JS for web pages)
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/health")
def health():
    return {"status": "ok", "service": "genrxiv-api"}


@app.get("/", response_class=HTMLResponse)
def index():
    """Simple landing redirect — the real splash page is served by nginx."""
    return HTMLResponse(
        f'<html><head><meta http-equiv="refresh" content="0;url={config.base_url}/"></head></html>'
    )
