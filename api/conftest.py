"""
Pytest fixtures for the GenRxiv API test suite.

Environment:
    Set DATABASE_URL_TEST to a PostgreSQL connection string for a *disposable*
    test database, e.g.:
        export DATABASE_URL_TEST="postgresql://postgres:postgres@localhost:5432/genrxiv_test"

    If DATABASE_URL_TEST is unset, every database-dependent test is skipped
    automatically (via the ``no_db`` marker / ``skipif`` guard), while the
    handful of endpoints that do not touch the database (health, robots.txt,
    OAI-PMH Identify / ListMetadataFormats / error responses) still run.
"""
import os
import tempfile
from datetime import datetime, timezone, timedelta

import pytest

# ─── Environment bootstrap ─────────────────────────────────────────────────
# The application reads ``DATABASE_URL`` at import time (config.Config.from_env),
# so we must point it at the test database *before* any api module is imported.
# We also register a test admin ORCID so admin-guarded endpoints can be exercised.

TEST_DB_URL = os.environ.get("DATABASE_URL_TEST", "")

no_db = not bool(TEST_DB_URL)

if TEST_DB_URL:
    os.environ.setdefault("DATABASE_URL", TEST_DB_URL)
else:
    # Fall back to a harmless placeholder so Config.from_env() does not blow up
    # when the api modules are imported in a database-less environment.
    os.environ.setdefault("DATABASE_URL", "postgresql://nouser:nopass@localhost:5432/nodb")

# Test admin ORCID — kept distinct from the regular test author so we can assert
# 403-for-non-admin behaviour.
TEST_ADMIN_ORCID = "0000-0000-0000-0001"
TEST_AUTHOR_ORCID = "0000-0000-0000-0000"
# Force-set (not setdefault) so we override any production env vars.
os.environ["ADMIN_ORCIDS"] = TEST_ADMIN_ORCID
os.environ.setdefault("SESSION_SECRET", "test-session-secret")
# Clear SMTP settings so notification tests don't try to send real email
os.environ["SMTP_HOST"] = ""
os.environ["SMTP_USERNAME"] = ""
os.environ["SMTP_PASSWORD"] = ""

# A throwaway files directory so rendered article artefacts never touch /app/files.
_FILES_TMP = tempfile.mkdtemp(prefix="genrxiv_test_files_")
os.environ.setdefault("FILES_DIR", _FILES_TMP)

# Now it is safe to import the application modules.
import db as db_module
from db import init_pool, init_schema, get_conn
from config import config
from auth import SESSION_COOKIE, SESSION_DURATION
import main as main_module

# Override the frozen config's admin_orcids to match our test admin ORCID.
# This is necessary because config is created at import time from env vars,
# and we need to ensure the test admin ORCID is the only admin.
object.__setattr__(config, "admin_orcids", (TEST_ADMIN_ORCID,))
# Clear SMTP config so notifications are no-ops during tests
object.__setattr__(config, "smtp_host", "")
object.__setattr__(config, "smtp_username", "")
object.__setattr__(config, "smtp_password", "")


# ─── Skip marker ────────────────────────────────────────────────────────────

requires_db = pytest.mark.skipif(no_db, reason="No test database (set DATABASE_URL_TEST)")


# ─── Fixtures ───────────────────────────────────────────────────────────────

DROP_SQL = """
DROP TABLE IF EXISTS sessions CASCADE;
DROP TABLE IF EXISTS endorsements CASCADE;
DROP TABLE IF EXISTS downloads CASCADE;
DROP TABLE IF EXISTS article_authors CASCADE;
DROP TABLE IF EXISTS articles CASCADE;
DROP TABLE IF EXISTS authors CASCADE;
"""


