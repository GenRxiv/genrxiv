# GenRxiv Migration: OJS to Purpose-Built FastAPI

## Status: Complete

All phases implemented, tested, and deployed. OJS has been removed.

## Decision

Replace Open Journal Systems with a purpose-built FastAPI application.
OJS's editorial workflow (review rounds, copyediting, production stages,
editorial boards) does not match GenRxiv's model: direct submission,
lightweight moderation, immediate publication, agent-readable access.

## What stays

| Component | Status | Notes |
|---|---|---|
| Conversion service (`convert-service/`) | Unchanged | Markdown→HTML/PDF via Pandoc + Tectonic |
| Splash page (`site/index.html`) | Minor updates | Update links to new API endpoints |
| PostgreSQL | Reused, new schema | Drop OJS tables, create GenRxiv tables |
| Nginx | Simplified | No more `sub_filter`, no more `/app/` prefix |
| Cloudflare Tunnel | Unchanged | Routes to nginx as before |
| Resend SMTP | Unchanged | For notifications |
| Backblaze B2 backups | Unchanged | Nightly DB + files backup |
| ORCID OAuth | Reused | New callback URL, same credentials |
| ARK identifiers | Reimplemented | Same NAAN (99999 test), same n2t.net resolver |
| Conversion service tests | Unchanged | 14 pytest tests still pass |

## What goes

| Component | Reason |
|---|---|
| OJS (Apache + PHP) | Wrong model, too complex |
| All OJS plugins | Functionality reimplemented in FastAPI |
| OJS theme/templates | Replaced by FastAPI templates |
| OJS entrypoint scripts | No longer needed |
| OJS database tables | Replaced by simple schema |

## New architecture

```
                    ┌──────────────────────────────────────────┐
                    │         GenRxiv API (FastAPI)             │
                    │                                          │
  Author/Agent ────→│  POST /api/submit          (submission)  │
  (ORCID auth)      │  GET  /api/submissions/{id} (status)     │
                    │  GET  /api/articles         (list/search) │
                    │  PATCH /api/articles/{id}   (moderate)    │
                    │                                          │
  Reader/Agent ────→│  GET  /article/{ark}       (HTML render)  │
                    │  GET  /article/{ark}/pdf    (PDF download) │
                    │  GET  /article/{ark}/jsonld (metadata)    │
                    │                                          │
  Machine ─────────→│  GET  /oai                 (OAI-PMH)      │
                    │  GET  /sitemap.xml          (sitemap)      │
                    │  GET  /robots.txt           (robots)       │
                    │  GET  /api/articles?format=jsonld (bulk)  │
                    │                                          │
  Admin ───────────→│  GET  /admin/queue          (moderation)  │
                    │  PATCH /admin/articles/{id} (approve/reject) │
                    └─────┬──────────┬──────────┬───────────────┘
                          │          │          │
                   ┌──────▼──┐ ┌─────▼────┐ ┌──▼──────────┐
                   │PostgreSQL│ │Convert   │ │Download     │
                   │(simple   │ │Service   │ │Tracker      │
                   │ schema)  │ │(existing)│ │(agent/human)│
                   └──────────┘ └──────────┘ └─────────────┘
```

## Database schema

