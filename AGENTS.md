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
| `api/db.py` | psycopg3 pool, schema definition, settings helpers |
| `api/auth.py` | ORCID OAuth, sessions, require_author/require_admin |
| `api/articles.py` | Submission, viewing, moderation, endorsements, stats, versioning, maintenance |
| `api/ratelimit.py` | Rate limiter config (disablable via RATE_LIMIT_ENABLED) |
| `api/migrate.py` | SQL migration runner |
| `api/migrations/` | Numbered SQL migration files |
| `api/notifications.py` | Email notifications on approve/reject |
| `api/oai.py` | OAI-PMH 2.0 endpoint |
| `api/sitemap.py` | Sitemap, robots.txt, Atom feed |
| `api/web.py` | HTML pages (browse, submit, dashboard, admin) |
| `convert-service/app.py` | Markdown to HTML/PDF conversion |
| `deploy/docker-compose.yml` | Container stack |
| `deploy/nginx.conf` | Reverse proxy config |
| `deploy/.env.example` | Environment variable documentation |
| `scripts/backup.sh` | Backup DB + files to Backblaze B2 |
| `scripts/restore.sh` | Restore DB + files from backup |
| `scripts/maintenance.sh` | Toggle maintenance mode |
| `scripts/deploy-downtime.sh` | Full scheduled downtime workflow |
| `scripts/test-after-restore.sh` | Post-restore test runner |
| `tests/browser/` | Playwright browser tests |

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

Eight tables: `authors`, `articles`, `article_authors`, `downloads`,
`endorsements`, `sessions`, `settings`, `schema_migrations`.
Schema is in `api/db.py` (`SCHEMA_SQL`). Tables are created automatically
on API startup via `init_schema()`.

## Migrations

Numbered SQL files in `api/migrations/` (e.g., `001_schema_migrations.sql`).
Tracked in the `schema_migrations` table.

```bash
# Apply pending migrations:
docker exec -w /app deploy-api-1 python -m migrate

# Check status:
docker exec -w /app deploy-api-1 python -m migrate --status
```

To add a new migration, create `api/migrations/NNN_description.sql`.
Migrations are forward-only. For rollbacks, write a new migration that
reverses the change.

## Scheduled downtime and deployment

GenRxiv has a full scheduled-downtime workflow for patches, migrations,
and hosting changes.

### Maintenance mode

Maintenance mode is controlled by a database flag in the `settings` table.
When enabled, all routes return a 503 maintenance page except:
- `/health` — health checks
- `/admin/maintenance` — toggle maintenance mode
- `/auth/me` — session verification

```bash
# Toggle via admin API (requires ADMIN_SESSION_TOKEN in .env):
scripts/maintenance.sh on  "Scheduled maintenance"
scripts/maintenance.sh off
scripts/maintenance.sh status
```

### Backup

```bash
# Full backup (DB + article files + signups) to Backblaze B2:
scripts/backup.sh

# Dry run:
scripts/backup.sh --dry-run
```

Backups are stored in `deploy/backup/local/` and uploaded to B2 with
30-day retention. The nightly cron runs at 3am.

### Restore from archive

```bash
# Restore from latest backup:
scripts/restore.sh latest

# Restore from specific backup:
scripts/restore.sh 20250115-030000
```

This drops and recreates the database, restores from the gzipped SQL dump,
restores the article files volume, runs migrations, and verifies table counts.

### Full deployment workflow

```bash
# Full scheduled downtime (backup → maintenance → update → rebuild → migrate → test → open):
scripts/deploy-downtime.sh

# Skip git pull (code already updated):
scripts/deploy-downtime.sh --no-pull

# Restore from backup during deployment:
scripts/deploy-downtime.sh --restore latest

# Dry run (show what would happen):
scripts/deploy-downtime.sh --dry-run
```

The workflow:
1. Enable maintenance mode (site shows maintenance page)
2. Backup current database and article files
3. (Optional) Restore from a specific backup
4. Pull latest code
5. Rebuild and restart the API container
6. Run database migrations
7. Run the full test suite (91 API tests + 13 browser tests)
8. If tests pass → disable maintenance mode → site is live
9. If tests fail → maintenance mode stays on → investigate

### Cloud hosting migration

To move to a new server:

1. On the OLD server: `scripts/backup.sh` (creates final backup)
2. Transfer `deploy/backup/local/` to the NEW server
3. On the NEW server:
   - Clone the repo
   - Copy `.env` (update `DATABASE_URL`, `CF_TUNNEL_TOKEN`, etc.)
   - `scripts/restore.sh latest` (restore DB + files)
   - `scripts/test-after-restore.sh` (verify tests pass)
   - If tests pass, the site is live on the new server

### Post-restore testing

```bash
# Run the full test suite against a test database:
scripts/test-after-restore.sh
```

This creates a fresh `genrxiv_test` database, copies test files into the
API container, and runs all 91 API tests. Exits 0 if all pass.

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
- Input validation: ORCID format, title/abstract/subject length limits,
  CC0-only license, file extension whitelist
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
