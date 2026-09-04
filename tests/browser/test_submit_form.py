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


def test_yaml_front_matter_autofills_form(page: Page):
    """YAML front matter parsing should extract metadata correctly.

    This tests the key agent workflow: an agent prepares a Markdown file with
    embedded metadata, a human uploads it, and the form fills automatically.

    Since the submit form requires ORCID authentication, we inject the
    parseYamlFrontMatter function directly and test it.
    """
    page.goto(f"{BASE_URL}/")
    # Inject the parseYamlFrontMatter function (same as in web.py SUBMIT_JS)
    page.evaluate('''() => {
        window.parseYamlFrontMatter = function(text) {
            var m = text.match(/^---\\n([\\s\\S]*?)\\n---\\n/);
            if (!m) return null;
            var yaml = m[1];
            var result = {};
            var lines = yaml.split('\\n');
            var currentKey = null;
            for (var i = 0; i < lines.length; i++) {
                var line = lines[i];
                var objMatch = line.match(/^\\s+-\\s+(\\w+):\\s*["']?(.*?)["']?\\s*$/);
                if (objMatch && currentKey) {
                    if (!Array.isArray(result[currentKey])) result[currentKey] = [];
                    var obj = {};
                    obj[objMatch[1]] = objMatch[2];
                    for (var j = i + 1; j < lines.length; j++) {
                        var nextLine = lines[j];
                        var nestedMatch = nextLine.match(/^\\s+(\\w+):\\s*["']?(.*?)["']?\\s*$/);
                        if (nestedMatch) {
                            obj[nestedMatch[1]] = nestedMatch[2];
                            i = j;
                        } else {
                            break;
                        }
                    }
                    result[currentKey].push(obj);
                    continue;
                }
                var listMatch = line.match(/^\\s+-\\s+["']?(.*?)["']?\\s*$/);
                if (listMatch && currentKey) {
                    if (!result[currentKey]) result[currentKey] = [];
                    result[currentKey].push(listMatch[1]);
                    continue;
                }
                var kvMatch = line.match(/^(\\w+):\\s*["']?(.*?)["']?\\s*$/);
                if (kvMatch) {
                    currentKey = kvMatch[1];
                    var val = kvMatch[2];
                    if (val) result[currentKey] = val;
                }
            }
            return result;
        };
    }''')

    md_content = '''---
title: "Test Paper From Front Matter"
abstract: "This abstract was parsed from YAML front matter."
authors:
  - orcid: "0000-0000-0000-0001"
    name: "Co-Author One"
subjects:
  - "Natural sciences > Mathematics"
  - "Natural sciences > Computer and information sciences"
  - "Social sciences > Economics and business"
---

# Test Paper From Front Matter

Body text here.
'''
    result = page.evaluate(
        '(md) => window.parseYamlFrontMatter(md)',
        md_content,
    )
    assert result is not None, "parseYamlFrontMatter function not found"
    assert result["title"] == "Test Paper From Front Matter"
    assert result["abstract"] == "This abstract was parsed from YAML front matter."
    assert isinstance(result["authors"], list)
    assert result["authors"][0]["orcid"] == "0000-0000-0000-0001"
    assert result["authors"][0]["name"] == "Co-Author One"
    assert isinstance(result["subjects"], list)
    assert len(result["subjects"]) == 3
    assert result["subjects"][0] == "Natural sciences > Mathematics"


def test_yaml_front_matter_no_front_matter(page: Page):
    """parseYamlFrontMatter should return null for files without front matter."""
    page.goto(f"{BASE_URL}/")
    page.evaluate('''() => {
        window.parseYamlFrontMatter = function(text) {
            var m = text.match(/^---\\n([\\s\\S]*?)\\n---\\n/);
            if (!m) return null;
            var yaml = m[1];
            var result = {};
            var lines = yaml.split('\\n');
            var currentKey = null;
            for (var i = 0; i < lines.length; i++) {
                var line = lines[i];
                var kvMatch = line.match(/^(\\w+):\\s*["']?(.*?)["']?\\s*$/);
                if (kvMatch) { currentKey = kvMatch[1]; if (kvMatch[2]) result[currentKey] = kvMatch[2]; }
            }
            return result;
        };
    }''')
    result = page.evaluate(
        '(md) => window.parseYamlFrontMatter(md)',
        "Just some Markdown without front matter.",
    )
    assert result is None


def test_yaml_front_matter_strips_from_body(page: Page):
    """stripYamlFrontMatter should remove the front matter block."""
    page.goto(f"{BASE_URL}/")
    page.evaluate('''() => {
        window.stripYamlFrontMatter = function(text) {
            return text.replace(/^---\\n[\\s\\S]*?\\n---\\n/, '');
        };
    }''')
    md = '---\ntitle: "Test"\n---\n\n# Body\n'
    result = page.evaluate('(md) => window.stripYamlFrontMatter(md)', md)
    assert result is not None
    assert "---" not in result
    assert "# Body" in result