@pytest.fixture()
def db(tmp_path):
    """Set up a fresh schema + seed data, yield a descriptor dict, tear down.

    Yields a dict with the ids/tokens the tests need:
        author_id, admin_id, article_id, ark, orcid, admin_orcid,
        regular_token, admin_token
    """
    # Redirect the (frozen) config's files_dir to an isolated temp dir so that
    # any rendered HTML/PDF artefacts are written somewhere disposable.
    object.__setattr__(config, "files_dir", str(tmp_path))

    # (Re)initialise the connection pool against the test database.
    if db_module.pool is not None:
        try:
            db_module.pool.close()
        except Exception:
            pass
    init_pool()

    # Drop any leftover tables from a previous run, then create fresh.
    with get_conn().connection() as conn:
        conn.execute(DROP_SQL)
        conn.commit()
    init_schema()

    now = datetime.now(timezone.utc)

    with get_conn().connection() as conn:
        # ── Authors ────────────────────────────────────────────────────────
        author_row = conn.execute(
            """INSERT INTO authors (orcid, name, email, affiliation)
               VALUES (%s, %s, %s, %s)
               RETURNING id, orcid, name""",
            (TEST_AUTHOR_ORCID, "Test Author", "test@example.com", "Test University"),
        ).fetchone()
        author_id = author_row["id"]

        admin_row = conn.execute(
            """INSERT INTO authors (orcid, name, email, affiliation)
               VALUES (%s, %s, %s, %s)
               RETURNING id, orcid, name""",
            (TEST_ADMIN_ORCID, "Test Admin", "admin@example.com", "GenRxiv"),
        ).fetchone()
        admin_id = admin_row["id"]

        # ── A published article ────────────────────────────────────────────
        ark = "ark:/99999/genrxiv-0001"

        # Pre-rendered artefacts on disk so the HTML/PDF view endpoints never
        # need to call out to the conversion service during tests.
        article_dir = tmp_path / "article_files"
        article_dir.mkdir(parents=True, exist_ok=True)
        html_file = article_dir / "article.html"
        html_file.write_text("<html><body><h1>A Test Paper</h1><p>Body.</p></body></html>", encoding="utf-8")
        pdf_file = article_dir / "article.pdf"
        pdf_file.write_bytes(b"%PDF-1.4\n%test pdf content\n%%EOF\n")
        html_rel = f"article_files/article.html"
        pdf_rel = f"article_files/article.pdf"

        article_row = conn.execute(
            """INSERT INTO articles
                   (ark, title, abstract, ai_disclosure, license, license_url,
                    keywords, source_markdown, html_path, pdf_path, status,
                    submitted_by, submitted_at, published_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'published',
                       %s, %s, %s)
               RETURNING id""",
            (
                ark,
                "A Test Paper on AI-Generated Research",
                "This is a test abstract.",
                "Drafted by an AI, verified by the authors.",
                "CC-BY-4.0",
                "https://creativecommons.org/licenses/by/4.0/",
                ["AI", "machine learning"],
                "# A Test Paper\n\nSome body text.\n",
                html_rel,
                pdf_rel,
                author_id,
                now - timedelta(days=1),
                now,
            ),
        ).fetchone()
        article_id = article_row["id"]

        # Link author → article
        conn.execute(
            """INSERT INTO article_authors (article_id, author_id, "order")
               VALUES (%s, %s, 0)""",
            (article_id, author_id),
        )

        # ── Sessions ───────────────────────────────────────────────────────
        expires = now + SESSION_DURATION

        regular_token = "test-session-regular-" + os.urandom(4).hex()
        conn.execute(
            """INSERT INTO sessions (token, author_id, orcid_access_token, expires_at)
               VALUES (%s, %s, %s, %s)""",
            (regular_token, author_id, "fake-regular-token", expires),
        )

        admin_token = "test-session-admin-" + os.urandom(4).hex()
        conn.execute(
            """INSERT INTO sessions (token, author_id, orcid_access_token, expires_at)
               VALUES (%s, %s, %s, %s)""",
            (admin_token, admin_id, "fake-admin-token", expires),
        )

        conn.commit()

    yield {
        "author_id": author_id,
        "admin_id": admin_id,
        "article_id": article_id,
        "ark": ark,
        "orcid": TEST_AUTHOR_ORCID,
        "admin_orcid": TEST_ADMIN_ORCID,
        "regular_token": regular_token,
        "admin_token": admin_token,
    }

    # ── Teardown ───────────────────────────────────────────────────────────
    with get_conn().connection() as conn:
        conn.execute(DROP_SQL)
        conn.commit()
    if db_module.pool is not None:
        try:
            db_module.pool.close()
        except Exception:
            pass
        db_module.pool = None


@pytest.fixture()
def app_client():
    """A TestClient with no database backing — only for db-free endpoints."""
    from fastapi.testclient import TestClient
    return TestClient(main_module.app)


@pytest.fixture()
def client(db):
    """An unauthenticated TestClient backed by the seeded test database."""
    from fastapi.testclient import TestClient
    return TestClient(main_module.app)


@pytest.fixture()
def authed_client(db):
    """A TestClient authenticated as the regular (non-admin) test author."""
    from fastapi.testclient import TestClient
    c = TestClient(main_module.app)
    c.cookies.set(SESSION_COOKIE, db["regular_token"])
    return c


@pytest.fixture()
def admin_client(db):
    """A TestClient authenticated as the test admin author."""
    from fastapi.testclient import TestClient
    c = TestClient(main_module.app)
    c.cookies.set(SESSION_COOKIE, db["admin_token"])
    return c
