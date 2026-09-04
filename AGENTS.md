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
# API tests (111 tests, requires PostgreSQL):
cd api && pip install -r requirements-dev.txt
export DATABASE_URL_TEST="postgresql://user:pass@localhost:5432/genrxiv_test"
export RATE_LIMIT_ENABLED=false
pytest test_api.py -v

# Browser tests (16 Playwright tests, requires running API):
cd tests/browser && pip install -r requirements.txt
playwright install chromium
pytest test_submit_form.py -v

# Conversion service tests (25 tests, requires pandoc + tectonic):
cd convert-service && pip install -r requirements-dev.txt
pytest test_app.py -v

# Without DATABASE_URL_TEST, DB-dependent tests are skipped automatically.
# Total: 234 tests (193 API + 16 browser + 25 convert service).
```

CI runs all suites on every push/PR (`.github/workflows/tests.yml`).

## Key paths

| Path | Purpose |
|---|---|
| `api/main.py` | FastAPI app, middleware, router mounting |
| `api/config.py` | Config dataclass from environment variables |
| `api/db.py` | psycopg3 pool, schema definition, settings helpers |
| `api/auth.py` | ORCID OAuth, sessions, require_author/require_admin |
| `api/articles.py` | Submission, viewing, moderation, stats, versioning, maintenance |
| `api/ratelimit.py` | Rate limiter config (disablable via RATE_LIMIT_ENABLED) |
| `api/migrate.py` | SQL migration runner |
| `api/migrations/` | Numbered SQL migration files |
| `api/notifications.py` | Email notifications on approve/reject |
| `api/oai.py` | OAI-PMH 2.0 endpoint |
| `api/sitemap.py` | Sitemap, robots.txt, Atom feed |
| `api/web.py` | HTML pages (browse, submit, dashboard, admin, code of conduct) |
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
- `SCREENING_ENABLED` — Set to `true`/`1`/`yes` to enable automated screening
- `CF_API_TOKEN` — Cloudflare API token with Workers AI permission
- `CF_ACCOUNT_ID` — Cloudflare account ID for Workers AI
- `SCREENING_MODEL` — Workers AI model name (default: `@cf/meta/llama-3.2-3b-instruct`)

**Never commit `.env`.** It is gitignored. A pre-commit hook blocks secrets.

## Database schema

Eight tables: `authors`, `articles`, `article_authors`, `downloads`,
`sessions`, `settings`, `schema_migrations`, `screening_reports`.
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
7. Run the full test suite (193 API tests + 16 browser tests)
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
API container, and runs all 193 API tests. Exits 0 if all pass.

## API structure

- All SQL uses parameterized queries (psycopg3 `%s` placeholders)
- Auth dependencies: `get_current_author` (optional), `require_author`
  (401 if not logged in), `require_admin` (403 if not admin)
- Article routes use `{ark:path}` to capture ARKs containing slashes
- Specific routes (`/pdf`, `/markdown`, `/jsonld`, `/bibtex`) are
  registered before the catch-all `/{ark:path}` route
- Rate limiting via SlowAPI: 5/min for submissions, 10/min for ORCID
  callback, 200/min global default

## Submission format

Submissions are Markdown files with optional YAML front matter for
metadata and a BibTeX block for citations.

### YAML front matter

Authors embed metadata at the top of the Markdown file:

```yaml
---
title: "Paper Title"
abstract: "Summary of the research."
authors:
  - orcid: "0000-0000-0000-0001"
    name: "Co-Author Name"
subjects:
  - "Natural sciences > Mathematics"
  - "Natural sciences > Computer and information sciences"
  - "Social sciences > Economics and business"