```sql
-- Authors (ORCID-identified)
CREATE TABLE authors (
    id SERIAL PRIMARY KEY,
    orcid TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    affiliation TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Articles
CREATE TABLE articles (
    id SERIAL PRIMARY KEY,
    ark TEXT UNIQUE NOT NULL,              -- ARK identifier (e.g. ark:/99999/genrxiv-XXXXX)
    title TEXT NOT NULL,
    abstract TEXT,
    license TEXT NOT NULL DEFAULT 'CC-BY-4.0',
    license_url TEXT NOT NULL DEFAULT 'https://creativecommons.org/licenses/by/4.0/',
    keywords TEXT[] DEFAULT '{}',
    source_markdown TEXT NOT NULL,         -- The Markdown source (version of record)
    html_path TEXT,                        -- Path to rendered HTML in files dir
    pdf_path TEXT,                         -- Path to generated PDF in files dir
    status TEXT NOT NULL DEFAULT 'pending',-- pending | approved | rejected | published
    submitted_by INTEGER REFERENCES authors(id),
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ,
    moderated_by INTEGER REFERENCES authors(id),
    moderated_at TIMESTAMPTZ,
    moderation_note TEXT
);

-- Article-author link (many-to-many)
CREATE TABLE article_authors (
    article_id INTEGER REFERENCES articles(id) ON DELETE CASCADE,
    author_id INTEGER REFERENCES authors(id) ON DELETE CASCADE,
    "order" INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (article_id, author_id)
);

-- Download tracking
CREATE TABLE downloads (
    id SERIAL PRIMARY KEY,
    article_id INTEGER REFERENCES articles(id) ON DELETE CASCADE,
    format TEXT NOT NULL,                  -- html | pdf | jsonld | markdown
    user_agent TEXT,
    is_agent BOOLEAN NOT NULL DEFAULT false,
    ip_hash TEXT,                          -- SHA-256 of IP for dedup, not stored raw
    downloaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Sessions (for ORCID OAuth)
CREATE TABLE sessions (
    token TEXT PRIMARY KEY,
    author_id INTEGER REFERENCES authors(id) ON DELETE CASCADE,
    orcid_access_token TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL
);
```

## API endpoints

### Authentication

| Method | Path | Description |
|---|---|---|
| GET | `/auth/orcid` | Redirect to ORCID OAuth |
| GET | `/auth/orcid/callback` | ORCID callback, creates session |
| POST | `/auth/logout` | Destroy session |
| GET | `/auth/me` | Current user info |

### Submission (author/agent)

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/submit` | Author | Submit Markdown + metadata |
| GET | `/api/submissions` | Author | List own submissions |
| GET | `/api/submissions/{id}` | Author | Submission status |
| GET | `/api/articles` | Public | List published articles (paginated) |
| GET | `/api/articles/{id}` | Public | Article metadata (JSON) |
| GET | `/api/articles/{id}?format=jsonld` | Public | Article as JSON-LD |

### Reading (public)

| Method | Path | Description |
|---|---|---|
| GET | `/article/{ark}` | HTML render of article |
| GET | `/article/{ark}/pdf` | PDF download (tracked) |
| GET | `/article/{ark}/markdown` | Original Markdown source |
| GET | `/article/{ark}/jsonld` | Schema.org JSON-LD |

### Moderation (admin)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/admin/queue` | Admin | Pending submissions |
| PATCH | `/admin/articles/{id}` | Admin | Approve/reject |
| GET | `/admin/stats` | Admin | Download counts, submission counts |

### Machine access

| Method | Path | Description |
|---|---|---|
| GET | `/oai` | OAI-PMH 2.0 endpoint |
| GET | `/sitemap.xml` | Sitemap of all published articles |
| GET | `/robots.txt` | Robots file |
| GET | `/api/articles?format=jsonld&page=N` | Bulk JSON-LD export |

## OAI-PMH implementation

The OAI-PMH endpoint at `/oai` implements the OAI-PMH 2.0 protocol:

### Supported verbs

| Verb | Description |
|---|---|
| `Identify` | Repository identification |
| `ListMetadataFormats` | Supported formats (oai_dc, oai_datacite) |
| `ListSets` | No sets (single repository) |
| `ListIdentifiers` | List article identifiers with dates |
| `ListRecords` | Full records with metadata |
| `GetRecord` | Single record by identifier |
| `ListIdentifiers` (resumption) | Pagination via resumptionToken |
| `ListRecords` (resumption) | Pagination via resumptionToken |

### Record identifier format

```
oai:genrxiv.org:ark:/99999/genrxiv-{id}
```

### Dublin Core mapping (oai_dc)

| DC field | GenRxiv field |
|---|---|
| `dc:title` | articles.title |
| `dc:creator` | authors.name (ordered) |
| `dc:subject` | articles.keywords[] |
| `dc:description` | articles.abstract |
| `dc:date` | articles.published_at |
| `dc:type` | "Preprint" |
| `dc:identifier` | articles.ark |
| `dc:rights` | articles.license_url |
| `dc:language` | "en" |

### Response format

