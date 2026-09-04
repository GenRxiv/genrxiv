"""
GenRxiv API — database connection and schema management.

Uses psycopg3 with a connection pool. Schema is managed via
a simple migration system (not Alembic — the schema is small).
"""
import psycopg
from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row

from config import config

pool: ConnectionPool | None = None


def init_pool():
    global pool
    pool = ConnectionPool(
        config.database_url,
        min_size=2,
        max_size=10,
        kwargs={"row_factory": dict_row},
        open=True,
    )


def get_conn():
    if pool is None:
        init_pool()
    return pool


SCHEMA_SQL = """
-- Authors (ORCID-identified)
CREATE TABLE IF NOT EXISTS authors (
    id SERIAL PRIMARY KEY,
    orcid TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    email TEXT,
    affiliation TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Articles
CREATE TABLE IF NOT EXISTS articles (
    id SERIAL PRIMARY KEY,
    ark TEXT UNIQUE,
    title TEXT NOT NULL,
    abstract TEXT,
    license TEXT NOT NULL DEFAULT 'CC0',
    license_url TEXT NOT NULL DEFAULT 'https://creativecommons.org/publicdomain/zero/1.0/',
    subjects TEXT[] DEFAULT '{}',
    source_markdown TEXT NOT NULL,
    html_path TEXT,
    pdf_path TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    version INTEGER NOT NULL DEFAULT 1,
    supersedes_id INTEGER REFERENCES articles(id),
    submitted_by INTEGER REFERENCES authors(id),
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ,
    moderated_by INTEGER REFERENCES authors(id),
    moderated_at TIMESTAMPTZ,
    moderation_note TEXT,
    is_retraction BOOLEAN NOT NULL DEFAULT FALSE,
    withdrawn_at TIMESTAMPTZ,
    withdrawal_reason TEXT
);

-- Article-author link (many-to-many)
CREATE TABLE IF NOT EXISTS article_authors (
    article_id INTEGER REFERENCES articles(id) ON DELETE CASCADE,
    author_id INTEGER REFERENCES authors(id) ON DELETE CASCADE,
    "order" INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (article_id, author_id)
);

-- Download tracking
CREATE TABLE IF NOT EXISTS downloads (
    id SERIAL PRIMARY KEY,
    article_id INTEGER REFERENCES articles(id) ON DELETE CASCADE,
    format TEXT NOT NULL,
    user_agent TEXT,
    is_agent BOOLEAN NOT NULL DEFAULT false,
    ip_hash TEXT,
    downloaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Sessions (for ORCID OAuth)
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    author_id INTEGER REFERENCES authors(id) ON DELETE CASCADE,
    orcid_access_token TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL
);

-- Settings (key-value store for maintenance mode, etc.)
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Schema migrations tracking
CREATE TABLE IF NOT EXISTS schema_migrations (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status);
CREATE INDEX IF NOT EXISTS idx_articles_published_at ON articles(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_downloads_article_id ON downloads(article_id);
CREATE INDEX IF NOT EXISTS idx_downloads_downloaded_at ON downloads(downloaded_at DESC);
CREATE INDEX IF NOT EXISTS idx_article_authors_article_id ON article_authors(article_id);
CREATE INDEX IF NOT EXISTS idx_article_authors_author_id ON article_authors(author_id);
CREATE INDEX IF NOT EXISTS idx_articles_supersedes_id ON articles(supersedes_id);
"""

# Migrations for existing databases (idempotent — safe to run repeatedly)
MIGRATIONS_SQL = """
-- Add email column to authors if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'authors' AND column_name = 'email') THEN
        ALTER TABLE authors ADD COLUMN email TEXT;
    END IF;
END$$;

-- Add version and supersedes_id columns to articles if they don't exist
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'articles' AND column_name = 'version') THEN
        ALTER TABLE articles ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
    END IF;
END$$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'articles' AND column_name = 'supersedes_id') THEN
        ALTER TABLE articles ADD COLUMN supersedes_id INTEGER REFERENCES articles(id);
    END IF;
END$$;

-- Add index for supersedes_id if it doesn't exist
CREATE INDEX IF NOT EXISTS idx_articles_supersedes_id ON articles(supersedes_id);

-- Add cached ORCID record columns to authors
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'authors' AND column_name = 'orcid_works_count') THEN
        ALTER TABLE authors ADD COLUMN orcid_works_count INTEGER DEFAULT 0;
    END IF;
END$$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'authors' AND column_name = 'orcid_record_fetched_at') THEN
        ALTER TABLE authors ADD COLUMN orcid_record_fetched_at TIMESTAMPTZ;
    END IF;
END$$;
"""


def init_schema():
    """Create tables if they don't exist, then run migrations."""
    with get_conn().connection() as conn:
        conn.execute(SCHEMA_SQL)
        conn.execute(MIGRATIONS_SQL)
        conn.commit()


def get_setting(key: str, default: str = "") -> str:
    """Read a setting from the settings table."""
    with get_conn().connection() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = %s", (key,)
        ).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    """Upsert a setting in the settings table."""
    with get_conn().connection() as conn:
        conn.execute(
            """INSERT INTO settings (key, value, updated_at)
               VALUES (%s, %s, now())
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()""",
            (key, value),
        )
        conn.commit()


def is_maintenance_mode() -> bool:
    """Check if the site is in maintenance mode."""
    return get_setting("maintenance_mode", "false") == "true"
