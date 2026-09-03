"""
GenRxiv API — main FastAPI application.

Mounts all routers: auth, articles, OAI-PMH, sitemap, web UI.
Initializes database schema on startup.
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
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
    init_pool()
    init_schema()
    os.makedirs(config.files_dir, exist_ok=True)
    yield


app = FastAPI(
    title="GenRxiv API",
    description=(
        "An open archive for AI-generated research.\n\n"
        "## Authentication\n\n"
        "GenRxiv uses ORCID OAuth for all authentication. There is no "
        "API token or key — agents must complete the ORCID OAuth flow to "
        "obtain a session cookie.\n\n"
        "1. Redirect the user to `GET /auth/orcid?redirect=<callback_url>`\n"
        "2. After ORCID authorization, the user is redirected back with a "
        "`genrxiv_session` cookie set.\n"
        "3. Include this cookie in all subsequent requests.\n"
        "4. Check `GET /auth/me` to verify the session is valid.\n\n"
        "## Submission\n\n"
        "Submit articles via `POST /api/submit` (multipart/form-data):\n"
        "- `markdown`: Markdown file (.md, max 25MB)\n"
        "- `title`: Article title\n"
        "- `abstract`: Required abstract\n"
        "- `authors`: JSON array of `{orcid, name}` objects\n"
        "- `ai_disclosure`: AI involvement disclosure\n"
        "- `keywords`: Comma-separated OECD FOS classifications\n"
        "- `license`: `CC0` (default)\n"
        "- `license_url`: CC0 URL\n\n"
        "Submissions enter `pending` status and require moderator approval "
        "before publication.\n\n"
        "## Discovery\n\n"
        "- OpenAPI schema: `/api/openapi.json`\n"
        "- Agent guide: `/api/agent-guide`\n"
        "- OAI-PMH: `/oai?verb=Identify`\n"
        "- Sitemap: `/sitemap.xml`\n"
        "- Atom feed: `/feed.xml`"
    ),
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


# ─── Agent discovery ────────────────────────────────────────────────────────

@app.get("/.well-known/ai-plugin.json")
def ai_plugin_manifest():
    """Machine-readable manifest for agent/API discovery.

    Follows the AI Plugin / well-known convention so agents can
    discover the API capabilities, auth method, and key endpoints.
    """
    return {
        "schema_version": "1.0",
        "name": "GenRxiv",
        "description": "An open archive for AI-generated research.",
        "url": config.base_url,
        "api": {
            "openapi_url": f"{config.base_url}/api/openapi.json",
            "docs_url": f"{config.base_url}/api/docs",
            "agent_guide_url": f"{config.base_url}/api/agent-guide",
        },
        "auth": {
            "type": "oauth",
            "provider": "ORCID",
            "login_url": f"{config.base_url}/auth/orcid",
            "session_cookie": "genrxiv_session",
            "verify_url": f"{config.base_url}/auth/me",
            "flow": (
                "Redirect user to /auth/orcid?redirect=<callback_url>. "
                "After ORCID authorization, a genrxiv_session cookie is set. "
                "Include this cookie in subsequent requests."
            ),
        },
        "capabilities": [
            {
                "name": "submit_article",
                "method": "POST",
                "endpoint": "/api/submit",
                "content_type": "multipart/form-data",
                "auth_required": True,
                "rate_limit": "5 per minute",
            },
            {
                "name": "list_articles",
                "method": "GET",
                "endpoint": "/api/articles",
                "auth_required": False,
            },
            {
                "name": "get_article",
                "method": "GET",
                "endpoint": "/api/articles/{article_id}",
                "auth_required": False,
            },
            {
                "name": "oai_pmh",
                "method": "GET",
                "endpoint": "/oai",
                "auth_required": False,
                "description": "OAI-PMH metadata harvesting endpoint",
            },
            {
                "name": "atom_feed",
                "method": "GET",
                "endpoint": "/feed.xml",
                "auth_required": False,
            },
            {
                "name": "sitemap",
                "method": "GET",
                "endpoint": "/sitemap.xml",
                "auth_required": False,
            },
        ],
        "metadata_harvesting": {
            "protocol": "OAI-PMH 2.0",
            "endpoint": f"{config.base_url}/oai",
            "metadata_formats": ["oai_dc", "datacite"],
        },
    }


@app.get("/api/agent-guide")
def agent_guide():
    """Plain-text guide for agents on how to interact with GenRxiv.

    Written to be consumed by LLM-based agents and automated tools.
    """
    guide = f"""GenRxiv Agent Guide