Standard OAI-PMH 2.0 XML responses with proper error handling:
- `badArgument` — invalid parameters
- `badResumptionToken` — invalid/expired token
- `cannotDisseminateFormat` — unsupported metadata prefix
- `idDoesNotExist` — unknown identifier
- `noRecordsMatch` — no records for the query
- `noSetHierarchy` — sets not supported

## Sitemap implementation

`/sitemap.xml` lists all published articles:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://genrxiv.org/article/ark:/99999/genrxiv-2026-00001</loc>
    <lastmod>2026-09-03T12:00:00+00:00</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
  </url>
  ...
</urlset>
```

For >50,000 articles, sitemap index files are generated.

## JSON-LD metadata export

Each published article emits Schema.org `ScholarlyArticle` JSON-LD:

```json
{
  "@context": "https://schema.org",
  "@type": "ScholarlyArticle",
  "@id": "ark:/99999/genrxiv-2026-00001",
  "identifier": "ark:/99999/genrxiv-2026-00001",
  "url": "https://genrxiv.org/article/ark:/99999/genrxiv-2026-00001",
  "headline": "...",
  "abstract": "...",
  "author": [
    {
      "@type": "Person",
      "@id": "https://orcid.org/0000-...",
      "name": "...",
      "givenName": "...",
      "familyName": "...",
      "affiliation": { "@type": "Organization", "name": "..." }
    }
  ],
  "datePublished": "2026-09-03",
  "license": "https://creativecommons.org/licenses/by/4.0/",
  "keywords": "...",
  "inLanguage": "en",
  "isPartOf": {
    "@type": "PublicationVolume",
    "name": "GenRxiv",
    "publisher": {
      "@type": "Organization",
      "name": "GenRxiv"
    }
  }
}
```

Bulk export at `/api/articles?format=jsonld` returns a JSON array,
paginated by `page` and `per_page` query parameters.

## Download tracking

Every article view and download is tracked:

```python
# Agent detection by User-Agent
AGENT_PATTERNS = [
    "GPTBot", "ChatGPT", "Claude", "Anthropic", "Googlebot",
    "Bingbot", "Slackbot", "Twitterbot", "LinkedInBot",
    "PerplexityBot", "Amazonbot", "Applebot", "facebookexternalhit",
    "python-requests", "curl", "Wget", "PostmanRuntime",
]

def is_agent(user_agent: str) -> bool:
    ua_lower = user_agent.lower()
    return any(p.lower() in ua_lower for p in AGENT_PATTERNS)
```

Stats available at `/admin/stats` and per-article at `/api/articles/{id}/stats`.

## Agent-defined submission process

### Programmatic submission

```bash
# Agent submits via API
curl -X POST https://genrxiv.org/api/submit \
  -H "Authorization: Bearer <session_token>" \
  -F "markdown=@paper.md" \
  -F "title=Test Paper" \
  -F "authors=[{\"orcid\":\"0000-...\",\"name\":\"Jane Doe\"}]" \
  -F "license=CC-BY-4.0" \
  -F "keywords=AI,testing"
```

Response:
```json
{
  "id": 1,
  "ark": "ark:/99999/genrxiv-2026-00001",
  "status": "pending",
  "submitted_at": "2026-09-03T12:00:00Z"
}
```

### Web submission

A simple form at `/submit` for human authors:
1. ORCID login
2. Upload Markdown file
3. Fill in title, authors, license, keywords
4. Submit — single step, no wizard

### Moderation flow

1. Submission arrives → status `pending`
2. Admin sees it in `/admin/queue`
3. Admin approves → status `published`, `published_at` set, HTML/PDF rendered, ARK assigned
4. Admin rejects → status `rejected`, note recorded
5. Author notified via email (Resend SMTP)

Optional: auto-publish mode where submissions go directly to `published`
without moderation (configurable).

### Publication pipeline

On approval:
1. Assign ARK: `ark:/99999/genrxiv-{id:04d}`
2. Call conversion service `/render/html` → store HTML
3. Call conversion service `/convert/markdown` → store PDF
4. Set `html_path` and `pdf_path`
5. Set `status = 'published'`, `published_at = now()`
6. Article immediately visible at `/article/{ark}`
7. Included in sitemap, OAI-PMH, JSON-LD export

## Docker Compose (simplified)

```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: genrxiv
      POSTGRES_USER: genrxiv
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - db_data:/var/lib/postgresql/data

  api:
    build: ./api
    depends_on: [db, convert]
    environment:
      DATABASE_URL: postgresql://genrxiv:${DB_PASSWORD}@db/genrxiv
      ORCID_CLIENT_ID: ${ORCID_CLIENT_ID}
      ORCID_CLIENT_SECRET: ${ORCID_CLIENT_SECRET}
      SMTP_HOST: ${SMTP_HOST}
      SMTP_PORT: ${SMTP_PORT}
      SMTP_USERNAME: ${SMTP_USERNAME}
      SMTP_PASSWORD: ${SMTP_PASSWORD}
      ARK_NAAN: ${ARK_NAAN:-99999}
      SESSION_SECRET: ${SESSION_SECRET}
    volumes:
      - article_files:/app/files

  convert:
    build: ./convert-service
    volumes:
      - signups_data:/data

  nginx:
    image: nginx:alpine
    depends_on: [api, convert]
    volumes:
      - ./deploy/nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - ./site:/site:ro
    ports:
      - "8080:80"

  cloudflared:
    image: cloudflare/cloudflared:latest
    command: "tunnel --no-autoupdate --protocol http2 run --token ${CF_TUNNEL_TOKEN}"
    depends_on: [nginx]

