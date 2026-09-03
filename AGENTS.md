# AGENTS.md

Project guide for AI agents (Devin, Claude, etc.) working on this repository.

## Project

GenRxiv is a preprint archive for AI-generated research. Built with FastAPI +
PostgreSQL. No OJS, no Apache, no PHP.

## Stack

- **API:** FastAPI (Python 3.12), `api/`
- **Database:** PostgreSQL 16, psycopg3 with connection pool
- **Conversion:** Pandoc + Tectonic, `convert-service/`
- **Reverse proxy:** nginx
- **Auth:** ORCID OAuth (the only login mechanism — no passwords)
- **Tunnel:** Cloudflare Tunnel

## Build and run

```bash
# From repo root, using root .env for secrets:
docker compose -f deploy/docker-compose.yml --env-file .env up -d --build

# Rebuild just the API:
docker compose -f deploy/docker-compose.yml --env-file .env up -d --build api

# View logs:
docker logs deploy-api-1 -f --tail 50

# The site is at http://localhost:8080
```

## Tests

```bash
# Conversion service (requires pandoc + tectonic):
cd convert-service && pip install -r requirements-dev.txt && pytest test_app.py -v

# API tests (requires PostgreSQL):
cd api && pip install -r requirements-dev.txt
export DATABASE_URL_TEST="postgresql://user:pass@localhost:5432/genrxiv_test"
pytest test_api.py -v

# Without DATABASE_URL_TEST, DB-dependent tests are skipped automatically.
```

CI runs both suites on every push/PR (`.github/workflows/tests.yml`).

## Key paths

| Path | Purpose |
|---|---|
| `api/main.py` | FastAPI app, middleware, router mounting |
| `api/config.py` | Config dataclass from environment variables |
| `api/db.py` | psycopg3 pool, schema definition |
| `api/auth.py` | ORCID OAuth, sessions, require_author/require_admin |
| `api/articles.py` | Submission, viewing, moderation, endorsements, stats |
| `api/oai.py` | OAI-PMH 2.0 endpoint |
| `api/sitemap.py` | Sitemap, robots.txt |
| `api/web.py` | HTML pages (browse, submit, dashboard, admin) |
| `convert-service/app.py` | Markdown to HTML/PDF conversion |
| `deploy/docker-compose.yml` | Container stack |
| `deploy/nginx.conf` | Reverse proxy config |
| `deploy/.env.example` | Environment variable documentation |
| `docs/MIGRATION.md` | Migration plan from OJS to FastAPI |

## Environment variables

See `deploy/.env.example` for the full list. Key ones:

- `DATABASE_URL` — PostgreSQL connection string
- `ORCID_CLIENT_ID` / `ORCID_CLIENT_SECRET` — ORCID OAuth app
- `SESSION_SECRET` — Session signing secret
- `ADMIN_ORCIDS` — Comma-separated ORCIDs with admin/moderation access
- `ARK_NAAN` — ARK Name Assigning Authority Number (default: 99999)
- `CF_TUNNEL_TOKEN` — Cloudflare Tunnel token
- `SMTP_*` — Resend SMTP for email notifications

**Never commit `.env`.** It is gitignored. A pre-commit hook blocks secrets.

## Database schema

Six tables: `authors`, `articles`, `article_authors`, `downloads`,
`endorsements`, `sessions`. Schema is in `api/db.py` (`SCHEMA_SQL`).
Tables are created automatically on API startup via `init_schema()`.

## API structure

- All SQL uses parameterized queries (psycopg3 `%s` placeholders)
- Auth dependencies: `get_current_author` (optional), `require_author`
  (401 if not logged in), `require_admin` (403 if not admin)
- Article routes use `{ark:path}` to capture ARKs containing slashes
- Specific routes (`/pdf`, `/markdown`, `/jsonld`) are registered before
  the catch-all `/{ark:path}` route
- Rate limiting via SlowAPI: 5/min for submissions, 10/min for ORCID
  callback, 200/min global default

## Security notes

- ORCID is the only login mechanism — no email/password registration
- Input validation: ORCID format, title/abstract/keyword length limits,
  license whitelist, file extension whitelist
- Path traversal protection on all file-serving endpoints
- Security headers at both nginx and FastAPI levels
- API docs at `/api/docs` (not default `/docs`)
- See `SECURITY.md` for the full policy

## Pre-commit hooks

```bash
# Lightweight (no dependencies):
cp scripts/pre-commit.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit

# Thorough (gitleaks + checks):
pip install pre-commit && pre-commit install
```

## Commit style

- Focus on "why" not "what"
- Include `Generated with [Devin]` and `Co-Authored-By: Devin` in commits
- Do not push unless explicitly asked
- Do not commit if no changes exist
