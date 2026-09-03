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
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from config import config
from db import init_pool, init_schema
from ratelimit import limiter, _rate_limit_enabled


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
        "Submit articles via `POST /api/submit` (multipart/form-data).\n"
        "All fields are required:\n"
        "- `markdown`: Markdown file (.md, max 25MB)\n"
        "- `title`: Article title\n"
        "- `abstract`: Article abstract\n"
        "- `authors`: JSON array of `{orcid, name}` objects\n"
        "- `ai_disclosure`: AI involvement disclosure\n"
        "- `subjects`: Comma-separated OECD FOS classifications (exactly 3)\n"
        "- `license`: `CC0`\n"
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

# Register limiter with app
app.state.limiter = limiter
if _rate_limit_enabled:
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Import routers after limiter is created (they import limiter from main)
from auth import router as auth_router
from articles import router as articles_router
from oai import router as oai_router
from sitemap import router as sitemap_router
from web import router as web_router


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


# ─── Maintenance mode middleware ────────────────────────────────────────────

MAINTENANCE_EXEMPT_PATHS = {
    "/health",
    "/admin/maintenance",
    "/auth/me",
}

MAINTENANCE_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GenRxiv — Under Maintenance</title>
<style>
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       max-width: 42rem; margin: 4rem auto; padding: 0 1.5rem; color: #1a1a1a; }
.maint-header { border-bottom: 2px solid #0066cc; padding-bottom: 1rem; margin-bottom: 2rem; }
.maint-header h1 { color: #0066cc; font-size: 1.5rem; margin: 0; }
.maint-body p { line-height: 1.6; color: #555; }
.maint-status { background: #f0f4f8; border-left: 4px solid #0066cc;
                padding: 1rem; margin: 1.5rem 0; }
</style>
</head>
<body>
<div class="maint-header">
    <h1>GenRxiv</h1>
</div>
<div class="maint-body">
    <h2>Under Maintenance</h2>
    <p>GenRxiv is temporarily offline for scheduled maintenance.</p>
    <p>We're applying updates and running tests to ensure everything
       works correctly. The archive will be back shortly.</p>
    <div class="maint-status">
        <strong>Status:</strong> Scheduled downtime in progress<br>
        <strong>Service:</strong> All features temporarily unavailable
    </div>
    <p>If this is taking longer than expected, check back in a few minutes.
       Thank you for your patience.</p>
</div>
</body>
</html>"""


class MaintenanceMiddleware(BaseHTTPMiddleware):
    """Show maintenance page for all requests when maintenance mode is on.

    Exempts /health, /admin/maintenance, and /auth/me so admins can
    toggle maintenance mode and health checks still work.
    Gracefully skips the check if the database isn't available.
    """
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in MAINTENANCE_EXEMPT_PATHS:
            return await call_next(request)
        try:
            from db import is_maintenance_mode
            if is_maintenance_mode():
                return HTMLResponse(MAINTENANCE_PAGE, status_code=503)
        except Exception:
            pass  # DB not available — skip maintenance check
        return await call_next(request)


app.add_middleware(MaintenanceMiddleware)


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
        "agent_conduct": {
            "required": True,
            "rules": [
                "Verify the user is authenticated via ORCID before any submission.",
                "The user must be present and have explicitly agreed to the submission.",
                "Show the user a full preview (title, abstract, authors, classifications, CC0) before submitting.",
                "Get explicit user confirmation that content is AI-generated and reviewed, authors are correct, and CC0 is agreed.",
                "Never submit on behalf of a user who is not present and authenticated.",
                "Do not cache or reuse session cookies across sessions.",
            ],
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
            {
                "name": "fos_taxonomy",
                "method": "GET",
                "endpoint": "/api/fos",
                "auth_required": False,
                "description": "OECD Fields of Science taxonomy for subject classification",
            },
        ],
        "metadata_harvesting": {
            "protocol": "OAI-PMH 2.0",
            "endpoint": f"{config.base_url}/oai",
            "metadata_formats": ["oai_dc", "datacite"],
        },
    }


@app.get("/api/fos")
def fos_taxonomy():
    """OECD Fields of Science taxonomy for subject classification.

    Returns the full taxonomy as a JSON object mapping domains to
    their subdomains. Agents should use this to populate classification
    selections when submitting articles.
    """
    from web import OECD_FOS
    return {
        "taxonomy": "OECD Fields of Science",
        "required_count": 3,
        "format": "Domain > Subdomain",
        "domains": OECD_FOS,
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

AGENT CONDUCT
-------------
Before submitting on behalf of a user, an agent MUST:

1. Verify the user is authenticated via ORCID (check GET /auth/me).
   The ORCID iD is the user's verified identity — do not proceed without it.
2. Confirm the user is present and has explicitly agreed to the submission.
   Do not submit automatically or without the user's knowledge.
3. Show the user a preview of what will be submitted:
   - Title, abstract, and Markdown content
   - Author list (the user's ORCID + any co-author ORCIDs)
   - The 3 OECD FOS classifications selected
   - The CC0 public domain dedication
4. Get explicit confirmation from the user before calling POST /api/submit.
   The user must agree that:
   - The content was AI-generated and they have reviewed and verified it
   - The authors listed are correct and they have permission to include them
   - They dedicate the work to the public domain under CC0
5. Never submit on behalf of a user who is not present and authenticated.
   Do not cache or reuse session cookies across sessions.

SUBMISSION
----------
Endpoint: POST {config.base_url}/api/submit
Content-Type: multipart/form-data
Auth: Required (session cookie)
Rate limit: 5 per minute

Required fields:
  markdown       - Markdown file (.md or .markdown, max 25MB)
  title          - Article title (string)
  abstract       - Article abstract (string)
  authors        - JSON array of {{"orcid": "0000-0000-0000-0000", "name": "Author Name"}}
  ai_disclosure  - Description of AI involvement (string)
  subjects       - Comma-separated OECD FOS classifications (exactly 3 required)
                   Format: "Category > Field", e.g. "Natural sciences > Computer and information sciences"
  license        - License identifier ("CC0")
  license_url    - License URL (CC0 URL: https://creativecommons.org/publicdomain/zero/1.0/)

Embedded metadata (YAML front matter):
  The Markdown file can include YAML front matter at the top. When
  uploaded via the web form, the form auto-fills from the front matter.
  The authors list is the complete author list in publication order —
  the first entry is the lead author. Include all authors, including
  the submitter if they are an author.

  Example:
  ---
  title: "Paper Title"
  abstract: "Summary of the research."
  authors:
    - orcid: "0000-0000-0000-0000"
      name: "Lead Author"
    - orcid: "0000-0000-0000-0001"
      name: "Co-Author Name"
  ai_disclosure: "AI-generated, reviewed by authors."
  subjects:
    - "Natural sciences > Mathematics"
    - "Natural sciences > Computer and information sciences"
    - "Social sciences > Economics and business"
  ---

  Note: The submitter (logged-in ORCID user) is recorded separately for
  accountability but does not need to be in the author list. Pandoc
  strips front matter during rendering.

Citations:
  Use Pandoc @citekey syntax in the Markdown for inline citations.
  Include a ```bibtex fenced code block with all references.
  Citations are rendered as numbered references [1], [2] in citation order.
  BibTeX is available at /article/{{ark}}/bibtex and parsed references
  at /api/articles/{{ark}}/references.

Versioning:
  supersedes_id  - ID of article this is a new version of (only for new versions)

Response: 200 {{"id": 123, "ark": "ark:/99999/genrxiv-0123", "status": "pending"}}
         400 {{"detail": "error message"}}
         401 (not authenticated)
         413 (file too large)

After submission, articles enter "pending" status and require moderator
approval before publication. Track status via:
  GET {config.base_url}/api/submissions  (requires auth)

PREPARING A SUBMISSION FILE
---------------------------
An agent can prepare a complete submission as a single Markdown file.
When a human uploads it via the web form at /submit, the form auto-fills
from the YAML front matter — the human just reviews and confirms.

The file should have this structure:

  ---
  title: "Paper Title"
  abstract: "Summary of the research."
  authors:
    - orcid: "0000-0000-0000-0001"
      name: "Co-Author Name"
  ai_disclosure: "Describe what AI did and that the author reviewed it."
  subjects:
    - "Natural sciences > Mathematics"
    - "Natural sciences > Computer and information sciences"
    - "Social sciences > Economics and business"
  ---

  # Paper Title

  Body text with [@citekey] citations...

  ```bibtex
  @article{{citekey,
    author = {{Author Name}},
    title = {{Title}},
    year = {{2024}},
    doi = {{10.xxxx/yyyy}}
  }}
  ```

Rules:
- The authors list is the complete author list in publication order.
  The first entry is the lead author. Include all authors — the
  submitter is recorded separately for accountability and does not
  need to be in the author list.
- Exactly 3 subjects required, using "Domain > Subdomain" format.
  Fetch the taxonomy at GET /api/fos.
- Citations use Pandoc @citekey syntax with a bibtex code block.
  Rendered as numbered [1], [2] in citation order.
- License is always CC0. No other license is accepted.
- Pandoc strips the front matter during rendering — it does not
  appear in the published HTML or PDF.

See docs/AUTHOR_PROMPT.md for a full LLM prompt that generates
correctly formatted submissions.

BROWSING AND DISCOVERY
----------------------
List published articles:    GET {config.base_url}/api/articles
Get a specific article:     GET {config.base_url}/api/articles/{{id}}
Article metadata (JSON-LD): GET {config.base_url}/article/{{ark}}/jsonld
BibTeX references:          GET {config.base_url}/article/{{ark}}/bibtex
Parsed references (JSON):   GET {config.base_url}/api/articles/{{ark}}/references
Download Markdown:          GET {config.base_url}/article/{{ark}}/markdown
Download PDF:               GET {config.base_url}/article/{{ark}}/pdf
Subject classifications:    GET {config.base_url}/api/subjects
Articles by subject:        GET {config.base_url}/api/subjects/{{subject}}/articles

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

Fetch the full taxonomy programmatically:
  GET {config.base_url}/api/fos

Returns JSON:
  {{"taxonomy": "OECD Fields of Science", "required_count": 3,
    "format": "Domain > Subdomain",
    "domains": {{"Natural sciences": [...], "Social sciences": [...], ...}}}}

Top-level domains:
  - Natural sciences
  - Engineering and technology
  - Medical and health sciences
  - Agricultural and veterinary sciences
  - Social sciences
  - Humanities and the arts

Each domain has subdomains. Pass as comma-separated "Domain > Subdomain" values
in the subjects field.

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