---
```

When uploaded via the web form, the form auto-fills from the front
matter and the author can edit the values. On submission, the form
data is merged back into the front matter — the stored Markdown file
is always a complete document with title, abstract, and authors in
the front matter. The authors list is the complete author list in
publication order — the first entry is the lead author. The submitter
(logged-in ORCID user) MUST be included in the author list — one of
the human authors must submit, and you cannot remove yourself. If the
front matter does not include the submitter's ORCID, they will be
appended automatically. The conversion service parses the front
matter and renders title, authors, and abstract as a header block at
the top of the HTML and PDF output.

### Citations

Authors use Pandoc's `@citekey` syntax for inline citations and
include a `bibtex` fenced code block:

````markdown
As shown by Smith et al. [@smith2023], the method converges.

```bibtex
@article{smith2023,
  author = {Smith, Jane},
  title = {A Test Paper},
  journal = {Journal of Testing},
  year = {2023},
  doi = {10.1234/example}
}
```
````

The conversion service extracts the BibTeX, renders citations as
numbered references [1], [2] in citation order (IEEE style), and
strips the raw BibTeX from the HTML.

### License

All submissions are CC0 (Public Domain Dedication). No other license
is accepted.

### Subject classifications

Exactly 3 OECD Fields of Science classifications are required.
Fetch the taxonomy at `GET /api/fos`. Format: "Domain > Subdomain".

### Article removal: delete, retraction, and withdrawal

GenRxiv has three distinct removal mechanisms, each with a different
scope and legal/scholarly purpose:

| Mechanism | Who | Scope | ARK behaviour |
|---|---|---|---|
| Hard delete | Author | `pending` / `rejected` only | No ARK yet — row + files removed |
| Retraction | Author (one-click) | `published` / `superseded` | ARK transfers to the retraction notice; original preserved as superseded |
| Withdrawal | Admin (reason required) | `published` | ARK persists, resolves to a tombstone page; content no longer served |

- **Hard delete** (`/dashboard/delete/{id}`): the author can permanently
  remove an unpublished submission. Published articles cannot be hard-deleted
  — their ARK is a persistent identifier that may be cited externally.
- **Retraction** (`/dashboard/retract/{id}`): the author submits a retraction
  notice (a new version with `is_retraction = TRUE`) that goes through the
  normal moderation pipeline. On approval the ARK transfers to the retraction
  notice and the article page shows a "this article has been retracted"
  banner. This is the scholarly norm (COPE) and preserves the citation record.
- **Withdrawal** (`/admin/articles/{id}/withdraw`): admin-only, used for
  DMCA/DSA takedowns and research-integrity findings. Sets `status =
  'withdrawn'`, records `withdrawal_reason` and `withdrawn_at`. The ARK
  resolves to a tombstone page; PDF/Markdown/JSON-LD/BibTeX return `410 Gone`.
  OAI-PMH advertises `deletedRecord: transient` and returns a `status="deleted"`
  header for withdrawn records; sitemap and feeds exclude them.

Schema columns (migration `007_retraction_and_withdrawal.sql`):
`articles.is_retraction`, `articles.withdrawn_at`, `articles.withdrawal_reason`.

### Automated submission screening

GenRxiv can auto-screen submissions using a small language model via
Cloudflare Workers AI. This is the arXiv model: screening (is this a
paper-shaped object in scope?), not peer review (is the science correct?).

**Flow:**
1. After a submission passes structural validation, the screening model
   evaluates the title, abstract, and truncated body.
2. The model returns a structured JSON report: `format_ok`, `in_scope`,
   `spam_likelihood`, `has_abstract`, `has_references`, `flags`, `summary`.
3. If the report is clean (all checks pass, no flags, low spam), the
   submission is **auto-published** immediately.
4. If the report has any flags, the submission stays **pending** for human
   review. The admin queue and submission detail page show the screening
   report alongside the submission.
5. The model **never auto-rejects**. Flagged submissions wait for a human.

**Configuration** (env vars):
- `SCREENING_ENABLED=true` — enable screening
- `CF_API_TOKEN` — Cloudflare API token with Workers AI permission
- `CF_ACCOUNT_ID` — Cloudflare account ID
- `SCREENING_MODEL` — model name (default: `@cf/meta/llama-3.2-3b-instruct`)

When screening is disabled (default), all submissions stay pending for
manual admin approval — the existing behavior is unchanged.

Screening reports are stored in the `screening_reports` table for audit.
Module: `api/screening.py`. Migration: `008_screening_reports.sql`.

The screening prompt also checks for:
- **Prompt injection / jailbreak attempts**: The model is instructed to flag
  any text that appears to be an attempt to override its instructions.
  A heuristic pre-check catches common injection patterns ("ignore all
  previous instructions", "disregard the system prompt", etc.) before
  the model sees the content. If injection is detected, the submission
  is auto-flagged regardless of the model's verdict.
- **Prohibited content**: The model flags hate speech, harassment,
  defamatory content, and content that violates the Code of Conduct.
  These submissions always go to human review.

### Code of Conduct

GenRxiv has a public Code of Conduct at `/code-of-conduct` (module:
`api/code_of_conduct.py`). It covers authorship, originality, scope,
respect and safety, legal compliance, interaction with the screening
system, and agent responsibilities. It draws on COPE and arXiv standards.

Authors must agree to the Code of Conduct by checking a third checkbox
on the submission form (alongside the existing "reviewed for accuracy"
and "CC0 agreement" checkboxes). The server validates all three
agreements on every submission.

The agent guide (`/api/agent-guide`) and AI plugin manifest
(`/well-known/ai-plugin.json`) both reference the Code of Conduct.

## Agent discovery endpoints

Agents can discover and interact with GenRxiv via:

| Endpoint | Purpose |
|---|---|
| `GET /api/agent-guide` | Plain-text guide for agents (submission, auth, discovery) |
| `GET /.well-known/ai-plugin.json` | AI plugin manifest |
| `GET /api/fos` | OECD FOS taxonomy (JSON) |
| `GET /api/openapi.json` | OpenAPI schema |
| `GET /api/docs` | Interactive Swagger UI |
| `GET /oai?verb=Identify` | OAI-PMH 2.0 endpoint |
| `GET /sitemap.xml` | XML sitemap |
| `GET /feed.xml` | Atom 1.0 feed |
| `GET /robots.txt` | Robots file (advertises agent endpoints) |

### Per-article endpoints for agents

| Endpoint | Purpose |
|---|---|
| `GET /api/articles/{id}` | Article metadata (JSON) |
| `GET /article/{ark}/jsonld` | Schema.org JSON-LD |
| `GET /article/{ark}/bibtex` | BibTeX references (plain text) |
| `GET /api/articles/{ark}/references` | Parsed references (JSON) |
| `GET /article/{ark}/markdown` | Original Markdown source |
| `GET /article/{ark}/pdf` | PDF rendering |

### Agent conduct

Before submitting on behalf of a user, an agent MUST:
1. Verify the user is authenticated via ORCID (check `GET /auth/me`)
2. Confirm the user has explicitly agreed to the submission
3. Show a preview of what will be submitted
4. Get explicit confirmation before calling `POST /api/submit`
5. Never submit on behalf of a user who is not present and authenticated

See the full agent guide at `GET /api/agent-guide` for details.

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
