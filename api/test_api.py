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


# ─── 9-11, 16-17. Articles / endorsements / keywords API ────────────────────

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


class TestKeywordsAPI:
    @requires_db
    def test_list_keywords_returns_keyword_list(self, client):
        r = client.get("/api/keywords")
        assert r.status_code == 200
        body = r.json()
        assert "keywords" in body
        keywords = {row["keyword"] for row in body["keywords"]}
        assert "AI" in keywords


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
    def test_keywords_page_returns_html(self, client):
        r = client.get("/keywords")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "Keywords" in r.text

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
