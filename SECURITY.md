# Security Policy

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

The GenRxiv conversion service runs untrusted author-submitted Markdown
(through Pandoc and Tectonic), so sandbox escapes and remote code
execution are the sharpest class of bug here. We need to hear about
those privately before they're public.

Please report vulnerabilities to **security@genrxiv.org** with:

- A description of the issue and its impact
- Steps to reproduce, including any crafted input
- The version or commit hash you tested against

You should receive a response within 72 hours. If you don't, follow up —
the message may have been filtered.

## Scope

**In scope:**

- The FastAPI application (`api/`) — authentication bypass, SQL
  injection, path traversal, input validation bypass, session
  fixation, authorization issues
- The conversion service (`convert-service/`) — sandbox escapes, file
  system access outside the job directory, network access during
  compilation, resource exhaustion attacks
- The nginx routing layer (`deploy/nginx.conf`) — request smuggling,
  path traversal, header injection, rate limit bypass
- The signup API — injection, data exfiltration, abuse vectors

**Out of scope:**

- Vulnerabilities in third-party dependencies (FastAPI, Starlette,
  psycopg, Tectonic, Pandoc, PostgreSQL, nginx) — report to the
  upstream project
- Issues that require already having administrative access
- Spam or content abuse on the archive itself — that's moderation, not
  security

## Disclosure

We follow coordinated disclosure:

1. You report the issue privately.
2. We acknowledge and triage within 72 hours.
3. We work on a fix and agree on a disclosure timeline with you.
4. Once a fix is released, we publish a security advisory and credit
   you (unless you prefer to remain anonymous).

## Security Measures in Place

### Application layer (FastAPI)

- **Parameterized SQL:** All database queries use psycopg3's
  parameterized queries. No string interpolation in SQL.
- **Input validation:** ORCID iD format validation (regex), title
  length limits (500 chars), abstract (5000),
  subject classification count (exactly 3 OECD FOS required) and
  length (100) limits, author count (50), license whitelist (CC0
  only), file extension whitelist (.md, .markdown), file size limit
  (25 MB).
- **Path traversal protection:** All file-serving endpoints use
  `safe_resolve_file()` which resolves the path and verifies it stays
  under the files directory.
- **Rate limiting:** Submission endpoint limited to 5 per minute per
  IP. ORCID callback limited to 10 per minute. Global default of 200
  per minute. Nginx-level rate limiting at 30 req/s with burst of 50.
- **Security headers:** X-Content-Type-Options: nosniff, X-Frame-Options:
  DENY, X-XSS-Protection, Referrer-Policy, Permissions-Policy, HSTS
  (over HTTPS). Applied at both nginx and FastAPI middleware levels.
- **Session security:** Cookies are HttpOnly, SameSite=Lax, Secure
  (over HTTPS). Session tokens are 32-byte URL-safe random values.
  Sessions expire after 7 days. ORCID OAuth state validation prevents
  CSRF.
- **No password storage:** ORCID is the only authentication mechanism.
  No passwords are stored or processed.
- **API docs not at default path:** Swagger UI at `/api/docs` (not
  `/docs`), OpenAPI schema at `/api/openapi.json` (not
  `/openapi.json`).
- **Maintenance mode:** Database-flag-controlled maintenance mode
  can take the site offline for scheduled downtime. Admin endpoints
  (/admin/maintenance, /health, /auth/me) remain accessible for
  recovery.
- **Rate limiting toggle:** Rate limiting can be disabled via the
  `RATE_LIMIT_ENABLED=false` environment variable (used in tests).
- **Upload size limit:** Nginx `client_max_body_size 26m` matches API
  validation (25 MB + overhead).

### Conversion service

- **Sandboxed compilation:** Tectonic is invoked with `--untrusted`,
  which disables shell-escape and restricts file access to the job
  directory. Each job runs in its own temporary directory that is
  deleted after compilation.
- **Hard timeouts:** Compilation is capped at 60 seconds wall-clock
  time. Jobs that exceed the limit are killed.
- **Upload size limits:** 25 MB maximum for Markdown files.
- **No published ports:** The conversion service is only reachable
  through the FastAPI application, not directly from the network.
- **Resource limits:** Container limited to 1 CPU and 1 GB RAM.

### Infrastructure

- **Container resource limits:** API (2 CPU, 1 GB), conversion service
  (1 CPU, 1 GB), nginx (0.5 CPU, 128 MB).
- **PostgreSQL healthcheck:** Database must be healthy before the API
  starts, preventing connection failures during startup.
- **Secrets via environment variables:** No credentials are stored in
  the repository. All secrets flow through `.env` (gitignored) and are
  injected as environment variables at container startup.
- **Pre-commit secret scanning:** Both a lightweight grep-based hook
  and gitleaks are available to prevent credentials from entering git
  history.
- **nginx version hidden:** `server_tokens off` prevents version
  disclosure.
