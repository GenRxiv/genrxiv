"""
Tests for the GenRxiv conversion service.

Run inside the convert container:
    docker compose run --rm convert pytest test_app.py -v

Or locally with pandoc + tectonic installed:
    pip install -r requirements.txt pytest httpx
    pytest test_app.py -v
"""
import io
import sqlite3
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as app_module


# ─── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Create a test client with an isolated SQLite database and fresh
    rate-limiter state (SlowAPI uses in-memory storage keyed by IP)."""
    test_db = tmp_path / "test_signups.db"
    monkeypatch.setattr(app_module, "DB_PATH", test_db)
    # Re-init the DB at the new path
    app_module._init_db()
    # Reset the rate limiter's in-memory storage so each test starts clean
    app_module.limiter.reset()
    return TestClient(app_module.app)


@pytest.fixture()
def md_file():
    """A minimal valid Markdown paper."""
    content = (
        b"# A Test Paper\n\n"
        b"## Abstract\n\n"
        b"This is a test abstract.\n\n"
        b"## Body\n\n"
        b"Some math: $E = mc^2$\n\n"
        b"A paragraph of text.\n"
    )
    return ("test.md", content, "text/markdown")


@pytest.fixture()
def tex_file():
    """A LaTeX file that should be rejected."""
    return ("paper.tex", b"\\documentclass{article}\n\\begin{document}\nHi\n\\end{document}", "application/x-tex")


# ─── /health ───────────────────────────────────────────────────────────────

class TestHealth:
    def test_returns_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


# ─── /render/html ──────────────────────────────────────────────────────────

class TestRenderHtml:
    def test_markdown_returns_html(self, client, md_file):
        r = client.post(
            "/render/html",
            files={"file": md_file},
        )
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        body = r.text
        assert "<!DOCTYPE html>" in body
        assert "A Test Paper" in body
        assert "katex" in body.lower()  # KaTeX CSS/JS loaded

    def test_latex_rejected(self, client, tex_file):
        r = client.post(
            "/render/html",
            files={"file": tex_file},
        )
        assert r.status_code == 400
        assert "markdown" in r.text.lower()

    def test_oversized_file_rejected(self, client):
        big = ("big.md", b"x" * (app_module.MAX_UPLOAD_BYTES + 1), "text/markdown")
        r = client.post("/render/html", files={"file": big})
        assert r.status_code == 413

    def test_math_rendered(self, client):
        """KaTeX delimiters should survive into the HTML output."""
        md = ("math.md", b"# Math\n\nDisplay: $$E=mc^2$$\n\nInline: $a^2+b^2=c^2$\n", "text/markdown")
        r = client.post("/render/html", files={"file": md})
        assert r.status_code == 200
        assert "E=mc^2" in r.text or "E = mc^2" in r.text

    def test_markdown_extension_accepted(self, client):
        md = ("paper.markdown", b"# Title\n\nBody.\n", "text/markdown")
        r = client.post("/render/html", files={"file": md})
        assert r.status_code == 200


# ─── /convert/markdown ─────────────────────────────────────────────────────

class TestConvertMarkdown:
    def test_markdown_returns_pdf(self, client, md_file):
        r = client.post(
            "/convert/markdown",
            files={"file": md_file},
        )
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        body = r.content
        assert body[:5] == b"%PDF-"  # PDF magic bytes

    def test_oversized_file_rejected(self, client):
        big = ("big.md", b"x" * (app_module.MAX_UPLOAD_BYTES + 1), "text/markdown")
        r = client.post("/convert/markdown", files={"file": big})
        assert r.status_code == 413


# ─── /signup ───────────────────────────────────────────────────────────────

class TestSignup:
    def test_valid_email_stored(self, client, tmp_path):
        r = client.post("/signup", json={"email": "user@example.com", "notify_on_launch": True})
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

        # Verify it's in the database
        conn = sqlite3.connect(str(tmp_path / "test_signups.db"))
        rows = conn.execute("SELECT email, notify_launch FROM signups").fetchall()
        conn.close()
        assert rows == [("user@example.com", 1)]

    def test_duplicate_email_ignored(self, client):
        r1 = client.post("/signup", json={"email": "dup@example.com"})
        r2 = client.post("/signup", json={"email": "dup@example.com"})
        assert r1.status_code == 200
        assert r2.status_code == 200  # INSERT OR IGNORE — no error

    def test_invalid_email_rejected(self, client):
        r = client.post("/signup", json={"email": "not-an-email"})
        assert r.status_code == 422  # Pydantic validation error

    def test_notify_defaults_false(self, client, tmp_path):
        client.post("/signup", json={"email": "plain@example.com"})
        conn = sqlite3.connect(str(tmp_path / "test_signups.db"))
        row = conn.execute("SELECT notify_launch FROM signups WHERE email=?", ("plain@example.com",)).fetchone()
        conn.close()
        assert row == (0,)


# ─── Rate limiting ─────────────────────────────────────────────────────────

class TestRateLimit:
    def test_signup_rate_limited(self, client):
        """5 per minute — the 6th request should get 429."""
        for i in range(5):
            r = client.post("/signup", json={"email": f"user{i}@example.com"})
            assert r.status_code == 200
        r6 = client.post("/signup", json={"email": "user5@example.com"})
        assert r6.status_code == 429

    def test_render_not_rate_limited_under_limit(self, client, md_file):
        """10 per minute — 10 requests should all succeed."""
        for _ in range(10):
            r = client.post("/render/html", files={"file": md_file})
            assert r.status_code == 200


# ─── Citation handling ──────────────────────────────────────────────────────

class TestCitations:
    """Tests for BibTeX citation extraction and rendering."""

    def test_extract_bibtex_from_markdown(self):
        """_extract_bibtex should find and extract a ```bibtex block."""
        md = """Some text [@smith2023].

## References

```bibtex
@article{smith2023,
  author = {Smith, Jane},
  title = {A Test Paper},
  year = {2023}
}
```
"""
        cleaned, bibtex = app_module._extract_bibtex(md)
        assert bibtex is not None
        assert "@article{smith2023" in bibtex
        assert "```bibtex" not in cleaned
        assert "## References" not in cleaned

    def test_extract_bibtex_no_block(self):
        """_extract_bibtex returns None when no bibtex block exists."""
        md = "Just some text without citations."
        cleaned, bibtex = app_module._extract_bibtex(md)
        assert bibtex is None
        assert cleaned == md

    def test_prepare_citations_no_bibtex(self, tmp_path):
        """_prepare_citations returns empty list when no bibtex present."""
        md = "No citations here."
        args = app_module._prepare_citations(tmp_path, md)
        assert args == []

    def test_prepare_citations_with_bibtex(self, tmp_path):
        """_prepare_citations returns citeproc args when bibtex is present."""
        md = """Text with [@smith2023].

```bibtex
@article{smith2023,
  author = {Smith, Jane},
  title = {Test},
  year = {2023}
}
```
"""
        args = app_module._prepare_citations(tmp_path, md)
        assert "--citeproc" in args
        assert any("refs.bib" in a for a in args)
        assert any("ieee.csl" in a for a in args)
        # The .bib file should exist
        assert (tmp_path / "refs.bib").exists()
        # The cleaned markdown should not contain the bibtex block
        cleaned = (tmp_path / "input.md").read_text()
        assert "```bibtex" not in cleaned

    def test_render_html_with_citations(self, client):
        """Rendering Markdown with BibTeX citations should produce numbered refs."""
        md_content = """# Test Paper

This cites [@smith2023] and also [@jones2024].

```bibtex
@article{smith2023,
  author = {Smith, Jane},
  title = {A Test Paper},
  journal = {Journal of Testing},
  year = {2023}
}

@book{jones2024,
  author = {Jones, Bob},
  title = {Another Book},
  publisher = {Academic Press},
  year = {2024}
}
```
"""
        r = client.post("/render/html", files={
            "file": ("test.md", md_content.encode(), "text/markdown"),
        })
        assert r.status_code == 200
        html = r.text
        # Citations should be rendered as numbered [1] and [2]
        assert "[1]" in html or "citation-number" in html or "csl-entry" in html
        # The raw bibtex block should NOT appear in the rendered HTML
        assert "@article{smith2023" not in html
        assert "@book{jones2024" not in html
        # The references section should be present
        assert "references" in html.lower() or "csl-bib-body" in html

    def test_render_html_without_citations_works(self, client, md_file):
        """Papers without BibTeX should still render normally."""
        r = client.post("/render/html", files={"file": md_file})
        assert r.status_code == 200
        assert "<html" in r.text.lower()
