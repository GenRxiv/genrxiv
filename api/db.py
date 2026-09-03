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
    affiliation TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Articles
CREATE TABLE IF NOT EXISTS articles (
    id SERIAL PRIMARY KEY,
    ark TEXT UNIQUE,
    title TEXT NOT NULL,
    abstract TEXT,
    ai_disclosure TEXT NOT NULL,
    license TEXT NOT NULL DEFAULT 'CC-BY-4.0',
    license_url TEXT NOT NULL DEFAULT 'https://creativecommons.org/licenses/by/4.0/',
    keywords TEXT[] DEFAULT '{}',
    source_markdown TEXT NOT NULL,
    html_path TEXT,
    pdf_path TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    submitted_by INTEGER REFERENCES authors(id),
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ,
    moderated_by INTEGER REFERENCES authors(id),
    moderated_at TIMESTAMPTZ,
    moderation_note TEXT
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

-- Endorsements (community upvotes)
CREATE TABLE IF NOT EXISTS endorsements (
    id SERIAL PRIMARY KEY,
    article_id INTEGER REFERENCES articles(id) ON DELETE CASCADE,
    author_id INTEGER REFERENCES authors(id) ON DELETE CASCADE,
    endorsed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (article_id, author_id)
);

-- Sessions (for ORCID OAuth)
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    author_id INTEGER REFERENCES authors(id) ON DELETE CASCADE,
    orcid_access_token TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status);
CREATE INDEX IF NOT EXISTS idx_articles_published_at ON articles(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_downloads_article_id ON downloads(article_id);
CREATE INDEX IF NOT EXISTS idx_downloads_downloaded_at ON downloads(downloaded_at DESC);
CREATE INDEX IF NOT EXISTS idx_article_authors_article_id ON article_authors(article_id);
CREATE INDEX IF NOT EXISTS idx_article_authors_author_id ON article_authors(author_id);
"""


def init_schema():
    """Create tables if they don't exist."""
    with get_conn().connection() as conn:
        conn.execute(SCHEMA_SQL)
        conn.commit()