volumes:
  db_data:
  article_files:
  signups_data:
```

No OJS container. No Apache. No PHP.

## Nginx (simplified)

```nginx
server {
    listen 80;
    server_name _;

    # Splash page
    location / {
        root /site;
        try_files $uri $uri/ /index.html;
    }

    # Signup API (legacy, on convert service)
    location /api/signup {
        proxy_pass http://convert:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Everything else → FastAPI
    location / {
        proxy_pass http://api:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

No `sub_filter`. No `/app/` prefix. No `$$$call$$` routing.

## Migration steps

1. **Create the FastAPI app** (`api/` directory) — DONE
   - Database schema + migrations
   - ORCID OAuth
   - Submission endpoint
   - Publication pipeline (calls conversion service)
   - Article viewing (HTML/PDF/Markdown/JSON-LD)
   - Moderation queue
   - Admin stats

2. **Implement machine access** — DONE
   - OAI-PMH 2.0 endpoint
   - Sitemap
   - Robots.txt
   - Bulk JSON-LD export

3. **Implement download tracking** — DONE
   - Agent/human classification
   - Per-article stats
   - Aggregate stats

4. **Implement community features** — DONE
   - Author pages
   - Keyword browsing
   - Web UI (browse, submit, dashboard, admin)

5. **Update infrastructure** — DONE
   - New `docker-compose.yml` (no OJS)
   - New `nginx.conf` (simplified, with security headers and rate limiting)
   - Update splash page links
   - Update `.env.example`
   - PostgreSQL healthcheck with startup ordering
   - Container resource limits

6. **Security hardening** — DONE
   - Input validation (ORCID, title, keywords, license, file extensions)
   - Path traversal protection
   - Rate limiting (API + nginx)
   - Security headers (nginx + FastAPI middleware)
   - API docs moved to `/api/docs`
   - Session cookie hardening

7. **Test end-to-end** — DONE
   - Submit Markdown paper
   - Moderate (approve)
   - View HTML render
   - Download PDF
   - Verify ARK
   - Verify JSON-LD
   - Verify OAI-PMH
   - Verify sitemap
   - Verify download tracking
   - API test suite (27 tests)
   - Conversion service test suite (14 tests)
   - CI workflow for both suites

8. **Decommission OJS** — DONE
   - Removed OJS container
   - Removed Apache config
   - Removed PHP dependencies
   - OJS database tables replaced

9. **Deploy and verify** — DONE
   - Rebuilt containers
   - Tested at https://genrxiv.org
   - Committed and pushed

## What we don't lose

- **OAI-PMH**: Reimplemented in FastAPI, simpler than OJS's version
- **Sitemap**: Generated from the articles table
- **JSON-LD**: Emitted per-article and in bulk
- **ARK identifiers**: Same format, same resolver
- **ORCID**: Same OAuth credentials, new callback
- **SMTP**: Same Resend relay
- **Conversion**: Same service, unchanged
- **Backups**: Same Backblaze B2 nightly job