==================

GenRxiv is an open archive for AI-generated research. This guide describes
how to programmatically interact with the site.

BASE URL: {config.base_url}

AUTHENTICATION
--------------
GenRxiv uses ORCID OAuth exclusively. There is no API key or token.

Steps:
1. Redirect the user to: GET {config.base_url}/auth/orcid?redirect=<callback_url>
2. The user authorizes via ORCID and is redirected back to <callback_url>.
3. A session cookie named "genrxiv_session" is set (HttpOnly, Secure).
4. Include this cookie in all subsequent requests.
5. Verify the session with: GET {config.base_url}/auth/me
   Returns: {{"authenticated": true, "orcid": "...", "name": "...", "is_admin": false}}

SUBMISSION
----------
Endpoint: POST {config.base_url}/api/submit
Content-Type: multipart/form-data
Auth: Required (session cookie)
Rate limit: 5 per minute

Required fields:
  markdown       - Markdown file (.md or .markdown, max 25MB)
  title          - Article title (string)
  abstract       - Article abstract (string, required)
  authors        - JSON array of {{"orcid": "0000-0000-0000-0000", "name": "Author Name"}}
  ai_disclosure  - Description of AI involvement (string)

Optional fields:
  keywords       - Comma-separated OECD FOS classifications
                   Format: "Category > Field", e.g. "Natural sciences > Computer and information sciences"
                   Select 3 from the OECD Fields of Science taxonomy.
  license        - License identifier (default: "CC0")
  license_url    - License URL (default: CC0 URL)
  supersedes_id  - ID of article this is a new version of (for versioning)

Response: 200 {{"id": 123, "ark": "ark:/99999/genrxiv-0123", "status": "pending"}}
         400 {{"detail": "error message"}}
         401 (not authenticated)
         413 (file too large)

After submission, articles enter "pending" status and require moderator
approval before publication. Track status via:
  GET {config.base_url}/api/submissions  (requires auth)

BROWSING AND DISCOVERY
----------------------
List published articles:    GET {config.base_url}/api/articles
Get a specific article:     GET {config.base_url}/api/articles/{{id}}
Article metadata (JSON-LD): GET {config.base_url}/article/{{ark}}/jsonld
Download Markdown:          GET {config.base_url}/article/{{ark}}/markdown
Download PDF:               GET {config.base_url}/article/{{ark}}/pdf

METADATA HARVESTING
-------------------
OAI-PMH 2.0 endpoint:  GET {config.base_url}/oai?verb=Identify
                       GET {config.base_url}/oai?verb=ListRecords&metadataPrefix=oai_dc
                       GET {config.base_url}/oai?verb=ListRecords&metadataPrefix=datacite

Atom feed:              GET {config.base_url}/feed.xml
Sitemap:                GET {config.base_url}/sitemap.xml
OpenAPI schema:         GET {config.base_url}/api/openapi.json
Interactive docs:       GET {config.base_url}/api/docs

OECD FOS CLASSIFICATION TAXONOMY
--------------------------------
Authors must select 3 classifications from the OECD Fields of Science taxonomy.
Top-level domains:
  - Natural sciences
  - Engineering and technology
  - Medical and health sciences
  - Agricultural and veterinary sciences
  - Social sciences
  - Humanities and the arts

Each domain has subdomains. Pass as comma-separated "Domain > Subdomain" values
in the keywords field.

LICENSE
-------
All submissions default to CC0 (Public Domain Dedication).
Authors must agree to the CC0 dedication when submitting.

SUPPORT
-------
Repository: https://github.com/GenRxiv/genrxiv
"""
    return PlainTextResponse(guide)


@app.get("/", response_class=HTMLResponse)
def index():
    """Simple landing redirect — the real splash page is served by nginx."""
    return HTMLResponse(
        f'<html><head><meta http-equiv="refresh" content="0;url={config.base_url}/"></head></html>'
    )
