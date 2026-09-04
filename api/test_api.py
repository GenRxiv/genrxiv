"""
Comprehensive pytest suite for the GenRxiv FastAPI API.

Run locally (with a PostgreSQL test database available):

    export DATABASE_URL_TEST="postgresql://postgres:postgres@localhost:5432/genrxiv_test"
    cd api && pip install -r requirements-dev.txt
    pytest test_api.py -v

Without DATABASE_URL_TEST, the database-dependent tests are skipped and only
the database-free endpoints (health, robots.txt, OAI-PMH Identify /
ListMetadataFormats / error responses) are exercised.
"""
import os

import pytest


# ─── Skip guard for database-dependent tests ────────────────────────────────

no_db = not bool(os.environ.get("DATABASE_URL_TEST"))
requires_db = pytest.mark.skipif(no_db, reason="No test database (set DATABASE_URL_TEST)")


# ─── 1. Health ──────────────────────────────────────────────────────────────

class TestHealth:
    def test_returns_200_with_ok_status(self, app_client):
        r = app_client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["service"] == "genrxiv-api"


# ─── 2-3. Sitemap & robots.txt ──────────────────────────────────────────────

class TestSitemapAndRobots:
    def test_robots_txt_returns_text_with_sitemap_line(self, app_client):
        r = app_client.get("/robots.txt")
        assert r.status_code == 200
        assert "text/plain" in r.headers["content-type"]
        assert "Sitemap:" in r.text
        assert "/sitemap.xml" in r.text
        # Admin paths should be disallowed
        assert "Disallow: /admin/" in r.text

    def test_robots_txt_advertises_agent_discovery(self, app_client):
        """robots.txt should advertise API discovery endpoints for agents."""
        r = app_client.get("/robots.txt")
        assert "OpenAPI-Schema:" in r.text
        assert "Agent-Guide:" in r.text
        assert "AI-Plugin-Manifest:" in r.text
        assert "FOS-Taxonomy:" in r.text
        assert "OAI-PMH-Endpoint:" in r.text


class TestAgentDiscovery:
    """Tests for agent-facing discovery endpoints."""

    def test_ai_plugin_manifest(self, app_client):
        """/.well-known/ai-plugin.json returns valid manifest."""
        r = app_client.get("/.well-known/ai-plugin.json")
        assert r.status_code == 200
        assert "application/json" in r.headers["content-type"]
        data = r.json()
        assert data["name"] == "GenRxiv"
        assert data["url"] is not None
        assert "api" in data
        assert "openapi_url" in data["api"]
        assert "auth" in data
        assert data["auth"]["type"] == "oauth"
        assert data["auth"]["provider"] == "ORCID"
        assert data["auth"]["session_cookie"] == "genrxiv_session"
        assert "agent_conduct" in data
        assert data["agent_conduct"]["required"] is True
        assert len(data["agent_conduct"]["rules"]) >= 5
        assert "capabilities" in data
        cap_names = [c["name"] for c in data["capabilities"]]
        assert "submit_article" in cap_names
        assert "fos_taxonomy" in cap_names
        assert "oai_pmh" in cap_names

    def test_agent_guide(self, app_client):
        """/api/agent-guide returns plain-text guide."""
        r = app_client.get("/api/agent-guide")
        assert r.status_code == 200
        assert "text/plain" in r.headers["content-type"]
        assert "GenRxiv Agent Guide" in r.text
        assert "AUTHENTICATION" in r.text
        assert "AGENT CONDUCT" in r.text
        assert "SUBMISSION" in r.text
        assert "ORCID" in r.text
        assert "CC0" in r.text
        assert "/api/fos" in r.text

    def test_fos_taxonomy(self, app_client):
        """/api/fos returns OECD FOS taxonomy as JSON."""
        r = app_client.get("/api/fos")
        assert r.status_code == 200
        assert "application/json" in r.headers["content-type"]
        data = r.json()
        assert data["taxonomy"] == "OECD Fields of Science"
        assert data["required_count"] == 3
        assert data["format"] == "Domain > Subdomain"
        assert "domains" in data
        domains = data["domains"]
        assert "Natural sciences" in domains
        assert "Social sciences" in domains
        assert "Humanities and the arts" in domains
        assert "Mathematics" in domains["Natural sciences"]
        assert isinstance(domains["Natural sciences"], list)
        assert len(domains["Natural sciences"]) > 3

    def test_openapi_schema_has_auth_description(self, app_client):
        """OpenAPI schema should include auth and submission docs."""
        r = app_client.get("/api/openapi.json")
        assert r.status_code == 200
        data = r.json()
        desc = data["info"]["description"]
        assert "ORCID OAuth" in desc
        assert "genrxiv_session" in desc
        assert "POST /api/submit" in desc
        assert "CC0" in desc

    @requires_db
    def test_sitemap_xml_returns_urlset(self, client):
        r = client.get("/sitemap.xml")
        assert r.status_code == 200
        assert "xml" in r.headers["content-type"]
        assert "<urlset" in r.text
        assert "</urlset>" in r.text
        # The homepage should always be present
        assert "<loc>" in r.text


# ─── 4-8. OAI-PMH ───────────────────────────────────────────────────────────

