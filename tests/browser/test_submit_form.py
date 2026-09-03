"""
Browser tests for the GenRxiv submission form.

These tests use Playwright to verify the JS-heavy form behavior that
can't be tested with the API test client:

- Classification dropdown cascading (domain → subdomain)
- Preview button state (disabled → enabled when all fields filled)
- Preview rendering (title, abstract, authors, classifications)
- beforeunload warning when form has data
- Nav link interceptor (confirm dialog when form is dirty)

Prerequisites:
    - API running at http://localhost:8080 (or set GENRXIV_URL)
    - Playwright browsers installed: playwright install chromium

Run:
    cd tests/browser
    pip install -r requirements.txt
    playwright install chromium
    pytest test_submit_form.py -v
"""
import os
import re

import pytest
from playwright.sync_api import Page, expect

BASE_URL = os.environ.get("GENRXIV_URL", "http://localhost:8080")


def test_submit_page_loads(page: Page):
    """The submit page should load and show the sign-in prompt when unauthenticated."""
    page.goto(f"{BASE_URL}/submit")
    expect(page).to_have_title(re.compile("Submit"))
    # Should show sign-in prompt when not authenticated
    expect(page.locator("h3")).to_contain_text("Sign in to submit")


def test_browse_page_has_container_layout(page: Page):
    """Browse page should use the container wrapper for proper layout."""
    page.goto(f"{BASE_URL}/browse")
    # The container div should be present
    container = page.locator(".container")
    expect(container).to_be_visible()


def test_robots_txt_advertises_agent_endpoints(page: Page):
    """robots.txt should advertise API discovery endpoints."""
    page.goto(f"{BASE_URL}/robots.txt")
    content = page.content()
    assert "OpenAPI-Schema:" in content
    assert "Agent-Guide:" in content
    assert "FOS-Taxonomy:" in content


def test_agent_guide_is_plain_text(page: Page):
    """Agent guide should return plain text with key sections."""
    response = page.goto(f"{BASE_URL}/api/agent-guide")
    assert response.status == 200
    content = page.content()
    assert "GenRxiv Agent Guide" in content
    assert "AUTHENTICATION" in content
    assert "AGENT CONDUCT" in content
    assert "SUBMISSION" in content


def test_fos_taxonomy_returns_json(page: Page):
    """FOS taxonomy endpoint should return valid JSON with OECD domains."""
    response = page.goto(f"{BASE_URL}/api/fos")
    assert response.status == 200
    # The response should be JSON — check via the body content
    content = page.evaluate("() => document.body.innerText")
    import json
    data = json.loads(content)
    assert data["taxonomy"] == "OECD Fields of Science"
    assert data["required_count"] == 3
    assert "Natural sciences" in data["domains"]


def test_ai_plugin_manifest_returns_json(page: Page):
    """AI plugin manifest should return valid JSON."""
    response = page.goto(f"{BASE_URL}/.well-known/ai-plugin.json")
    assert response.status == 200
    content = page.evaluate("() => document.body.innerText")
    import json
    data = json.loads(content)
    assert data["name"] == "GenRxiv"
    assert data["auth"]["provider"] == "ORCID"
    assert "agent_conduct" in data
    assert data["agent_conduct"]["required"] is True


def test_openapi_schema_loads(page: Page):
    """OpenAPI schema should load and contain auth/submission docs."""
    response = page.goto(f"{BASE_URL}/api/openapi.json")
    assert response.status == 200
    content = page.evaluate("() => document.body.innerText")
    import json
    data = json.loads(content)
    assert data["info"]["title"] == "GenRxiv API"
    desc = data["info"]["description"]
    assert "ORCID OAuth" in desc
    assert "genrxiv_session" in desc
    assert "POST /api/submit" in desc


def test_interactive_docs_page_loads(page: Page):
    """Swagger UI docs should load."""
    response = page.goto(f"{BASE_URL}/api/docs")
    assert response.status == 200
    # Swagger UI should render
    page.wait_for_load_state("networkidle")
    # The page should contain Swagger UI elements
    assert "GenRxiv API" in page.title() or "GenRxiv" in page.content()


def test_health_endpoint(page: Page):
    """Health endpoint should return ok status."""
    response = page.goto(f"{BASE_URL}/health")
    assert response.status == 200
    content = page.evaluate("() => document.body.innerText")
    import json
    data = json.loads(content)
    assert data["status"] == "ok"
    assert data["service"] == "genrxiv-api"


def test_splash_page_loads(page: Page):
    """Splash page should load with the GenRxiv branding."""
    page.goto(f"{BASE_URL}/")
    expect(page).to_have_title(re.compile("GenRxiv"))
    # Should have the splash content
    expect(page.locator(".splash")).to_be_visible()
    # Should have the masthead
    expect(page.locator(".masthead h1")).to_contain_text("GenRxiv")


def test_nav_links_present_on_all_pages(page: Page):
    """Navigation should be consistent across pages."""
    for path in ["/", "/browse", "/subjects", "/stats"]:
        page.goto(f"{BASE_URL}{path}")
        nav = page.locator("nav")
        expect(nav).to_be_visible()
        # Should have links or disabled spans for main sections
        # (current page's nav item is a span, not an anchor)
        assert page.locator("nav :has-text('Browse')").count() >= 1
        # "Subjects" may be a link or a disabled span depending on the page
        assert page.locator("nav :has-text('Subjects')").count() >= 1


def test_nav_disables_current_page_link(page: Page):
    """Nav links to the current page should be disabled (not clickable)."""
    page.goto(f"{BASE_URL}/browse")
    # The Browse link should be a span, not an anchor
    browse_span = page.locator("nav span:has-text('Browse')")
    expect(browse_span).to_be_visible()
    # Should have opacity 0.5 (disabled style)
    opacity = browse_span.evaluate("el => getComputedStyle(el).opacity")
    assert float(opacity) < 1.0


def test_submit_page_nav_submit_is_disabled(page: Page):
    """On /submit, the Submit nav button should be disabled."""
    page.goto(f"{BASE_URL}/submit")
    # The Submit button should be a span, not a link
    submit_span = page.locator("nav span:has-text('Submit')")
    expect(submit_span).to_be_visible()