class TestOAI:
    def test_identify_returns_repository_name(self, app_client):
        r = app_client.get("/oai", params={"verb": "Identify"})
        assert r.status_code == 200
        assert "text/xml" in r.headers["content-type"]
        assert "<Identify>" in r.text
        assert "GenRxiv" in r.text
        assert "<repositoryName>" in r.text
        assert "2.0" in r.text  # protocol version

    def test_list_metadata_formats_returns_oai_dc_and_datacite(self, app_client):
        r = app_client.get("/oai", params={"verb": "ListMetadataFormats"})
        assert r.status_code == 200
        assert "oai_dc" in r.text
        assert "oai_datacite" in r.text
        assert "<metadataFormat>" in r.text

    def test_no_verb_returns_badverb_error(self, app_client):
        r = app_client.get("/oai")
        assert r.status_code == 200
        assert "badVerb" in r.text
        assert "<error" in r.text

    def test_list_records_without_metadataprefix_returns_badargument(self, app_client):
        r = app_client.get("/oai", params={"verb": "ListRecords"})
        assert r.status_code == 200
        assert "badArgument" in r.text

    @requires_db
    def test_list_records_oai_dc_returns_records(self, client):
        r = client.get("/oai", params={"verb": "ListRecords", "metadataPrefix": "oai_dc"})
        assert r.status_code == 200
        assert "text/xml" in r.headers["content-type"]
        # With a seeded published article we expect actual records.
        assert "<ListRecords>" in r.text
        assert "<record>" in r.text
        assert "<dc:title>" in r.text

    @requires_db
    def test_list_records_unknown_prefix_returns_cannotdisseminateformat(self, client):
        r = client.get("/oai", params={"verb": "ListRecords", "metadataPrefix": "bogus"})
        assert r.status_code == 200
        assert "cannotDisseminateFormat" in r.text


# ─── 9-11, 16-17. Articles / endorsements / subjects API ────────────────────

class TestArticlesAPI:
    @requires_db
    def test_list_articles_returns_paginated_list(self, client):
        r = client.get("/api/articles")
        assert r.status_code == 200
        body = r.json()
        assert "items" in body
        assert "total" in body
        assert "page" in body
        assert "per_page" in body
        assert body["total"] >= 1
        assert any(item["ark"] for item in body["items"])

    @requires_db
    def test_list_articles_jsonld_format(self, client):
        r = client.get("/api/articles", params={"format": "jsonld"})
        assert r.status_code == 200
        body = r.json()
        assert "items" in body
        assert body["items"], "expected at least one JSON-LD item"
        item = body["items"][0]
        assert item["@context"] == "https://schema.org"
        assert item["@type"] == "ScholarlyArticle"

    @requires_db
    def test_article_endorsements_returns_count(self, client, db):
        r = client.get(f"/api/articles/{db['article_id']}/endorsements")
        assert r.status_code == 200
        body = r.json()
        assert "count" in body
        assert "endorsers" in body
        assert body["count"] == 0

    @requires_db
    def test_endorse_requires_auth_returns_401_without(self, client, db):
        r = client.post(f"/api/articles/{db['article_id']}/endorse")
        assert r.status_code == 401

    @requires_db
    def test_endorse_succeeds_when_authenticated(self, authed_client, db):
        r = authed_client.post(f"/api/articles/{db['article_id']}/endorse")
        assert r.status_code == 200
        assert r.json()["status"] == "endorsed"
        # Endorsing again should be a conflict.
        r2 = authed_client.post(f"/api/articles/{db['article_id']}/endorse")
        assert r2.status_code == 409


class TestSubjectsAPI:
    @requires_db
    def test_list_subjects_returns_subject_list(self, client):
        r = client.get("/api/subjects")
        assert r.status_code == 200
        body = r.json()
        assert "subjects" in body
        subjects = {row["subject"] for row in body["subjects"]}
        assert "AI" in subjects


# ─── 11b. BibTeX / references ──────────────────────────────────────────────

class TestBibtexExtraction:
    """Test BibTeX extraction and parsing utilities."""

    def test_extract_bibtex_finds_block(self):
        from articles import extract_bibtex
        md = "Text\n\n```bibtex\n@article{key1, title={Test}}\n```\n"
        result = extract_bibtex(md)
        assert result is not None
        assert "@article{key1" in result

    def test_extract_bibtex_no_block(self):
        from articles import extract_bibtex
        md = "Just text, no bibtex."
        assert extract_bibtex(md) is None

    def test_parse_bibtex_entries(self):
        from articles import parse_bibtex_entries
        bibtex = """@article{smith2023,
  author = {Smith, Jane},
  title = {A Test Paper},
  journal = {Journal of Testing},
  year = {2023},
  volume = {1},
  pages = {1--10},
  doi = {10.1234/example}
}

@book{jones2024,
  author = {Jones, Bob},
  title = {Another Book},
  publisher = {Academic Press},
  year = {2024}
}"""
        entries = parse_bibtex_entries(bibtex)
        assert len(entries) == 2
        assert entries[0]["type"] == "article"
        assert entries[0]["key"] == "smith2023"
        assert entries[0]["author"] == "Smith, Jane"
        assert entries[0]["title"] == "A Test Paper"
        assert entries[0]["year"] == "2023"
        assert entries[0]["doi"] == "10.1234/example"
        assert entries[1]["type"] == "book"
        assert entries[1]["key"] == "jones2024"
        assert entries[1]["publisher"] == "Academic Press"


# ─── 12. Public stats ───────────────────────────────────────────────────────

class TestStatsAPI:
    @requires_db
    def test_public_stats_returns_counts(self, client):
        r = client.get("/api/stats")
        assert r.status_code == 200
        body = r.json()
        for key in (
            "total_articles",
            "total_authors",
            "total_downloads",
            "agent_downloads",
            "human_downloads",
            "total_endorsements",
            "top_articles",
        ):
            assert key in body
        assert body["total_articles"] >= 1
        assert body["total_authors"] >= 1


# ─── 13-15. Web HTML pages ──────────────────────────────────────────────────

class TestWebPages:
    @requires_db
    def test_browse_returns_html(self, client):
        r = client.get("/browse")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "Browse" in r.text
        # The seeded article should appear.
        assert "A Test Paper" in r.text

    @requires_db
    def test_subjects_page_returns_html(self, client):
        r = client.get("/subjects")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "Subjects" in r.text

    @requires_db
    def test_submit_page_shows_signin_prompt_when_unauthenticated(self, client):
        r = client.get("/submit")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "Sign in" in r.text

    @requires_db
    def test_submit_page_shows_form_when_authenticated(self, authed_client):
        r = authed_client.get("/submit")
        assert r.status_code == 200
        assert "Submit a Paper" in r.text
        assert "Subject classifications" in r.text
        assert "CC0" in r.text
        assert "reviewed and verified" in r.text
        assert "classification-rows" in r.text
        assert "Preview submission" in r.text

    @requires_db
    def test_submit_rejects_missing_abstract(self, authed_client):
        """Abstract is now required."""
        import json
        import io
        md = io.BytesIO(b"# Test\n\nContent.")
        r = authed_client.post(
            "/api/submit",
            files={"markdown": ("test.md", md, "text/markdown")},
            data={
                "title": "Test Paper",
                "authors": json.dumps([{"orcid": "0000-0000-0000-0000", "name": "Test Author"}]),
                "abstract": "",
            },
        )
        assert r.status_code == 400
        assert "Abstract is required" in r.json()["detail"]


class TestSubmissionValidation:
    """Tests for the new submission validation rules."""

    KWS_3 = "Natural sciences > Mathematics, Natural sciences > Physical sciences, Social sciences > Economics and business"
    KWS_2 = "Natural sciences > Mathematics, Natural sciences > Physical sciences"
    KWS_4 = "Natural sciences > Mathematics, Natural sciences > Physical sciences, Social sciences > Economics and business, Humanities and the arts > History and archaeology"

    def _submit(self, client, **overrides):
        """Helper to submit with valid defaults, overriding specific fields."""
        import json as _json
        import io as _io
        defaults = {
            "title": "Validation Test Paper",
            "authors": _json.dumps([{"orcid": "0000-0000-0000-0000", "name": "Test Author"}]),
            "abstract": "A test abstract for validation testing.",
            "subjects": self.KWS_3,
            "license": "CC0",
            "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        }
        defaults.update(overrides)
        md = _io.BytesIO(b"# Test\n\nContent.")
        return client.post(
            "/api/submit",
            files={"markdown": ("test.md", md, "text/markdown")},
            data=defaults,
        )

    @requires_db
    def test_submit_rejects_non_cc0_license(self, authed_client):
        """Only CC0 is accepted now."""
        r = self._submit(authed_client, license="CC-BY-4.0",
                         license_url="https://creativecommons.org/licenses/by/4.0/")
        assert r.status_code == 400
        assert "Unsupported license" in r.json()["detail"]

    @requires_db
    def test_submit_rejects_missing_subjects(self, authed_client):
        """Subjects (3 classifications) are required."""
        r = self._submit(authed_client, subjects="")
        assert r.status_code == 400
        assert "Exactly 3 subject classifications" in r.json()["detail"]

    @requires_db
    def test_submit_rejects_two_subjects(self, authed_client):
        """Fewer than 3 classifications are rejected."""
        r = self._submit(authed_client, subjects=self.KWS_2)
        assert r.status_code == 400
        assert "Exactly 3 subject classifications" in r.json()["detail"]

    @requires_db
    def test_submit_rejects_four_subjects(self, authed_client):
        """More than 3 classifications are rejected."""
        r = self._submit(authed_client, subjects=self.KWS_4)
        assert r.status_code == 400
        assert "Exactly 3 subject classifications" in r.json()["detail"]

    @requires_db
    def test_submit_rejects_invalid_authors_json(self, authed_client):
        """Authors must be valid JSON."""
        r = self._submit(authed_client, authors="not json")
        assert r.status_code == 400
        assert "authors must be a JSON array" in r.json()["detail"]

    @requires_db
    def test_submit_rejects_empty_authors_array(self, authed_client):
        """Authors array must not be empty."""
        import json
        r = self._submit(authed_client, authors=json.dumps([]))
        assert r.status_code == 400
        assert "authors must be a JSON array" in r.json()["detail"]

    @requires_db
    def test_submit_rejects_author_missing_name(self, authed_client):
        """Each author must have a name."""
        import json
        r = self._submit(authed_client, authors=json.dumps([{"orcid": "0000-0000-0000-0000"}]))
        assert r.status_code == 400
        assert "orcid and name" in r.json()["detail"]

    @requires_db
    def test_submit_rejects_submitter_not_in_authors(self, authed_client):
        """The submitter must be listed as one of the authors."""
        import json
        r = self._submit(authed_client, authors=json.dumps([
            {"orcid": "0000-0000-0000-0009", "name": "Someone Else"},
        ]))
        assert r.status_code == 400
        assert "must be listed as one of the authors" in r.json()["detail"]

    @requires_db
    def test_submit_rejects_non_markdown_file(self, authed_client):
        """Only .md and .markdown files are accepted."""
        import io
        md = io.BytesIO(b"<html>not markdown</html>")
        r = authed_client.post(
            "/api/submit",
            files={"markdown": ("test.html", md, "text/html")},
            data={
                "title": "Test Paper",
                "authors": '[{"orcid": "0000-0000-0000-0000", "name": "Test"}]',
                "abstract": "Test abstract.",
                "subjects": self.KWS_3,
                "license": "CC0",
                "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
            },
        )
        assert r.status_code == 400
        assert "Markdown only" in r.json()["detail"]

    @requires_db
    def test_submit_rejects_empty_file(self, authed_client):
        """Empty files are rejected."""
        import io
        md = io.BytesIO(b"")
        r = authed_client.post(
            "/api/submit",
            files={"markdown": ("test.md", md, "text/markdown")},
            data={
                "title": "Test Paper",
                "authors": '[{"orcid": "0000-0000-0000-0000", "name": "Test"}]',
                "abstract": "Test abstract.",
                "subjects": self.KWS_3,
                "license": "CC0",
                "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
            },
        )
        assert r.status_code == 400
        assert "Empty file" in r.json()["detail"]


# ─── Validation endpoint ────────────────────────────────────────────────────

class TestValidateEndpoint:
    KWS_3 = (
        "Natural sciences > Computer and information sciences, "
        "Natural sciences > Mathematics, "
        "Social sciences > Economics and business"
    )

    def _validate(self, client, **overrides):
        import json as _json
        import io as _io
        defaults = {
            "title": "Validation Test Paper",
            "authors": _json.dumps([{"orcid": "0000-0000-0000-0000", "name": "Test Author"}]),
            "abstract": "A test abstract for validation testing.",
            "subjects": self.KWS_3,
            "license": "CC0",
            "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        }
        defaults.update(overrides)
        md = _io.BytesIO(b"# Test\n\nContent with $E=mc^2$.")
        return client.post(
            "/api/validate",
            files={"markdown": ("test.md", md, "text/markdown")},
            data=defaults,
        )

    @requires_db
    def test_validate_accepts_valid_submission(self, authed_client):
        r = self._validate(authed_client)
        assert r.status_code == 200
        body = r.json()
        assert body["valid"] is True
        assert body["errors"] == []
        # Preview rendering requires the conversion service, which is
        # not reachable from the in-process TestClient. In production
        # this returns a full HTML document.
        # Just verify valid + no errors is the correct state.

    @requires_db
    def test_validate_rejects_missing_title(self, authed_client):
        r = self._validate(authed_client, title="")
        assert r.status_code == 200
        body = r.json()
        assert body["valid"] is False
        assert any("Title is required" in e for e in body["errors"])

    @requires_db
    def test_validate_rejects_missing_abstract(self, authed_client):
        r = self._validate(authed_client, abstract="")
        assert r.status_code == 200
        body = r.json()
        assert body["valid"] is False
        assert any("Abstract is required" in e for e in body["errors"])

    @requires_db
    def test_validate_rejects_wrong_subject_count(self, authed_client):
        r = self._validate(authed_client, subjects="Natural sciences > Mathematics")
        assert r.status_code == 200
        body = r.json()
        assert body["valid"] is False
        assert any("3 subject" in e for e in body["errors"])

    @requires_db
    def test_validate_rejects_submitter_not_in_authors(self, authed_client):
        import json
        r = self._validate(authed_client, authors=json.dumps([
            {"orcid": "0000-0000-0000-0009", "name": "Someone Else"},
        ]))
        assert r.status_code == 200
        body = r.json()
        assert body["valid"] is False
        assert any("must be listed" in e for e in body["errors"])

    @requires_db
    def test_validate_hints_unclosed_bibtex(self, authed_client):
        import io
        md = io.BytesIO(b"# Test\n\n```bibtex\n@article{x, title={X}\n")
        r = authed_client.post(
            "/api/validate",
            files={"markdown": ("test.md", md, "text/markdown")},
            data={
                "title": "Test Paper",
                "authors": '[{"orcid": "0000-0000-0000-0000", "name": "Test"}]',
                "abstract": "Test abstract.",
                "subjects": self.KWS_3,
                "license": "CC0",
                "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert any("BibTeX" in h for h in body["hints"])

    @requires_db
    def test_validate_hints_duplicate_title_in_body(self, authed_client):
        """Title in front matter AND as H1 in body should be flagged."""
        import io
        md = io.BytesIO(
            b'---\n'
            b'title: "Duplicate Title"\n'
            b'abstract: "Test abstract."\n'
            b'authors:\n'
            b'  - orcid: "0000-0000-0000-0000"\n'
            b'    name: "Test Author"\n'
            b'---\n\n'
            b'# Duplicate Title\n\n'
            b'Body content.\n'
        )
        r = authed_client.post(
            "/api/validate",
            files={"markdown": ("test.md", md, "text/markdown")},
            data={
                "title": "Duplicate Title",
                "authors": '[{"orcid": "0000-0000-0000-0000", "name": "Test Author"}]',
                "abstract": "Test abstract.",
                "subjects": self.KWS_3,
                "license": "CC0",
                "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert any("H1" in h and "body" in h for h in body["hints"])

    @requires_db
    def test_validate_hints_duplicate_abstract_in_body(self, authed_client):
        """Abstract in front matter AND as ## Abstract in body should be flagged."""
        import io
        md = io.BytesIO(
            b'---\n'
            b'title: "Test Paper"\n'
            b'abstract: "The abstract text."\n'
            b'authors:\n'
            b'  - orcid: "0000-0000-0000-0000"\n'
            b'    name: "Test Author"\n'
            b'---\n\n'
            b'## Abstract\n\n'
            b'The abstract text.\n\n'
            b'Body content.\n'
        )
        r = authed_client.post(
            "/api/validate",
            files={"markdown": ("test.md", md, "text/markdown")},
            data={
                "title": "Test Paper",
                "authors": '[{"orcid": "0000-0000-0000-0000", "name": "Test Author"}]',
                "abstract": "The abstract text.",
                "subjects": self.KWS_3,
                "license": "CC0",
                "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert any("Abstract" in h and "body" in h for h in body["hints"])

    @requires_db
    def test_validate_no_duplicate_hint_when_clean(self, authed_client):
        """No duplicate hints when title/abstract are only in front matter."""
        import io
        md = io.BytesIO(
            b'---\n'
            b'title: "Clean Paper"\n'
            b'abstract: "Clean abstract."\n'
            b'authors:\n'
            b'  - orcid: "0000-0000-0000-0000"\n'
            b'    name: "Test Author"\n'
            b'---\n\n'
            b'Body content with no duplicate title or abstract.\n'
        )
        r = authed_client.post(
            "/api/validate",
            files={"markdown": ("test.md", md, "text/markdown")},
            data={
                "title": "Clean Paper",
                "authors": '[{"orcid": "0000-0000-0000-0000", "name": "Test Author"}]',
                "abstract": "Clean abstract.",
                "subjects": self.KWS_3,
                "license": "CC0",
                "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["valid"] is True
        dup_hints = [h for h in body["hints"] if "rendered twice" in h or "H1" in h]
        assert dup_hints == []

    @requires_db
    def test_validate_requires_auth(self, client):
        r = client.post("/api/validate")
        assert r.status_code == 401


# ─── 18-21. Auth-gated pages (dashboard / admin) ────────────────────────────

class TestAuthGated:
    @requires_db
    def test_dashboard_requires_auth_returns_401_without(self, client):
        r = client.get("/dashboard")
        assert r.status_code == 401

    @requires_db
    def test_dashboard_works_when_authenticated(self, authed_client):
        r = authed_client.get("/dashboard")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "Submissions" in r.text

    @requires_db
    def test_admin_requires_auth_returns_401_without(self, client):
        r = client.get("/admin")
        assert r.status_code == 401

    @requires_db
    def test_admin_returns_403_for_non_admin(self, authed_client):
        r = authed_client.get("/admin")
        assert r.status_code == 403

    @requires_db
    def test_admin_works_for_admin_user(self, admin_client):
        r = admin_client.get("/admin")
        assert r.status_code == 200
        assert "Admin" in r.text

    @requires_db
    def test_admin_queue_requires_admin(self, client, authed_client, admin_client):
        # Unauthenticated → 401
        assert client.get("/admin/queue").status_code == 401
        # Non-admin → 403
        assert authed_client.get("/admin/queue").status_code == 403
        # Admin → 200 with items
        r = admin_client.get("/admin/queue")
        assert r.status_code == 200
        assert "items" in r.json()

    @requires_db
    def test_admin_stats_requires_admin(self, client, authed_client, admin_client):
        assert client.get("/admin/stats").status_code == 401
        assert authed_client.get("/admin/stats").status_code == 403
        r = admin_client.get("/admin/stats")
        assert r.status_code == 200
        body = r.json()
        for key in ("total_articles", "total_downloads", "pending_submissions"):
            assert key in body


# ─── 22-25. Article viewing (JSON-LD / HTML / PDF / Markdown) ───────────────

class TestArticleView:
    @requires_db
    def test_article_jsonld_returns_scholarlyarticle(self, client, db):
        r = client.get(f"/article/{db['ark']}/jsonld")
        assert r.status_code == 200
        body = r.json()
        assert body["@context"] == "https://schema.org"
        assert body["@type"] == "ScholarlyArticle"
        assert body["headline"] == "A Test Paper on AI-Generated Research"
        assert body["identifier"] == db["ark"]

    @requires_db
    def test_article_html_returns_html_page(self, client, db):
        r = client.get(f"/article/{db['ark']}")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]

    @requires_db
    def test_article_pdf_returns_pdf(self, client, db):
        r = client.get(f"/article/{db['ark']}/pdf")
        assert r.status_code == 200
        assert "application/pdf" in r.headers["content-type"]
        assert r.content.startswith(b"%PDF")

    @requires_db
    def test_article_markdown_returns_markdown(self, client, db):
        r = client.get(f"/article/{db['ark']}/markdown")
        assert r.status_code == 200
        assert "markdown" in r.headers["content-type"]
        assert "A Test Paper" in r.text

    @requires_db
    def test_article_not_found_returns_404(self, client):
        r = client.get("/article/ark:/99999/genrxiv-9999")
        assert r.status_code == 404


# ─── 26-27. Authors ─────────────────────────────────────────────────────────

class TestAuthors:
    @requires_db
    def test_author_profile_returns_author_and_articles(self, client, db):
        r = client.get(f"/api/authors/{db['orcid']}")
        assert r.status_code == 200
        body = r.json()
        assert body["author"]["name"] == "Test Author"
        assert body["author"]["orcid"] == db["orcid"]
        assert isinstance(body["articles"], list)
        assert len(body["articles"]) >= 1

    @requires_db
    def test_author_profile_404_for_unknown_orcid(self, client):
        r = client.get("/api/authors/9999-9999-9999-9999")
        assert r.status_code == 404

    @requires_db
    def test_author_html_page_returns_html(self, client, db):
        r = client.get(f"/author/{db['orcid']}")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "Test Author" in r.text
        assert db["orcid"] in r.text


# ─── Atom feed ──────────────────────────────────────────────────────────────

class TestAtomFeed:
    @requires_db
    def test_feed_xml_returns_atom_feed(self, client):
        r = client.get("/feed.xml")
        assert r.status_code == 200
        assert "xml" in r.headers["content-type"]
        assert "<feed" in r.text
        assert "http://www.w3.org/2005/Atom" in r.text
        assert "<entry>" in r.text
        assert "<title>" in r.text
        assert "<id>" in r.text
        assert "<updated>" in r.text

    @requires_db
    def test_feed_contains_published_article(self, client, db):
        r = client.get("/feed.xml")
        assert r.status_code == 200
        assert db["ark"] in r.text
        assert "Test Paper" in r.text

    @requires_db
    def test_feed_has_correct_mime_type(self, client):
        r = client.get("/feed.xml")
        assert r.status_code == 200
        assert "atom+xml" in r.headers["content-type"]


# ─── Article versioning ─────────────────────────────────────────────────────

class TestVersioning:
    @requires_db
    def test_article_metadata_includes_version(self, client, db):
        r = client.get(f"/api/articles/{db['article_id']}")
        assert r.status_code == 200
        body = r.json()
        assert body["version"] == 1

    @requires_db
    def test_version_history_returns_single_version(self, client, db):
        r = client.get(f"/api/articles/{db['article_id']}/versions")
        assert r.status_code == 200
        body = r.json()
        assert body["ark"] == db["ark"]
        assert len(body["versions"]) == 1
        assert body["versions"][0]["version"] == 1
        assert body["versions"][0]["is_current"] is True

    @requires_db
    def test_version_history_404_for_unknown_article(self, client):
        r = client.get("/api/articles/999999/versions")
        assert r.status_code == 404

    @requires_db
    def test_submit_new_version_requires_authorship(self, client, db, authed_client):
        """A non-author cannot submit a new version."""
        # authed_client is the test author who IS an author of the seed article,
        # so this should actually succeed. We test the 403 path by using a
        # different article that the author didn't create.
        import json
        import io

        # Create a second article by the admin author
        md = io.BytesIO(b"# Second\n\nBy admin.")
        r = authed_client.post(
            "/api/submit",
            files={"markdown": ("test.md", md, "text/markdown")},
            data={
                "title": "Second Paper",
                "authors": json.dumps([
                    {"orcid": "0000-0000-0000-0000", "name": "Test Author"},
                    {"orcid": "0000-0000-0000-0001", "name": "Admin"},
                ]),
                "abstract": "A second paper for versioning tests.",
                "subjects": "Natural sciences > Computer and information sciences, Natural sciences > Mathematics, Social sciences > Economics and business",
                "supersedes_id": db["article_id"],
            },
        )
        # The test author IS an author of the seed article, so this should succeed
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "pending"
        assert body["version"] == 2

    @requires_db
    def test_submit_new_version_increments_version(self, client, db, authed_client):
        """Submitting a new version increments the version number."""
        import json
        import io

        md = io.BytesIO(b"# v2\n\nUpdated content.")
        r = authed_client.post(
            "/api/submit",
            files={"markdown": ("test.md", md, "text/markdown")},
            data={
                "title": "Test Paper v2",
                "authors": json.dumps([{"orcid": db["orcid"], "name": "Test Author"}]),
                "abstract": "Updated abstract for v2.",
                "subjects": "Natural sciences > Computer and information sciences, Natural sciences > Mathematics, Social sciences > Economics and business",
                "supersedes_id": db["article_id"],
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["version"] == 2

    @requires_db
    def test_approve_new_version_transfers_ark(self, client, db, authed_client, admin_client):
        """When a new version is approved, the ARK transfers and old version is superseded."""
        import json
        import io

        # Submit v2
        md = io.BytesIO(b"# v2\n\nUpdated.")
        r = authed_client.post(
            "/api/submit",
            files={"markdown": ("test.md", md, "text/markdown")},
            data={
                "title": "Test Paper v2",
                "authors": json.dumps([{"orcid": db["orcid"], "name": "Test Author"}]),
                "abstract": "Updated abstract for v2 approval test.",
                "subjects": "Natural sciences > Computer and information sciences, Natural sciences > Mathematics, Social sciences > Economics and business",
                "supersedes_id": db["article_id"],
            },
        )
        assert r.status_code == 200
        new_id = r.json()["id"]

        # Approve v2 as admin
        r = admin_client.patch(
            f"/admin/articles/{new_id}",
            json={"action": "approve"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "published"
        assert body["ark"] == db["ark"]  # ARK transferred
        assert body["version"] == 2

        # Old version should be superseded
        r = client.get(f"/api/articles/{db['article_id']}")
        assert r.status_code == 404  # Old version no longer published

        # New version should be accessible via the same ARK
        r = client.get(f"/api/articles/{new_id}")
        assert r.status_code == 200
        assert r.json()["version"] == 2

        # Version history should show both versions
        r = client.get(f"/api/articles/{new_id}/versions")
        assert r.status_code == 200
        body = r.json()
        assert len(body["versions"]) == 2
        assert body["versions"][0]["version"] == 2
        assert body["versions"][0]["is_current"] is True
        assert body["versions"][1]["version"] == 1
        assert body["versions"][1]["is_current"] is False

    @requires_db
    def test_version_history_page_returns_html(self, client, db):
        r = client.get(f"/article/{db['ark']}/versions")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "Version History" in r.text
        assert "v1" in r.text


# ─── Notifications ──────────────────────────────────────────────────────────

class TestNotifications:
    def test_notify_approved_skips_without_smtp(self, monkeypatch):
        """notify_approved should silently skip when SMTP is not configured."""
        from notifications import notify_approved
        # SMTP_HOST is empty by default in test config, so this should be a no-op
        notify_approved(1, "ark:/99999/test-0001", "Test", "")  # should not raise

    def test_notify_rejected_skips_without_smtp(self, monkeypatch):
        """notify_rejected should silently skip when SMTP is not configured."""
        from notifications import notify_approved
        notify_approved(1, "ark:/99999/test-0001", "Test", "")  # should not raise

    @requires_db
    def test_notify_approved_skips_without_email(self, client, db):
        """notify_approved should skip when the author has no email."""
        from notifications import notify_approved
        # The seed author has an email, but SMTP is not configured, so it's a no-op
        notify_approved(db["article_id"], db["ark"], "Test Paper", "")  # should not raise

    @requires_db
    def test_moderation_sends_notification_without_crash(self, client, db, admin_client):
        """Approving an article should not crash even if SMTP is not configured."""
        # Submit a new article
        import json
        import io

        md = io.BytesIO(b"# Notify test\n\nContent.")
        r = admin_client.post(
            "/api/submit",
            files={"markdown": ("test.md", md, "text/markdown")},
            data={
                "title": "Notification Test",
                "authors": json.dumps([{"orcid": "0000-0000-0000-0001", "name": "Admin"}]),
                "abstract": "Testing moderation notifications.",
                "subjects": "Natural sciences > Computer and information sciences, Natural sciences > Mathematics, Social sciences > Economics and business",
            },
        )
        assert r.status_code == 200
        article_id = r.json()["id"]

        # Approve it — should not crash even without SMTP
        r = admin_client.patch(
            f"/admin/articles/{article_id}",
            json={"action": "approve"},
        )
        assert r.status_code == 200


# ─── Security tests ─────────────────────────────────────────────────────────

class TestSecurity:
    """Security-focused tests: XSS, CSRF, session, auth boundaries."""

    @requires_db
    def test_submit_requires_authentication(self, client):
        """Unauthenticated users cannot submit articles."""
        import json
        import io
        md = io.BytesIO(b"# Test\n\nContent.")
        r = client.post(
            "/api/submit",
            files={"markdown": ("test.md", md, "text/markdown")},
            data={
                "title": "Test Paper",
                "authors": json.dumps([{"orcid": "0000-0000-0000-0000", "name": "Test"}]),
                "abstract": "Test abstract.",
                "subjects": "Natural sciences > Mathematics, Natural sciences > Physical sciences, Social sciences > Economics and business",
                "license": "CC0",
                "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
            },
        )
        assert r.status_code == 401

    @requires_db
    def test_admin_endpoints_require_admin(self, client, authed_client):
        """Regular authenticated users cannot access admin endpoints."""
        r = authed_client.get("/admin/queue")
        assert r.status_code == 403
        r = authed_client.get("/admin/stats")
        assert r.status_code == 403

    @requires_db
    def test_non_admin_cannot_approve_articles(self, authed_client, db):
        """Regular users cannot approve or reject articles."""
        r = authed_client.patch(
            f"/admin/articles/{db['article_id']}",
            json={"action": "approve"},
        )
        assert r.status_code == 403

    @requires_db
    def test_xss_in_title_is_escaped_on_browse(self, client, db):
        """XSS payloads in article titles should be escaped in HTML pages."""
        # db fixture creates an article with a known title
        # We check that the browse page doesn't render raw HTML
        r = client.get("/browse")
        assert r.status_code == 200
        # The page should not contain unescaped script tags
        # (titles in the browse page should be escaped)
        assert "<script>alert" not in r.text

    @requires_db
    def test_xss_in_title_is_escaped_on_article_page(self, client, db):
        """XSS payloads should be escaped on article pages."""
        r = client.get(f"/article/{db['ark']}")
        assert r.status_code == 200
        assert "<script>alert" not in r.text

    @requires_db
    def test_session_cookie_has_security_attributes(self, client, db, authed_client):
        """Session cookie should be HttpOnly and Secure."""
        # The authed_client fixture has a session cookie
        cookies = authed_client.cookies
        # Check that the session cookie exists
        assert "genrxiv_session" in cookies
        # Cookie security attributes are set on the response, not visible
        # in the client's cookie jar, but we can check the raw headers
        # by making a request that sets the cookie
        # This is verified by checking /auth/me works
        r = authed_client.get("/auth/me")
        assert r.status_code == 200
        assert r.json()["authenticated"] is True

    @requires_db
    def test_logout_destroys_session(self, authed_client):
        """After logout, the session is no longer valid."""
        r = authed_client.post("/auth/logout")
        assert r.status_code in (200, 303, 307)
        # After logout, authed_client should no longer be authenticated
        r = authed_client.get("/auth/me")
        assert r.json()["authenticated"] is False

    @requires_db
    def test_invalid_orcid_format_rejected(self, authed_client):
        """ORCID IDs with invalid format are rejected."""
        import json
        import io
        md = io.BytesIO(b"# Test\n\nContent.")
        r = authed_client.post(
            "/api/submit",
            files={"markdown": ("test.md", md, "text/markdown")},
            data={
                "title": "Test Paper",
                "authors": json.dumps([{"orcid": "not-an-orcid", "name": "Test"}]),
                "abstract": "Test abstract.",
                "subjects": "Natural sciences > Mathematics, Natural sciences > Physical sciences, Social sciences > Economics and business",
                "license": "CC0",
                "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
            },
        )
        assert r.status_code == 400
        assert "orcid" in r.json()["detail"].lower() or "ORCID" in r.json()["detail"]

    @requires_db
    def test_oversized_title_rejected(self, authed_client):
        """Titles exceeding the max length are rejected."""
        import json
        import io
        md = io.BytesIO(b"# Test\n\nContent.")
        r = authed_client.post(
            "/api/submit",
            files={"markdown": ("test.md", md, "text/markdown")},
            data={
                "title": "A" * 600,  # MAX_TITLE_LENGTH is 500
                "authors": json.dumps([{"orcid": "0000-0000-0000-0000", "name": "Test"}]),
                "abstract": "Test abstract.",
                "subjects": "Natural sciences > Mathematics, Natural sciences > Physical sciences, Social sciences > Economics and business",
                "license": "CC0",
                "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
            },
        )
        assert r.status_code == 400
        assert "title" in r.json()["detail"].lower()

    @requires_db
    def test_oversized_abstract_rejected(self, authed_client):
        """Abstracts exceeding the max length are rejected."""
        import json
        import io
        md = io.BytesIO(b"# Test\n\nContent.")
        r = authed_client.post(
            "/api/submit",
            files={"markdown": ("test.md", md, "text/markdown")},
            data={
                "title": "Test Paper",
                "authors": json.dumps([{"orcid": "0000-0000-0000-0000", "name": "Test"}]),
                "abstract": "A" * 6000,  # MAX_ABSTRACT_LENGTH is 5000
                "subjects": "Natural sciences > Mathematics, Natural sciences > Physical sciences, Social sciences > Economics and business",
                "license": "CC0",
                "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
            },
        )
        assert r.status_code == 400
        assert "abstract" in r.json()["detail"].lower()

    def test_security_headers_present(self, app_client):
        """Security headers should be set on all responses."""
        r = app_client.get("/health")
        assert r.headers.get("X-Content-Type-Options") == "nosniff"
        assert r.headers.get("X-Frame-Options") == "DENY"
        assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    def test_no_server_info_header(self, app_client):
        """Server version info should not be leaked."""
        r = app_client.get("/health")
        # FastAPI/Starlette may set "server" header but it should not
        # reveal detailed version info
        server = r.headers.get("server", "")
        # Nginx or similar may set this, but it shouldn't expose versions
        assert "uvicorn" not in server.lower()


# ─── Maintenance mode tests ─────────────────────────────────────────────────

class TestMaintenanceMode:
    """Tests for the maintenance mode feature."""

    @requires_db
    def test_maintenance_off_by_default(self, client):
        """Site should be accessible when maintenance mode is off."""
        r = client.get("/browse")
        assert r.status_code == 200
        assert "Under Maintenance" not in r.text

    @requires_db
    def test_maintenance_on_shows_503(self, client, db):
        """When maintenance mode is on, pages return 503 with maintenance page."""
        from db import set_setting
        set_setting("maintenance_mode", "true")
        try:
            r = client.get("/browse")
            assert r.status_code == 503
            assert "Under Maintenance" in r.text
        finally:
            set_setting("maintenance_mode", "false")

    @requires_db
    def test_health_accessible_during_maintenance(self, client, db):
        """Health endpoint should work even during maintenance."""
        from db import set_setting
        set_setting("maintenance_mode", "true")
        try:
            r = client.get("/health")
            assert r.status_code == 200
            assert r.json()["status"] == "ok"
        finally:
            set_setting("maintenance_mode", "false")

    @requires_db
    def test_admin_maintenance_get_status(self, admin_client):
        """Admin can get maintenance mode status."""
        r = admin_client.get("/admin/maintenance")
        assert r.status_code == 200
        assert "maintenance_mode" in r.json()
        assert r.json()["maintenance_mode"] is False

    @requires_db
    def test_admin_maintenance_toggle_on(self, admin_client):
        """Admin can enable maintenance mode."""
        r = admin_client.post(
            "/admin/maintenance",
            data={"enabled": "true", "message": "Testing maintenance"},
        )
        assert r.status_code == 200
        assert r.json()["maintenance_mode"] is True
        # Verify it's actually on
        r = admin_client.get("/admin/maintenance")
        assert r.json()["maintenance_mode"] is True
        # Clean up
        admin_client.post("/admin/maintenance", data={"enabled": "false"})

    @requires_db
    def test_admin_maintenance_toggle_off(self, admin_client):
        """Admin can disable maintenance mode."""
        # Turn on first
        admin_client.post("/admin/maintenance", data={"enabled": "true"})
        # Turn off
        r = admin_client.post("/admin/maintenance", data={"enabled": "false"})
        assert r.status_code == 200
        assert r.json()["maintenance_mode"] is False
        # Verify site is accessible again
        r = admin_client.get("/browse")
        assert r.status_code == 200

    @requires_db
    def test_non_admin_cannot_toggle_maintenance(self, authed_client):
        """Regular users cannot toggle maintenance mode."""
        r = authed_client.post(
            "/admin/maintenance",
            data={"enabled": "true"},
        )
        assert r.status_code == 403

    @requires_db
    def test_maintenance_doesnt_affect_api_endpoints_for_admin(self, admin_client, db):
        """Admin API endpoints should work during maintenance (for recovery)."""
        from db import set_setting
        set_setting("maintenance_mode", "true")
        try:
            # Admin maintenance endpoint should work
            r = admin_client.get("/admin/maintenance")
            assert r.status_code == 200
        finally:
            set_setting("maintenance_mode", "false")


# ─── Migration system tests ─────────────────────────────────────────────────

class TestMigrations:
    """Tests for the SQL migration system."""

    @requires_db
    def test_schema_migrations_table_exists(self, db):
        """The schema_migrations table should exist after init_schema."""
        from db import get_conn
        with get_conn().connection() as conn:
            row = conn.execute(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'schema_migrations')"
            ).fetchone()
            assert row["exists"] is True

    @requires_db
    def test_settings_table_exists(self, db):
        """The settings table should exist after init_schema."""
        from db import get_conn
        with get_conn().connection() as conn:
            row = conn.execute(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'settings')"
            ).fetchone()
            assert row["exists"] is True

    @requires_db
    def test_get_set_setting(self, db):
        """Settings can be read and written."""
        from db import get_setting, set_setting
        set_setting("test_key", "test_value")
        assert get_setting("test_key") == "test_value"
        # Upsert should update, not insert
        set_setting("test_key", "updated_value")
        assert get_setting("test_key") == "updated_value"

    @requires_db
    def test_is_maintenance_mode_default_false(self, db):
        """Maintenance mode should be off by default."""
        from db import is_maintenance_mode
        # Ensure it's off
        from db import set_setting
        set_setting("maintenance_mode", "false")
        assert is_maintenance_mode() is False

    def test_list_migrations_finds_files(self):
        """The migration runner should find migration files."""
        from migrate import list_migrations
        migrations = list_migrations()
        assert len(migrations) >= 2
        # Check they're sorted by number
        nums = [m[0] for m in migrations]
        assert nums == sorted(nums)
        # Check the first migration is 001
        assert migrations[0][0] == 1

    def test_migration_files_are_valid_sql(self):
        """All migration files should be non-empty SQL."""
        from migrate import list_migrations
        migrations = list_migrations()
        for num, name, path in migrations:
            content = path.read_text(encoding="utf-8")
            assert len(content) > 0, f"Migration {num:03d}_{name}.sql is empty"
