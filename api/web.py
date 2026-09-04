"""
GenRxiv API — web UI pages (HTML).

Simple server-rendered pages using Jinja2 templates:
- /submit — submission form
- /dashboard — author's submissions
- /admin — moderation queue and stats
- /browse — article listing
- /author/{orcid} — author profile page
- /subjects — subject cloud
- /code-of-conduct — code of conduct for authors and agents
"""
from datetime import datetime
import logging
from urllib.parse import quote

from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel

from config import config
from db import get_conn
from auth import get_current_author, require_author, require_admin, require_reviewer, _is_admin, _is_reviewer
from orcid_client import fetch_orcid_works_count

router = APIRouter()
logger = logging.getLogger(__name__)

# ─── OECD Fields of Science taxonomy ───────────────────────────────────────
# Used for structured subject classification on submissions.
# Authors must select 3 classifications from this taxonomy.

OECD_FOS = {
    "Natural sciences": [
        "Mathematics", "Computer and information sciences", "Physical sciences",
        "Chemical sciences", "Earth and related environmental sciences",
        "Biological sciences", "Other natural sciences",
    ],
    "Engineering and technology": [
        "Civil engineering", "Electrical, electronic, information engineering",
        "Mechanical engineering", "Chemical engineering",
        "Materials engineering", "Medical engineering",
        "Environmental engineering", "Environmental biotechnology",
        "Industrial biotechnology", "Nano-technology",
        "Other engineering and technologies",
    ],
    "Medical and health sciences": [
        "Basic medicine", "Clinical medicine", "Health sciences",
        "Medical biotechnology", "Other medical sciences",
    ],
    "Agricultural and veterinary sciences": [
        "Agriculture, forestry, and fisheries", "Animal and dairy science",
        "Veterinary science", "Agricultural biotechnology",
        "Other agricultural sciences",
    ],
    "Social sciences": [
        "Psychology and cognitive sciences", "Economics and business",
        "Education", "Sociology", "Law", "Political science",
        "Social and economic geography", "Media and communications",
        "Other social sciences",
    ],
    "Humanities and the arts": [
        "History and archaeology", "Languages and literature",
        "Philosophy, ethics, and religion", "Arts (arts, history of arts, performing arts, music)",
        "Other humanities",
    ],
}


def _oecd_select_html(selected: list[str] = None) -> str:
    """Build HTML for the OECD FOS multi-select (3 required)."""
    selected = selected or []
    options = ""
    for category, fields in OECD_FOS.items():
        options += f'<optgroup label="{category}">\n'
        for field in fields:
            # Use "Category > Field" as the value for clarity
            value = f"{category} > {field}"
            is_selected = " selected" if value in selected else ""
            options += f'<option value="{value}"{is_selected}>{field}</option>\n'
        options += "</optgroup>\n"
    return f'<select name="subjects" multiple size="10" required style="width:100%;padding:0.6rem;border:1px solid var(--border);border-radius:4px;font-size:1rem;font-family:inherit">{options}</select>'


# ─── Shared template helpers ───────────────────────────────────────────────

PAGE_CSS = """
:root {
    --paper: #EDEAE2;
    --paper-warm: #F5F2EB;
    --ink: #1B1E27;
    --ink-soft: #4A4A45;
    --muted: #8A8578;
    --rule: #C9C3B5;
    --border: #C9C3B5;
    --accent: #2F5CFF;
    --accent-soft: #E4E9FF;
    --accent-dim: #6B8AFA;
    --card: #FFFFFF;
    --badge-ai: #6B4FBB;
    --badge-ai-soft: #EEEAF7;
    --cobalt: #2F5CFF;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, sans-serif;
    color: var(--ink);
    background: var(--paper);
    line-height: 1.7;
    font-size: 1.05rem;
    -webkit-font-smoothing: antialiased;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
h1, h2, h3, h4 { font-family: 'Fraunces', Georgia, serif; line-height: 1.3; }
.container { max-width: 52rem; margin: 0 auto; padding: 2rem 1.5rem; }
.btn {
    display: inline-block;
    padding: 0.5rem 1.2rem;
    border: 1px solid var(--accent);
    border-radius: 4px;
    color: var(--accent);
    font-size: 0.95rem;
    cursor: pointer;
    background: transparent;
    transition: all 0.15s;
}
.btn:hover { background: var(--accent); color: #fff; text-decoration: none; }
.btn-primary { background: var(--accent); color: #fff; }
.btn-primary:hover { background: #1a40d0; }
.btn-danger { border-color: #c0392b; color: #c0392b; }
.btn-danger:hover { background: #c0392b; color: #fff; }
.card {
    background: #fff;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1.5rem;
    margin-bottom: 1rem;
}
.card h2 { font-size: 1.3rem; margin-bottom: 0.5rem; }
.card h2 a { color: var(--ink); }
.card h2 a:hover { color: var(--cobalt); }
.card .meta { font-size: 0.85rem; color: #888; margin-top: 0.5rem; }
.card .abstract { font-size: 0.95rem; color: #555; margin-top: 0.5rem; }
.card .subjects { margin-top: 0.5rem; }
.card .subjects a {
    font-size: 0.8rem;
    background: var(--muted);
    padding: 0.15rem 0.5rem;
    border-radius: 3px;
    margin-right: 0.3rem;
    color: var(--ink);
}
.form-group { margin-bottom: 1rem; }
.form-group label { display: block; font-weight: 600; margin-bottom: 0.3rem; font-size: 0.9rem; }
.form-group input, .form-group textarea, .form-group select {
    width: 100%;
    padding: 0.6rem;
    border: 1px solid var(--border);
    border-radius: 4px;
    font-size: 1rem;
    font-family: inherit;
    background: #fff;
}
.form-group textarea { min-height: 6rem; resize: vertical; }
.form-group .hint { font-size: 0.8rem; color: #888; margin-top: 0.2rem; }
.form-group input[type="file"] { padding: 0.3rem; }
.status-badge {
    display: inline-block;
    padding: 0.15rem 0.6rem;
    border-radius: 3px;
    font-size: 0.8rem;
    font-weight: 600;
}
.status-pending { background: #fff3cd; color: #856404; }
.status-published { background: #d4edda; color: #155724; }
.status-rejected { background: #f8d7da; color: #721c24; }
.stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr)); gap: 1rem; margin-bottom: 2rem; }
.stat-card { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 1.2rem; text-align: center; }
.stat-card .num { font-size: 2rem; font-family: 'Fraunces', Georgia, serif; font-weight: 700; }
.stat-card .label { font-size: 0.85rem; color: #888; margin-top: 0.3rem; }
.subject-cloud { display: flex; flex-wrap: wrap; gap: 0.5rem; }
.subject-cloud a {
    background: #fff;
    border: 1px solid var(--border);
    padding: 0.3rem 0.8rem;
    border-radius: 4px;
    color: var(--ink);
}
.subject-cloud a:hover { border-color: var(--cobalt); color: var(--cobalt); }
.empty { text-align: center; padding: 3rem; color: #888; }
.empty h3 { font-size: 1.2rem; margin-bottom: 0.5rem; }
.error { background: #f8d7da; color: #721c24; padding: 0.8rem 1rem; border-radius: 4px; margin-bottom: 1rem; }
.success { background: #d4edda; color: #155724; padding: 0.8rem 1rem; border-radius: 4px; margin-bottom: 1rem; }
.author-info { display: flex; gap: 1rem; align-items: center; margin-bottom: 1.5rem; }
.author-info .name { font-size: 1.3rem; font-family: 'Fraunces', Georgia, serif; }
.author-info .orcid { font-size: 0.85rem; color: var(--cobalt); }
.author-info .orcid a { color: var(--cobalt); }
.pagination { display: flex; gap: 0.5rem; justify-content: center; margin-top: 2rem; }
.pagination a, .pagination span {
    padding: 0.4rem 0.8rem;
    border: 1px solid var(--border);
    border-radius: 4px;
    font-size: 0.9rem;
}
.pagination .current { background: var(--cobalt); color: #fff; border-color: var(--cobalt); }
footer { border-top: 1px solid var(--border); padding: 1.5rem; text-align: center; font-size: 0.85rem; color: #888; margin-top: 3rem; }
"""


def _header_html(author: dict | None, current_path: str = "") -> str:
    """Render the site header with nav — matches the splash page top nav.

    current_path is used to disable nav links that point to the current page,
    preventing accidental page reloads that would lose form state.
    """
    def nav_link(href: str, label: str, style: str = "color:var(--ink);text-decoration:none") -> str:
        if current_path == href:
            return f'<span style="{style};opacity:0.5;cursor:default">{label}</span>'
        return f'<a href="{href}" style="{style}">{label}</a>'

    if author:
        submit_link = nav_link(
            "/submit", "Submit",
            "display:inline-block;padding:0.3rem 0.9rem;background:var(--accent);color:#fff;border-radius:4px;text-decoration:none;font-size:0.85rem",
        )
        # Show moderation link for reviewers and admins (DB role, ORCID, or GitHub)
        mod_link = nav_link("/admin", "Moderation") if _is_reviewer(author) else ""
        auth_area = (
            f'{mod_link}'
            f'{nav_link("/dashboard", "My Submissions")}'
            f'{nav_link("/profile", author["name"])}'
            f'{submit_link}'
            f'<form method="post" action="/auth/logout" style="display:inline">'
            f'<button type="submit" style="background:none;border:none;color:var(--ink);cursor:pointer;font-size:0.85rem;text-decoration:underline">Sign out</button>'
            f'</form>'
        )
    else:
        submit_link = nav_link(
            "/submit", "Submit",
            "display:inline-block;padding:0.3rem 0.9rem;background:var(--accent);color:#fff;border-radius:4px;text-decoration:none;font-size:0.85rem",
        )
        auth_area = (
            f'<a href="/auth/orcid?redirect=/dashboard" style="color:var(--ink);text-decoration:none">Sign in with ORCID</a>'
            + f'{submit_link}'
        )
    return f"""<nav style="display:flex;justify-content:space-between;align-items:center;padding:0.6rem 1.5rem;border-bottom:1px solid var(--rule);font-size:0.9rem">
<div style="display:flex;gap:1.2rem;align-items:center">
<a href="/" style="font-weight:600;color:var(--accent);text-decoration:none">{config.site_name}</a>
{nav_link("/browse", "Browse")}
{nav_link("/subjects", "Subjects")}
{nav_link("/stats", "Stats")}
<a href="/feed.xml" style="color:var(--ink);text-decoration:none">Feed</a>
</div>
<div style="display:flex;gap:0.8rem;align-items:center">
{auth_area}
</div>
</nav>"""


def _footer_html() -> str:
    reviewer_note = ""
    if config.github_client_id:
        reviewer_note = f'<p style="font-size:0.85rem;color:var(--ink-soft)">Interested in helping review submissions? <a href="mailto:{config.contact_email if hasattr(config, "contact_email") and config.contact_email else "admin@genrxiv.org"}">Get in touch</a>. Already a reviewer? <a href="/auth/github?redirect=/admin">Log in with GitHub</a>.</p>'
    return f"""<footer>
<p>{config.site_name} &mdash; An open archive for AI-generated research.</p>
<p><a href="/api/articles">API</a> &middot; <a href="/oai?verb=Identify">OAI-PMH</a> &middot; <a href="/feed.xml">Feed</a> &middot; <a href="/sitemap.xml">Sitemap</a> &middot; <a href="/robots.txt">robots.txt</a> &middot; <a href="/code-of-conduct">Code of Conduct</a></p>
{reviewer_note}
</footer>"""


def _asset_version() -> str:
    """Cache-busting version string for static assets.

    Uses the mtime of this file so it changes whenever the code is
    updated and the container is rebuilt. This forces Cloudflare and
    browsers to fetch fresh CSS/JS instead of serving stale caches.
    """
    import os
    try:
        return str(int(os.path.getmtime(__file__)))
    except OSError:
        return "1"


def _page(
    title: str,
    body: str,
    author: dict | None = None,
    extra_css: str = "",
    extra_js: str = "",
    extra_head: str = "",
    raw_title: bool = False,
    wrap_container: bool = True,
    current_path: str = "",
    extra_css_files: list[str] | None = None,
    extra_js_files: list[str] | None = None,
) -> HTMLResponse:
    """Render a full HTML page."""
    page_title = title if raw_title else f"{title} &middot; {config.site_name}"
    if wrap_container:
        body = f'<div class="container">\n{body}\n</div>'
    v = _asset_version()
    css_links = ""
    if extra_css_files:
        css_links = "\n".join(f'<link rel="stylesheet" href="{f}?v={v}">' for f in extra_css_files)
    js_links = ""
    if extra_js_files:
        js_links = "\n".join(f'<script defer src="{f}?v={v}"></script>' for f in extra_js_files)
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{page_title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,500;0,9..144,600;1,9..144,400&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" href="/mark.svg" type="image/svg+xml">
<link rel="icon" href="/favicon-32.png" type="image/png" sizes="32x32">
<link rel="icon" href="/favicon-16.png" type="image/png" sizes="16x16">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="alternate" type="application/atom+xml" title="{config.site_name} — Recent Articles" href="/feed.xml">
<link rel="stylesheet" href="/css/page.css?v={v}">
{css_links}
{f"<style>{extra_css}</style>" if extra_css else ""}
{extra_head}
</head>
<body>
{_header_html(author, current_path)}
{body}
{_footer_html()}
{js_links}
{f"<script>{extra_js}</script>" if extra_js else ""}
</body>
</html>"""
    return HTMLResponse(html)


def _format_date(dt) -> str:
    if not dt:
        return ""
    if isinstance(dt, str):
        return dt[:10]
    return dt.strftime("%Y-%m-%d")


def _article_card(article: dict) -> str:
    """Render an article card in the unified paper-card style."""
    from oecd_codes import classification_tag

    ark = article.get("ark", "")
    title = article.get("title", "Untitled")
    abstract = article.get("abstract") or ""
    subjects = article.get("subjects", [])
    published = _format_date(article.get("published_at"))
    is_retraction = article.get("is_retraction", False)
    status = article.get("status", "published")

    tags_html = "".join(classification_tag(s) for s in subjects) if subjects else ""
    authors_html = ""
    if "authors" in article and article["authors"]:
        authors_html = ", ".join(
            f'<a href="/author/{a["orcid"]}">{a["name"]}</a>' for a in article["authors"]
        )
    elif "author_names" in article and article["author_names"]:
        authors_html = article["author_names"]

    # Status indicator (only show if not published or is a retraction)
    status_badge = ""
    if status != "published":
        status_badge = f'<span class="badge badge-status">{status}</span>'
    if is_retraction:
        status_badge += '<span class="badge" style="background:#fdf0f0;color:#c0392b">retraction</span>'

    return f"""<div class="paper-card">
<div class="paper-meta">{ark} &middot; posted {published}</div>
<h2><a href="/article/{ark}">{title}</a></h2>
<div class="paper-authors">{authors_html}</div>
{f'<p class="paper-abstract">{abstract}</p>' if abstract else ''}
{f'<div class="paper-badges">{status_badge}</div>' if status_badge else ''}
{f'<div class="paper-tags">{tags_html}</div>' if tags_html else ''}
</div>"""


# ─── ORCID lookup for co-author entry ──────────────────────────────────────

@router.get("/api/orcid-lookup/{orcid}", include_in_schema=False)
def orcid_lookup(orcid: str, request: Request):
    """Look up an ORCID iD and return the name if known.

    Checks the local authors table first, then falls back to the ORCID
    public API. Returns {orcid, name, source} or 404 if not found.
    """
    # Normalize the ORCID
    orcid = orcid.strip()
    if len(orcid) == 16 and "-" not in orcid:
        orcid = f"{orcid[0:4]}-{orcid[4:8]}-{orcid[8:12]}-{orcid[12:16]}"

    # Check local DB first
    with get_conn().connection() as conn:
        row = conn.execute(
            "SELECT name, affiliation FROM authors WHERE orcid = %s", (orcid,)
        ).fetchone()
    if row:
        return {"orcid": orcid, "name": row["name"], "affiliation": row.get("affiliation"), "source": "local"}

    # Fall back to ORCID public API
    try:
        import httpx2 as httpx
        with httpx.Client(timeout=10) as client:
            r = client.get(
                f"{config.orcid_api_url}/{orcid}/person",
                headers={"Accept": "application/json"},
            )
            if r.status_code == 200:
                data = r.json()
                name_obj = data.get("name", {})
                given = name_obj.get("given-names", {}).get("value", "")
                family = name_obj.get("family-name", {}).get("value", "")
                name = f"{given} {family}".strip()
                if name:
                    return {"orcid": orcid, "name": name, "affiliation": None, "source": "orcid"}
    except Exception:
        pass

    raise HTTPException(404, f"ORCID {orcid} not found")


# ─── Splash page ───────────────────────────────────────────────────────────

SPLASH_CSS = """
.splash { max-width: 720px; margin: 0 auto; padding: 3rem 1.5rem 4rem; }
@media (max-width: 520px) { .splash { padding: 2rem 1.25rem 3rem; } }
.masthead { animation: rise 0.6s ease-out both; }
@keyframes rise { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
.masthead h1 { font-family: 'Fraunces', serif; font-weight: 500; font-size: clamp(2.6rem, 8vw, 3.6rem); letter-spacing: -0.01em; margin: 0; }
.masthead .tagline { font-family: 'Fraunces', serif; font-style: italic; font-weight: 400; font-size: 1.1rem; color: var(--ink-soft); margin: 0.35rem 0 0; }
.splash .rule { border: none; border-top: 1px solid var(--rule); margin: 1.6rem 0 2.6rem; }
.splash .status { font-size: 0.8rem; letter-spacing: 0.02em; color: var(--muted); margin: 0 0 2.6rem; }
.splash .status .dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: var(--accent); margin-right: 0.5em; animation: pulse 2s ease-in-out infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
.splash p { font-size: 1.02rem; color: var(--ink); max-width: 34em; }
.splash h2 { font-family: 'Fraunces', serif; font-weight: 500; font-size: 1.3rem; margin: 2.8rem 0 0.6rem; }
.splash h3 { font-family: 'IBM Plex Sans', sans-serif; font-weight: 600; font-size: 0.95rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin: 2.6rem 0 1rem; }
.subjects { display: flex; flex-wrap: wrap; gap: 0.5rem; margin: 1rem 0 0; }
.subject-tag { font-size: 0.85rem; font-weight: 500; padding: 0.35rem 0.8rem; background: var(--paper-warm); border: 1px solid var(--rule); border-radius: 999px; color: var(--ink-soft); }
.paper-card { background: var(--card); border: 1px solid var(--rule); border-radius: 6px; padding: 1.4rem 1.5rem; margin: 1rem 0; }
.paper-card .paper-meta { font-family: 'IBM Plex Mono', monospace; font-size: 0.78rem; color: var(--muted); margin-bottom: 0.5rem; }
.paper-card h4 { font-family: 'Fraunces', serif; font-weight: 500; font-size: 1.15rem; margin: 0 0 0.4rem; line-height: 1.3; }
.paper-card .paper-authors { font-size: 0.9rem; color: var(--ink-soft); margin: 0 0 0.6rem; }
.paper-card .paper-abstract { font-size: 0.92rem; color: var(--ink-soft); margin: 0 0 0.8rem; }
.paper-card .paper-badges { display: flex; flex-wrap: wrap; gap: 0.4rem; }
.badge { font-size: 0.75rem; font-weight: 500; padding: 0.2rem 0.6rem; border-radius: 3px; }
.badge-ai { background: var(--badge-ai-soft); color: var(--badge-ai); }
.badge-format { background: var(--accent-soft); color: var(--accent); }
.badge-status { background: var(--paper-warm); color: var(--muted); border: 1px solid var(--rule); }
.standards { margin: 1rem 0; padding: 0; }
.standards li { font-size: 0.95rem; color: var(--ink); padding: 0.5rem 0 0.5rem 1.6rem; position: relative; list-style: none; }
.standards li::before { content: "\\2192"; position: absolute; left: 0; color: var(--accent); font-weight: 600; }
.splash form { margin-top: 1.2rem; }
.splash label.field-label { display: block; font-size: 0.92rem; color: var(--ink-soft); margin-bottom: 0.5rem; }
.splash input[type="email"] { width: 100%; font-family: 'IBM Plex Sans', sans-serif; font-size: 1rem; padding: 0.75rem 0.85rem; border: 1px solid var(--rule); background: #fff; color: var(--ink); border-radius: 3px; }
.splash input[type="email"]:focus { outline: 2px solid var(--accent); outline-offset: 1px; border-color: var(--accent); }
.checkbox-row { display: flex; align-items: flex-start; gap: 0.6rem; margin-top: 1rem; }
.checkbox-row input[type="checkbox"] { margin-top: 0.2rem; width: 16px; height: 16px; accent-color: var(--accent); flex-shrink: 0; }
.checkbox-row label { font-size: 0.95rem; color: var(--ink); }
.splash button[type="submit"] { margin-top: 1.4rem; font-family: 'IBM Plex Sans', sans-serif; font-weight: 500; font-size: 0.95rem; background: var(--ink); color: var(--paper); border: none; padding: 0.75rem 1.5rem; border-radius: 3px; cursor: pointer; transition: background 0.15s ease; }
.splash button[type="submit"]:hover { background: var(--accent); }
.splash button[type="submit"]:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.confirm { display: none; margin-top: 1rem; padding: 0.85rem 1rem; background: var(--accent-soft); border-left: 3px solid var(--accent); font-size: 0.92rem; color: var(--ink); }
.confirm.error { background: #FDE8E8; border-left-color: #C53030; }
.roadmap { margin: 1rem 0; }
.roadmap-item { display: flex; gap: 1rem; padding: 0.6rem 0; border-bottom: 1px solid var(--rule); }
.roadmap-item:last-child { border-bottom: none; }
.roadmap-status { font-family: 'IBM Plex Mono', monospace; font-size: 0.78rem; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em; min-width: 70px; padding-top: 0.15rem; }
.roadmap-status.done { color: #2D7A3E; }
.roadmap-status.active { color: var(--accent); }
.roadmap-status.planned { color: var(--muted); }
.roadmap-label { font-size: 0.95rem; color: var(--ink); }
.support { margin-top: 2.6rem; padding-top: 1.8rem; border-top: 1px solid var(--rule); }
.support p { color: var(--ink-soft); font-size: 0.96rem; }
.support-links { display: flex; flex-wrap: wrap; gap: 1.2rem; margin-top: 0.8rem; }
.support-link { display: inline-block; font-size: 0.95rem; font-weight: 500; color: var(--accent); text-decoration: none; border-bottom: 1px solid var(--accent); padding-bottom: 1px; }
.support-link:hover { color: var(--ink); border-color: var(--ink); }
.github-link { margin-top: 1.6rem; font-size: 0.9rem; color: var(--muted); }
.github-link a { color: var(--ink-soft); text-decoration: none; border-bottom: 1px solid var(--rule); }
.github-link a:hover { color: var(--accent); border-color: var(--accent); }
.splash footer { margin-top: 3.5rem; font-size: 0.8rem; color: var(--muted); }
"""

SPLASH_JS = """
const form = document.getElementById('interest-form');
const confirmMsg = document.getElementById('confirm-message');
form.addEventListener('submit', async function (e) {
    e.preventDefault();
    const email = document.getElementById('email').value;
    const notify = document.getElementById('notify').checked;
    confirmMsg.classList.remove('error');
    confirmMsg.style.display = 'block';
    confirmMsg.textContent = 'Sending\\u2026';
    try {
        const resp = await fetch('/api/signup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email: email, notify_on_launch: notify }),
        });
        if (resp.ok) {
            confirmMsg.textContent = 'Thanks \\u2014 we\\'ll be in touch.';
            form.reset();
        } else {
            confirmMsg.classList.add('error');
            confirmMsg.textContent = 'Something went wrong. Please try again.';
        }
    } catch (err) {
        confirmMsg.classList.add('error');
        confirmMsg.textContent = 'Network error. Please try again.';
    }
});
"""


@router.get("/", include_in_schema=False, response_class=HTMLResponse)
def splash_page(request: Request):
    """Splash page — served through FastAPI so it shares the nav with all pages."""
    author = get_current_author(request)
    body = """
<div class="splash">
    <div class="heartbeat-banner">
        <span class="heartbeat-dot"></span>
        Now accepting submissions
    </div>
    <div class="masthead">
        <h1>GenRxiv</h1>
        <p class="tagline">An open archive for AI-generated research</p>
        <div style="margin-top:1rem;display:flex;gap:0.8rem;flex-wrap:wrap">
            <a href="/browse" style="display:inline-block;padding:0.5rem 1.2rem;border:1px solid var(--accent);border-radius:4px;color:var(--accent);font-size:0.95rem;text-decoration:none">Browse articles</a>
            <a href="/submit" style="display:inline-block;padding:0.5rem 1.2rem;background:var(--accent);color:#fff;border:1px solid var(--accent);border-radius:4px;font-size:0.95rem;text-decoration:none">Submit a paper</a>
            <a href="/feed.xml" style="display:inline-block;padding:0.5rem 1.2rem;border:1px solid var(--rule);border-radius:4px;color:var(--ink);font-size:0.95rem;text-decoration:none">RSS feed</a>
        </div>
    </div>

    <hr class="rule">

    <p>
        GenRxiv is a preprint archive for research substantially generated or
        co-generated by AI, submitted in Markdown and openly available to
        human and machine readers alike. We're building this in the open, and
        we'd love the community to get involved &mdash; whether by submitting
        research, helping review submissions, or contributing to the platform
        itself.
    </p>

    <h3>Subject areas</h3>
    <p style="margin-bottom:0.75rem;color:var(--ink-soft);font-size:0.9rem">
        Authors classify their work using the OECD Fields of Science taxonomy.
        Each paper is tagged with 3 subcategories across these domains:
    </p>
    <div class="subjects" style="display:flex;flex-wrap:wrap;gap:0.4rem">
        <span class="oecd-tag" style="color:#2F5CFF;background:#E4E9FF;border-color:#2F5CFF">N &middot; Natural sciences</span>
        <span class="oecd-tag" style="color:#E67E22;background:#FDF0E0;border-color:#E67E22">E &middot; Engineering & technology</span>
        <span class="oecd-tag" style="color:#E74C3C;background:#FDEAEA;border-color:#E74C3C">M &middot; Medical & health</span>
        <span class="oecd-tag" style="color:#27AE60;background:#E8F8F0;border-color:#27AE60">A &middot; Agricultural & veterinary</span>
        <span class="oecd-tag" style="color:#9B59B6;background:#F4ECF7;border-color:#9B59B6">S &middot; Social sciences</span>
        <span class="oecd-tag" style="color:#16A085;background:#E0F5F1;border-color:#16A085">H &middot; Humanities & arts</span>
    </div>

    <h3>What a GenRxiv preprint looks like</h3>
    <div class="paper-card">
        <div class="paper-meta">ark:99999/genrxiv-2026-00001 &middot; posted 2026-01-15</div>
        <h4>Emergent Symbolic Reasoning in Multi-Agent LLM Systems Under Constrained Communication Bandwidth</h4>
        <p class="paper-authors">A. Chen, R. Okafor, with assistance from Claude 3.5 (Anthropic)</p>
        <p class="paper-abstract">
            We demonstrate that groups of large language models, when restricted to
            low-bandwidth symbolic channels, spontaneously develop compositional
            protocols resembling human mathematical notation. We characterize the
            conditions under which this emergence occurs and propose a framework&hellip;
        </p>
        <div class="paper-tags">
            <span class="oecd-tag" style="color:#2F5CFF;background:#E4E9FF;border-color:#2F5CFF" title="Natural sciences > Computer and information sciences">N&middot;CS</span>
            <span class="oecd-tag" style="color:#9B59B6;background:#F4ECF7;border-color:#9B59B6" title="Social sciences > Psychology and cognitive sciences">S&middot;PSYCH</span>
            <span class="oecd-tag" style="color:#E67E22;background:#FDF0E0;border-color:#E67E22" title="Engineering and technology > Electrical, electronic, information engineering">E&middot;EE</span>
        </div>
    </div>

    <h3>Submission standards</h3>
    <p>
        Every submission comes with a simple commitment: the author has
        reviewed the work and checked it for accuracy, whether AI was
        involved or not. That's it &mdash; no separate disclosure required,
        no paperwork about what the AI did. The responsibility is the same
        regardless of how the work was produced.
    </p>
    <p>
        Beyond that: submit in Markdown, attribute authorship to humans
        with an ORCID iD, and license the work openly. Point your AI agent
        to <a href="https://genrxiv.org">genrxiv.org</a> and tell it to
        discover how to prepare your manuscript for submission &mdash; the
        site exposes a plain-text
        <a href="/api/agent-guide">agent guide</a> with everything it needs.
    </p>

    <h2>Get involved</h2>
    <p>
        Leave your email if you'd like to help shape GenRxiv &mdash; as an early
        contributor, reviewer, or just a second pair of eyes.
    </p>

    <form id="interest-form">
        <label class="field-label" for="email">Email</label>
        <input type="email" id="email" name="email" placeholder="you@example.com" required>
        <button type="submit">Send</button>
        <div class="confirm" id="confirm-message">Thanks &mdash; we'll be in touch.</div>
    </form>

    <div class="support">
        <p>
            GenRxiv is self-hosted and self-funded. If you'd like to help cover
            hosting and infrastructure costs as we grow, contributions are
            welcome.
        </p>
        <div class="support-links">
            <a class="support-link" href="https://github.com/sponsors/GenRxiv">GitHub Sponsors &rarr;</a>
            <a class="support-link" href="https://opencollective.com/genrxiv">Open Collective &rarr;</a>
        </div>
    </div>

    <p class="github-link">
        We're building in the open. Watch the repo: <a href="https://github.com/GenRxiv/genrxiv">github.com/GenRxiv/genrxiv</a>
    </p>

    <footer>GenRxiv &middot; est. 2026</footer>
</div>
"""
    return _page(
        "GenRxiv — an open archive for AI-generated research",
        body,
        author,
        extra_css_files=["/css/splash.css"],
        extra_js_files=["/js/splash.js"],
        raw_title=True,
        wrap_container=False,
        extra_head='''<meta name="description" content="GenRxiv is a preprint archive for AI-generated research. Submissions are Markdown, authors are identified by ORCID, and all papers are CC0.">
<meta property="og:type" content="website">
<meta property="og:title" content="GenRxiv — an open archive for AI-generated research">
<meta property="og:description" content="A preprint archive for research substantially generated or co-generated by AI. Submissions are Markdown, authors are identified by ORCID, and all papers are CC0.">
<meta property="og:url" content="https://genrxiv.org/">
<meta property="og:site_name" content="GenRxiv">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="GenRxiv — an open archive for AI-generated research">
<meta name="twitter:description" content="A preprint archive for AI-generated research. Markdown submissions, ORCID authors, CC0 license.">
<link rel="canonical" href="https://genrxiv.org/">''',
    )


# ─── Browse page ───────────────────────────────────────────────────────────

@router.get("/browse", include_in_schema=False, response_class=HTMLResponse)
def browse_page(
    request: Request,
    page: int = 1,
    per_page: int = 20,
    q: str = "",
    sort: str = "recent",
):
    """Browse published articles."""
    author = get_current_author(request)
    offset = (page - 1) * per_page

    # Determine sort order
    if sort == "established":
        order_clause = "COALESCE(MAX(au.orcid_works_count), 0) DESC, a.published_at DESC"
    else:
        order_clause = "a.published_at DESC"

    with get_conn().connection() as conn:
        if q:
            rows = conn.execute(
                f"""SELECT a.id, a.ark, a.title, a.abstract, a.subjects, a.published_at,
                          string_agg(au.name, ', ' ORDER BY aa."order") as author_names,
                          COALESCE(MAX(au.orcid_works_count), 0) as max_works
                   FROM articles a
                   LEFT JOIN article_authors aa ON a.id = aa.article_id
                   LEFT JOIN authors au ON aa.author_id = au.id
                   WHERE a.status = 'published'
                     AND (a.title ILIKE %s OR a.abstract ILIKE %s)
                   GROUP BY a.id
                   ORDER BY {order_clause} LIMIT %s OFFSET %s""",
                (f"%{q}%", f"%{q}%", per_page, offset),
            ).fetchall()
            total = conn.execute(
                """SELECT COUNT(*) as c FROM articles
                   WHERE status = 'published'
                     AND (title ILIKE %s OR abstract ILIKE %s)""",
                (f"%{q}%", f"%{q}%"),
            ).fetchone()["c"]
        else:
            rows = conn.execute(
                f"""SELECT a.id, a.ark, a.title, a.abstract, a.subjects, a.published_at,
                          string_agg(au.name, ', ' ORDER BY aa."order") as author_names,
                          COALESCE(MAX(au.orcid_works_count), 0) as max_works
                   FROM articles a
                   LEFT JOIN article_authors aa ON a.id = aa.article_id
                   LEFT JOIN authors au ON aa.author_id = au.id
                   WHERE a.status = 'published'
                   GROUP BY a.id
                   ORDER BY {order_clause} LIMIT %s OFFSET %s""",
                (per_page, offset),
            ).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) as c FROM articles WHERE status = 'published'"
            ).fetchone()["c"]

    cards = "".join(_article_card(r) for r in rows) if rows else ""
    if not cards:
        cards = '<div class="empty"><h3>No articles yet</h3><p>Be the first to submit.</p></div>'

    search_box = f"""
    <form method="get" action="/browse" style="margin-bottom:1.5rem">
        <input type="text" name="q" value="{q}" placeholder="Search articles..." style="width:60%;padding:0.5rem;border:1px solid var(--border);border-radius:4px;font-size:1rem">
        <button type="submit" class="btn">Search</button>
    </form>"""

    # Sort links
    sort_q = f"&q={quote(q)}" if q else ""
    sort_links = f"""
    <div style="margin-bottom:1.5rem;font-size:0.9rem">
        Sort by:
        {'<strong>Most recent</strong>' if sort == 'recent' else f'<a href="/browse?page=1{sort_q}&sort=recent">Most recent</a>'}
        &middot;
        {'<strong>Established authors</strong>' if sort == 'established' else f'<a href="/browse?page=1{sort_q}&sort=established">Established authors</a>'}
    </div>"""

    # Update pagination to include sort
    pages = (total + per_page - 1) // per_page
    pagination = ""
    if pages > 1:
        parts = []
        for p in range(1, pages + 1):
            if p == page:
                parts.append(f'<span class="current">{p}</span>')
            else:
                qs = f"?page={p}" + (f"&q={quote(q)}" if q else "") + (f"&sort={sort}" if sort != "recent" else "")
                parts.append(f'<a href="/browse{qs}">{p}</a>')
        pagination = f'<div class="pagination">{"".join(parts)}</div>'

    body = f"""
    <h1>Browse Articles</h1>
    <p style="color:#888;margin-bottom:1.5rem">{total} published article{'s' if total != 1 else ''}</p>
    {search_box}
    {sort_links}
    {cards}
    {pagination}
    """
    return _page("Browse", body, author, current_path="/browse")


# ─── Subjects page ─────────────────────────────────────────────────────────

@router.get("/subjects", include_in_schema=False, response_class=HTMLResponse)
def subjects_page(request: Request):
    """Subject cloud."""
    author = get_current_author(request)
    with get_conn().connection() as conn:
        rows = conn.execute(
            """SELECT subject, COUNT(*) as count
               FROM articles, unnest(subjects) AS subject
               WHERE status = 'published'
               GROUP BY subject
               ORDER BY count DESC, subject ASC""",
        ).fetchall()

    if not rows:
        body = '<div class="empty"><h3>No subjects yet</h3><p>Subjects appear once articles are published.</p></div>'
    else:
        from oecd_codes import classification_tag
        links = []
        for r in rows:
            tag = classification_tag(r["subject"])
            links.append(
                f'<a href="/subjects/{quote(r["subject"])}/articles" style="text-decoration:none">{tag} <span style="color:#888;font-size:0.85rem">({r["count"]})</span></a>'
            )
        body = f"""
        <h1>Subjects</h1>
        <p style="color:#888;margin-bottom:1.5rem">{len(rows)} subject{'s' if len(rows) != 1 else ''} across published articles</p>
        <div class="subject-cloud">{''.join(links)}</div>
        """
    return _page("Subjects", body, author, current_path="/subjects")


@router.get("/stats", include_in_schema=False, response_class=HTMLResponse)
def stats_page(request: Request):
    """Public statistics page."""
    author = get_current_author(request)
    with get_conn().connection() as conn:
        stats = {
            "total_articles": conn.execute(
                "SELECT COUNT(*) AS c FROM articles WHERE status = 'published'"
            ).fetchone()["c"],
            "pending": conn.execute(
                "SELECT COUNT(*) AS c FROM articles WHERE status = 'pending'"
            ).fetchone()["c"],
            "total_authors": conn.execute("SELECT COUNT(*) AS c FROM authors WHERE orcid IS NOT NULL").fetchone()["c"],
            "total_downloads": conn.execute("SELECT COUNT(*) AS c FROM downloads").fetchone()["c"],
            "agent_downloads": conn.execute(
                "SELECT COUNT(*) AS c FROM downloads WHERE is_agent = TRUE"
            ).fetchone()["c"],
            "human_downloads": conn.execute(
                "SELECT COUNT(*) AS c FROM downloads WHERE is_agent = FALSE"
            ).fetchone()["c"],
        }
        top = conn.execute(
            """SELECT a.ark, a.title, COUNT(d.id) as dl_count
               FROM articles a LEFT JOIN downloads d ON d.article_id = a.id
               WHERE a.status = 'published'
               GROUP BY a.id, a.ark, a.title
               ORDER BY dl_count DESC LIMIT 10""",
        ).fetchall()

    stat_cards = []
    for label, key in [
        ("Published articles", "total_articles"),
        ("Pending review", "pending"),
        ("Authors", "total_authors"),
        ("Total downloads", "total_downloads"),
        ("Agent downloads", "agent_downloads"),
        ("Human downloads", "human_downloads"),
    ]:
        stat_cards.append(
            f'<div class="stat-card"><div class="num">{stats[key]}</div><div class="label">{label}</div></div>'
        )

    top_html = ""
    if top:
        rows_html = ""
        for r in top:
            dl = r["dl_count"] if r["dl_count"] else 0
            link = f'<a href="/article/{r["ark"]}">{r["title"]}</a>' if r["ark"] else r["title"]
            rows_html += f"<tr><td style='padding:0.5rem 0'>{link}</td><td style='padding:0.5rem 0;text-align:right'>{dl}</td></tr>"
        top_html = f"""
        <h2 style="margin-top:2rem">Top Articles by Downloads</h2>
        <table style="width:100%;border-collapse:collapse;font-size:0.9rem">
            <thead><tr style="border-bottom:2px solid var(--border);text-align:left">
                <th style="padding:0.5rem 0">Title</th>
                <th style="padding:0.5rem 0;text-align:right">Downloads</th>
            </tr></thead>
            <tbody>{rows_html}</tbody>
        </table>
        """
    else:
        top_html = '<div class="empty" style="margin-top:2rem"><p>No downloads yet.</p></div>'

    body = f"""
    <h1>Statistics</h1>
    <p style="color:#888;margin-bottom:1.5rem">Public metrics for the GenRxiv archive</p>
    <div class="stats-grid">{''.join(stat_cards)}</div>
    {top_html}
    <div style="margin-top:2rem;font-size:0.85rem;color:#888">
        <p>Machine-readable data: <a href="/api/stats">/api/stats</a> (JSON)</p>
    </div>
    """
    return _page("Statistics", body, author, current_path="/stats")


# ─── Subject articles page ─────────────────────────────────────────────────

@router.get("/subjects/{subject:path}/articles", include_in_schema=False, response_class=HTMLResponse)
def subject_articles(subject: str, request: Request, page: int = 1, per_page: int = 20):
    """Articles by subject."""
    from urllib.parse import unquote
    subject = unquote(subject)
    author = get_current_author(request)
    offset = (page - 1) * per_page
    with get_conn().connection() as conn:
        rows = conn.execute(
            """SELECT a.id, a.ark, a.title, a.abstract, a.subjects, a.published_at,
                      string_agg(au.name, ', ' ORDER BY aa."order") as author_names
               FROM articles a
               LEFT JOIN article_authors aa ON a.id = aa.article_id
               LEFT JOIN authors au ON aa.author_id = au.id
               WHERE a.status = 'published' AND %s = ANY(a.subjects)
               GROUP BY a.id
               ORDER BY a.published_at DESC LIMIT %s OFFSET %s""",
            (subject, per_page, offset),
        ).fetchall()
        total = conn.execute(
            """SELECT COUNT(*) as c FROM articles
               WHERE status = 'published' AND %s = ANY(subjects)""",
            (subject,),
        ).fetchone()["c"]

    cards = "".join(_article_card(r) for r in rows) if rows else ""
    if not cards:
        cards = '<div class="empty"><h3>No articles with this subject</h3></div>'

    body = f"""
    <h1>Subject: {subject}</h1>
    <p style="color:#888;margin-bottom:1.5rem">{total} article{'s' if total != 1 else ''}</p>
    {cards}
    <div style="margin-top:1.5rem"><a href="/subjects">&larr; All subjects</a></div>
    """
    return _page(f"Subject: {subject}", body, author)


# ─── Author profile page ───────────────────────────────────────────────────

@router.get("/author/{orcid:path}", include_in_schema=False, response_class=HTMLResponse)
def author_page(orcid: str, request: Request):
    """Author profile page."""
    from urllib.parse import unquote
    orcid = unquote(orcid)
    author_session = get_current_author(request)
    with get_conn().connection() as conn:
        author = conn.execute(
            "SELECT id, orcid, name, affiliation, created_at, orcid_works_count FROM authors WHERE orcid = %s",
            (orcid,),
        ).fetchone()
        if not author:
            raise HTTPException(404, "Author not found")
        articles = conn.execute(
            """SELECT a.id, a.ark, a.title, a.abstract, a.subjects, a.published_at,
                      string_agg(au.name, ', ' ORDER BY aa2."order") as author_names
               FROM articles a
               JOIN article_authors aa ON a.id = aa.article_id
               LEFT JOIN article_authors aa2 ON a.id = aa2.article_id
               LEFT JOIN authors au ON aa2.author_id = au.id
               WHERE aa.author_id = %s AND a.status = 'published'
               GROUP BY a.id
               ORDER BY a.published_at DESC""",
            (author["id"],),
        ).fetchall()

    cards = "".join(_article_card(r) for r in articles) if articles else ""
    if not cards:
        cards = '<div class="empty"><h3>No published articles yet</h3></div>'

    works_count = author["orcid_works_count"] if author["orcid_works_count"] else 0

    body = f"""
    <div class="author-info">
        <div>
            <div class="name">{author['name']}</div>
            <div class="orcid"><a href="https://orcid.org/{author['orcid']}">ORCID: {author['orcid']}</a></div>
            {f'<div style="font-size:0.9rem;color:#555;margin-top:0.3rem">{author["affiliation"]}</div>' if author.get('affiliation') else ''}
        </div>
    </div>
    <div class="stats-grid" style="margin-bottom:2rem">
        <div class="stat-card"><div class="num">{len(articles)}</div><div class="label">GenRxiv articles</div></div>
        <div class="stat-card"><div class="num">{works_count}</div><div class="label">ORCID publications</div></div>
    </div>
    <h2>Articles</h2>
    {cards}
    """
    return _page(author["name"], body, author_session)


# ─── Submit page ───────────────────────────────────────────────────────────

SUBMIT_CSS = """
.author-entry { display:flex; gap:0.5rem; align-items:center; margin-bottom:0.5rem; }
.author-entry input { flex:1; }
.author-entry .author-name { font-size:0.85rem; color:var(--ink-soft); margin-left:0.5rem; }
.author-entry .author-name.loading { color:var(--muted); }
.author-entry .author-name.not-found { color:#c0392b; }
.author-entry .remove-author { background:none; border:1px solid var(--border); border-radius:3px; cursor:pointer; padding:0.2rem 0.5rem; font-size:0.8rem; color:#888; }
.author-entry .remove-author:hover { color:#c0392b; border-color:#c0392b; }
.add-author-btn { background:none; border:1px dashed var(--border); border-radius:4px; padding:0.4rem 1rem; cursor:pointer; font-size:0.85rem; color:var(--ink-soft); margin-bottom:1rem; }
.add-author-btn:hover { border-color:var(--accent); color:var(--accent); }
.preview-card { background:#fff; border:1px solid var(--border); border-radius:8px; padding:1.5rem; margin-bottom:1rem; }
.preview-card h2 { margin-bottom:0.5rem; }
.preview-card .meta { font-size:0.85rem; color:#888; margin-top:0.5rem; }
.preview-card .authors-list { margin:0.5rem 0; font-size:0.95rem; }
.preview-card .author-line { padding:0.3rem 0; border-bottom:1px solid var(--rule); }
.preview-card .author-line:last-child { border-bottom:none; }
.preview-card .author-line .orcid { font-family:'IBM Plex Mono',monospace; font-size:0.8rem; color:var(--muted); }
.confirm-checkbox { display:flex; align-items:flex-start; gap:0.6rem; margin:1rem 0; }
.confirm-checkbox input[type="checkbox"] { margin-top:0.2rem; width:18px; height:18px; accent-color:var(--accent); flex-shrink:0; }
.confirm-checkbox label { font-size:0.95rem; color:var(--ink); }
/* Classification rows */
.class-row { display:flex; gap:0.5rem; align-items:center; margin-bottom:0.6rem; }
.class-row select {
    flex:1; padding:0.5rem; border:1px solid var(--border); border-radius:4px;
    font-size:0.9rem; font-family:inherit; background:#fff; color:var(--ink);
    transition: border-color 0.2s, background 0.2s;
}
.class-row select.complete {
    border-color:#2D7A3E; background:#F0F7F1;
}
.class-row .class-num {
    font-size:0.8rem; font-weight:600; color:var(--muted); min-width:1.2rem; text-align:right;
}
/* Preview button states */
.btn-preview {
    display:inline-block; padding:0.6rem 1.5rem; border-radius:4px;
    font-size:0.95rem; font-family:inherit; cursor:pointer; border:none;
    transition: background 0.2s, opacity 0.2s;
}
.btn-preview.ready { background:var(--accent); color:#fff; cursor:pointer; }
.btn-preview.ready:hover { background:#1a40d0; }
.btn-preview.disabled { background:var(--muted); color:#fff; cursor:not-allowed; opacity:0.6; }
.preview-hints { margin-top:0.6rem; font-size:0.85rem; color:#888; min-height:1.2rem; }
.preview-hints .missing-item { color:#c0392b; }
.preview-hints .all-ready { color:#2D7A3E; }
"""

SUBMIT_JS = """
var OECD_DATA = __OECD_JSON__;

// Co-author ORCID lookup
function normalizeOrcid(id) {
    id = id.trim().replace(/\\s/g, '');
    if (id.length === 16 && !id.includes('-')) {
        return id.slice(0,4) + '-' + id.slice(4,8) + '-' + id.slice(8,12) + '-' + id.slice(12,16);
    }
    return id;
}

function lookupOrcid(input, nameSpan) {
    const raw = input.value.trim();
    if (!raw) { nameSpan.textContent = ''; nameSpan.className = 'author-name'; return; }
    const orcid = normalizeOrcid(raw);
    if (!/^\\d{4}-\\d{4}-\\d{4}-\\d{4}$/.test(orcid)) {
        nameSpan.textContent = 'Invalid ORCID format';
        nameSpan.className = 'author-name not-found';
        return;
    }
    nameSpan.textContent = 'Looking up...';
    nameSpan.className = 'author-name loading';
    fetch('/api/orcid-lookup/' + orcid)
        .then(r => r.ok ? r.json() : null)
        .then(data => {
            if (data) {
                nameSpan.textContent = data.name + (data.affiliation ? ' \\u00b7 ' + data.affiliation : '');
                nameSpan.className = 'author-name';
                input.dataset.name = data.name;
            } else {
                nameSpan.textContent = 'Not found \\u2014 check the ORCID iD';
                nameSpan.className = 'author-name not-found';
                delete input.dataset.name;
            }
        })
        .catch(() => {
            nameSpan.textContent = 'Lookup failed';
            nameSpan.className = 'author-name not-found';
            delete input.dataset.name;
        });
    updatePreviewState();
}

function addAuthorRow(orcid, name) {
    const container = document.getElementById('co-authors');
    const div = document.createElement('div');
    div.className = 'author-entry';
    const input = document.createElement('input');
    input.type = 'text';
    input.name = 'co_author_orcids';
    input.placeholder = '0000-0000-0000-0000';
    input.value = orcid || '';
    input.style.padding = '0.6rem';
    input.style.border = '1px solid var(--border)';
    input.style.borderRadius = '4px';
    input.style.fontSize = '0.95rem';
    input.style.flex = '1';
    const nameSpan = document.createElement('span');
    nameSpan.className = 'author-name';
    const upBtn = document.createElement('button');
    upBtn.type = 'button';
    upBtn.className = 'move-author-up';
    upBtn.innerHTML = '&#8593;';
    upBtn.title = 'Move up';
    upBtn.onclick = function() { moveAuthorUp(this); };
    const downBtn = document.createElement('button');
    downBtn.type = 'button';
    downBtn.className = 'move-author-down';
    downBtn.innerHTML = '&#8595;';
    downBtn.title = 'Move down';
    downBtn.onclick = function() { moveAuthorDown(this); };
    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'remove-author';
    removeBtn.textContent = 'Remove';
    removeBtn.onclick = function() { div.remove(); updatePreviewState(); };
    input.addEventListener('input', function() {
        clearTimeout(input.timer);
        input.timer = setTimeout(function() { lookupOrcid(input, nameSpan); }, 400);
    });
    div.appendChild(input);
    div.appendChild(nameSpan);
    div.appendChild(upBtn);
    div.appendChild(downBtn);
    div.appendChild(removeBtn);
    container.appendChild(div);
    if (orcid) lookupOrcid(input, nameSpan);
    updatePreviewState();
}

function moveAuthorUp(btn) {
    var entry = btn.parentElement;
    var prev = entry.previousElementSibling;
    if (prev && prev.classList.contains('author-entry')) {
        entry.parentNode.insertBefore(entry, prev);
        updatePreviewState();
    }
}

function moveAuthorDown(btn) {
    var entry = btn.parentElement;
    var next = entry.nextElementSibling;
    if (next && next.classList.contains('author-entry')) {
        entry.parentNode.insertBefore(next, entry);
        updatePreviewState();
    }
}

// ─── Classification rows: domain → subdomain ─────────────────────────────
function buildClassRow(num) {
    var row = document.createElement('div');
    row.className = 'class-row';

    var label = document.createElement('span');
    label.className = 'class-num';
    label.textContent = num + '.';

    var domainSel = document.createElement('select');
    domainSel.className = 'class-domain';
    domainSel.dataset.row = num;
    domainSel.innerHTML = '<option value="">Select domain...</option>' +
        Object.keys(OECD_DATA).map(function(k) { return '<option value="' + k + '">' + k + '</option>'; }).join('');

    var subSel = document.createElement('select');
    subSel.className = 'class-subdomain';
    subSel.dataset.row = num;
    subSel.disabled = true;
    subSel.innerHTML = '<option value="">Select subdomain...</option>';

    domainSel.addEventListener('change', function() {
        var domain = domainSel.value;
        subSel.innerHTML = '<option value="">Select subdomain...</option>';
        if (domain) {
            var subs = OECD_DATA[domain];
            subSel.innerHTML += subs.map(function(s) { return '<option value="' + domain + ' > ' + s + '">' + s + '</option>'; }).join('');
            subSel.disabled = false;
        } else {
            subSel.disabled = true;
        }
        updateClassRowState(row);
        updatePreviewState();
    });

    subSel.addEventListener('change', function() {
        updateClassRowState(row);
        updatePreviewState();
    });

    row.appendChild(label);
    row.appendChild(domainSel);
    row.appendChild(subSel);
    return row;
}

function updateClassRowState(row) {
    var domainSel = row.querySelector('.class-domain');
    var subSel = row.querySelector('.class-subdomain');
    if (domainSel.value && subSel.value) {
        domainSel.classList.add('complete');
        subSel.classList.add('complete');
    } else {
        domainSel.classList.remove('complete');
        subSel.classList.remove('complete');
    }
}

function getSelectedClassifications() {
    var rows = document.querySelectorAll('.class-row');
    var selections = [];
    rows.forEach(function(row) {
        var sub = row.querySelector('.class-subdomain');
        if (sub && sub.value) selections.push(sub.value);
    });
    return selections;
}

function getClassificationCount() {
    return getSelectedClassifications().length;
}

// ─── Preview button state management ──────────────────────────────────────
function getMissingItems() {
    var missing = [];
    var title = document.querySelector('[name="title"]').value.trim();
    var abstract = document.querySelector('[name="abstract"]').value.trim();
    var mdFile = document.querySelector('[name="markdown"]').files[0];
    var classCount = getClassificationCount();
    var reviewed = document.querySelector('[name="reviewed"]').checked;
    var cc0 = document.querySelector('[name="cc0_agree"]').checked;
    var coc = document.querySelector('[name="coc_agree"]').checked;

    if (!title) missing.push('title');
    if (!abstract) missing.push('abstract');
    if (!mdFile) missing.push('Markdown file');
    if (classCount < 3) missing.push((3 - classCount) + ' more classification' + ((3 - classCount) > 1 ? 's' : ''));
    if (!reviewed) missing.push('review confirmation');
    if (!cc0) missing.push('CC0 agreement');
    if (!coc) missing.push('Code of Conduct agreement');
    return missing;
}

function updatePreviewState() {
    var btn = document.getElementById('preview-btn');
    var hints = document.getElementById('preview-hints');
    var missing = getMissingItems();

    if (missing.length === 0) {
        btn.className = 'btn-preview ready';
        btn.disabled = false;
        hints.innerHTML = '<span class="all-ready">All requirements met \\u2014 ready to preview.</span>';
    } else {
        btn.className = 'btn-preview disabled';
        btn.disabled = true;
        hints.innerHTML = '<span class="missing-item">Still needed: ' + missing.join(', ') + '</span>';
    }
}

// ─── Preview step ─────────────────────────────────────────────────────────
function showPreview(e) {
    e.preventDefault();
    if (getMissingItems().length > 0) return;

    var title = document.querySelector('[name="title"]').value.trim();
    var abstract = document.querySelector('[name="abstract"]').value.trim();
    var mdFile = document.querySelector('[name="markdown"]').files[0];
    var subjects = getSelectedClassifications();

    // Gather all authors from the author entries
    // The submitter is included as an author entry (first, with a "you" label)
    // but author order is determined by the entries, not forced.
    var authors = [];
    var allAuthorInputs = document.querySelectorAll('.author-entry input[type="text"]');
    allAuthorInputs.forEach(function(input) {
        var orcid = normalizeOrcid(input.value);
        if (orcid && /^\\d{4}-\\d{4}-\\d{4}-\\d{4}$/.test(orcid)) {
            var name = input.dataset.name || input.parentElement.querySelector('.author-name').textContent.split(' \\u00b7 ')[0] || 'Unknown';
            if (name && !name.includes('Not found') && !name.includes('Looking') && !name.includes('Invalid') && !name.includes('failed')) {
                authors.push({orcid: orcid, name: name});
            }
        }
    });

    // Build preview
    var authorsHtml = authors.map(function(a) {
        return '<div class="author-line">' + a.name + ' <span class="orcid">' + a.orcid + '</span></div>';
    }).join('');
    var subjHtml = subjects.map(function(k) { return '<span class="subject-tag">' + k + '</span>'; }).join(' ');

    document.getElementById('preview-title').textContent = title;
    document.getElementById('preview-abstract').textContent = abstract;
    document.getElementById('preview-authors').innerHTML = authorsHtml;
    document.getElementById('preview-subjects').innerHTML = subjHtml;
    document.getElementById('preview-file').textContent = mdFile.name + ' (' + (mdFile.size / 1024).toFixed(1) + ' KB)';

    // Store authors JSON for final submission
    document.getElementById('authors-json').value = JSON.stringify(authors);

    // Copy values to confirm form
    document.getElementById('confirm-title').value = title;
    document.getElementById('confirm-abstract').value = abstract;
    document.getElementById('confirm-authors').value = JSON.stringify(authors);
    document.getElementById('confirm-subjects').value = subjects.join(', ');
    // Copy agreement checkbox states
    document.getElementById('confirm-reviewed').value = document.querySelector('[name="reviewed"]').checked ? '1' : '';
    document.getElementById('confirm-cc0').value = document.querySelector('[name="cc0_agree"]').checked ? '1' : '';
    document.getElementById('confirm-coc').value = document.querySelector('[name="coc_agree"]').checked ? '1' : '';
    // Copy the file to the confirm form's file input
    // DataTransfer is needed because .files is read-only
    var confirmFile = document.getElementById('confirm-markdown');
    try {
        var dt = new DataTransfer();
        dt.items.add(mdFile);
        confirmFile.files = dt.files;
    } catch (err) {
        console.error('Could not copy file to confirm form:', err);
    }

    // Show preview, hide form
    document.getElementById('submit-form').style.display = 'none';
    document.getElementById('preview-section').style.display = 'block';
}

function backToForm(e) {
    e.preventDefault();
    document.getElementById('submit-form').style.display = 'block';
    document.getElementById('preview-section').style.display = 'none';
}

// ─── YAML front matter auto-fill ──────────────────────────────────────────
// When a Markdown file is selected, send it to /api/validate which
// parses front matter using PyYAML (the same parser the API uses).
// The response includes parsed_metadata with title, abstract, authors,
// and subjects extracted from the file's YAML front matter.

function fillFormFromFrontMatter(meta) {
    if (!meta) return;

    // Title
    if (meta.title) {
        var titleInput = document.querySelector('[name="title"]');
        if (titleInput) titleInput.value = meta.title;
    }

    // Abstract
    if (meta.abstract) {
        var abstractInput = document.querySelector('[name="abstract"]');
        if (abstractInput) abstractInput.value = meta.abstract;
    }

    // Authors (array of {orcid, name} objects) — replaces all author entries
    // The submitter must always be present; if the front matter doesn't
    // include them, they are appended.
    if (meta.authors && Array.isArray(meta.authors)) {
        var container = document.getElementById('co-authors');
        var submitterOrcid = document.querySelector('[data-submitter="true"] input');
        var myOrcid = submitterOrcid ? normalizeOrcid(submitterOrcid.value) : null;
        var myName = submitterOrcid ? submitterOrcid.dataset.name : null;
        // Remove all existing author entries
        container.innerHTML = '';

        var foundSubmitter = false;
        meta.authors.forEach(function(a) {
            if (a.orcid && a.name) {
                addAuthorRow(a.orcid, a.name);
                if (myOrcid && normalizeOrcid(a.orcid) === myOrcid) foundSubmitter = true;
            }
        });
        // If the submitter wasn't in the front matter, add them
        if (!foundSubmitter && myOrcid && myName) {
            addAuthorRow(myOrcid, myName);
        }
    }

    // Subjects (array of "Domain > Subdomain" strings)
    if (meta.subjects && Array.isArray(meta.subjects)) {
        var rows = document.querySelectorAll('.class-row');
        meta.subjects.forEach(function(subj, idx) {
            if (idx >= rows.length) return;
            var parts = subj.split(' > ');
            var domain = parts[0].trim();
            var subdomain = parts[1] ? parts[1].trim() : '';

            var domainSel = rows[idx].querySelector('.class-domain');
            var subSel = rows[idx].querySelector('.class-subdomain');

            // Set domain
            domainSel.value = domain;
            // Trigger change to populate subdomain options
            domainSel.dispatchEvent(new Event('change'));

            // Set subdomain if we have a value
            if (subdomain) {
                // The option value is "Domain > Subdomain"
                var fullValue = domain + ' > ' + subdomain;
                subSel.value = fullValue;
                subSel.dispatchEvent(new Event('change'));
            }
        });
    }

    // Update preview state after filling
    updatePreviewState();
}

function handleFileSelect(input) {
    if (!input.files || !input.files.length) return;
    var file = input.files[0];
    // Send the file to /api/validate to parse front matter using the
    // same PyYAML parser as the API — no hand-written JS YAML parser.
    var formData = new FormData();
    formData.append('markdown', file);
    fetch('/api/validate', {
        method: 'POST',
        body: formData,
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.parsed_metadata) {
            fillFormFromFrontMatter(data.parsed_metadata);
        }
    })
    .catch(function(err) {
        console.error('Front matter parse failed:', err);
    });
}

// ─── Init ─────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function() {
    // Build 3 classification rows
    var classContainer = document.getElementById('classification-rows');
    for (var i = 1; i <= 3; i++) {
        classContainer.appendChild(buildClassRow(i));
    }

    // Add co-author button
    document.getElementById('add-author-btn').addEventListener('click', function() {
        addAuthorRow('', '');
    });

    // File input: auto-fill from YAML front matter
    var fileInput = document.querySelector('[name="markdown"]');
    if (fileInput) {
        fileInput.addEventListener('change', function() {
            handleFileSelect(this);
        });
    }

    // Monitor all inputs for preview state updates
    var form = document.getElementById('main-form');
    if (form) {
        form.addEventListener('input', updatePreviewState);
        form.addEventListener('change', updatePreviewState);
    }

    // Initial state
    updatePreviewState();
});

// beforeunload: check form state directly — no dependency on event listeners
var _submitConfirmed = false;
function _formHasData() {
    var form = document.getElementById('main-form');
    if (!form) return false;
    var hasData = false;
    form.querySelectorAll('input[type="text"], textarea').forEach(function(el) {
        if (el.value.trim()) hasData = true;
    });
    var fileInput = form.querySelector('input[type="file"]');
    if (fileInput && fileInput.files && fileInput.files.length > 0) hasData = true;
    form.querySelectorAll('input[type="checkbox"]').forEach(function(el) {
        if (el.checked) hasData = true;
    });
    form.querySelectorAll('select').forEach(function(el) {
        if (el.value) hasData = true;
    });
    form.querySelectorAll('input[name="co_author_orcids"]').forEach(function(el) {
        if (el.value.trim()) hasData = true;
    });
    return hasData;
}

window.addEventListener('beforeunload', function(e) {
    if (_submitConfirmed) return;
    if (_formHasData()) {
        e.preventDefault();
        e.returnValue = 'You have unsaved changes. Are you sure you want to leave?';
        return 'You have unsaved changes. Are you sure you want to leave?';
    }
});

// Also intercept nav link clicks and form submits for an explicit confirm()
// This is a fallback in case beforeunload doesn't fire
document.addEventListener('DOMContentLoaded', function() {
    var nav = document.querySelector('nav');
    if (!nav) return;
    // Intercept all links in the nav
    nav.querySelectorAll('a[href]').forEach(function(link) {
        link.addEventListener('click', function(e) {
            if (_submitConfirmed) return;
            if (!_formHasData()) return;
            if (!confirm('You have unsaved changes. Are you sure you want to leave?')) {
                e.preventDefault();
            }
        });
    });
    // Intercept form submissions in the nav (e.g. Sign out)
    nav.querySelectorAll('form').forEach(function(form) {
        form.addEventListener('submit', function(e) {
            if (_submitConfirmed) return;
            if (!_formHasData()) return;
            if (!confirm('You have unsaved changes. Are you sure you want to leave?')) {
                e.preventDefault();
            }
        });
    });
});

// Intercept confirm form submit — post via fetch, redirect to submission page
document.addEventListener('DOMContentLoaded', function() {
    var confirmForm = document.getElementById('confirm-form');
    if (confirmForm) {
        confirmForm.addEventListener('submit', function(e) {
            e.preventDefault();
            _submitConfirmed = true;
            var btn = confirmForm.querySelector('button[type="submit"]');
            btn.disabled = true;
            btn.textContent = 'Submitting...';
            fetch('/api/submit', {
                method: 'POST',
                body: new FormData(confirmForm),
            })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.id) {
                    window.location.href = '/submit/done/' + data.id;
                } else {
                    alert('Submission failed: ' + (data.detail || JSON.stringify(data)));
                    btn.disabled = false;
                    btn.textContent = 'Confirm and submit';
                }
            })
            .catch(function(err) {
                alert('Submission failed: ' + err);
                btn.disabled = false;
                btn.textContent = 'Confirm and submit';
            });
        });
    }
});
"""


@router.get("/code-of-conduct", include_in_schema=False, response_class=HTMLResponse)
def code_of_conduct_page(request: Request):
    """Public code of conduct for authors and agents."""
    author = get_current_author(request)
    from code_of_conduct import COC_HTML
    return _page("Code of Conduct", COC_HTML, author, extra_css_files=["/css/coc.css"], current_path="/code-of-conduct")


@router.get("/submit", include_in_schema=False, response_class=HTMLResponse)
def submit_page(request: Request):
    """Submission form with ORCID-based author entry and preview/confirm flow."""
    author = get_current_author(request)
    if not author:
        body = f"""
        <div class="empty">
            <h3>Sign in to submit</h3>
            <p>You need an ORCID to submit to {config.site_name}.</p>
            <p style="margin-top:1rem"><a href="/auth/orcid?redirect=/submit" class="btn btn-primary">Sign in with ORCID</a></p>
        </div>
        """
        return _page("Submit", body, None, current_path="/submit")

    import json as _json
    oecd_json = _json.dumps(OECD_FOS)
    # OECD data is dynamic, so inject it as a small inline script before
    # the external submit.js loads (which references OECD_DATA as a global).
    submit_inline_js = f"var OECD_DATA = {oecd_json};"

    body = f"""
    <h1>Submit a Paper</h1>
    <p style="color:#888;margin-bottom:1.5rem">GenRxiv accepts Markdown submissions only. Markdown is the version of record.</p>

    <div id="submit-form">
        <form method="post" action="/api/submit" enctype="multipart/form-data" id="main-form">
            <input type="hidden" name="submitter_orcid" value="{author['orcid']}">
            <input type="hidden" name="submitter_name" value="{author['name']}">
            <input type="hidden" name="authors" id="authors-json" value="">
            <input type="hidden" name="license" value="CC0">
            <input type="hidden" name="license_url" value="https://creativecommons.org/publicdomain/zero/1.0/">

            <div class="form-group">
                <label>Markdown file (.md)</label>
                <input type="file" name="markdown" accept=".md,.markdown" required>
                <div class="hint">Max 25MB. The file is the version of record.</div>
                <div class="hint" style="margin-top:0.3rem;color:var(--cobalt)">
                    Metadata can be embedded as YAML front matter in the file —
                    the form will auto-fill when you upload. See
                    <a href="/api/agent-guide" target="_blank">the agent guide</a>
                    for the format.
                </div>
            </div>

            <div class="form-group">
                <label>Title</label>
                <input type="text" name="title" required placeholder="Paper title">
            </div>

            <div class="form-group">
                <label>Abstract</label>
                <textarea name="abstract" required placeholder="A brief summary of the research..."></textarea>
                <div class="hint">Required. This is what appears in browse, search, and feeds.</div>
            </div>

            <div class="form-group">
                <label>Authors (in order — first author is the lead)</label>
                <div id="co-authors">
                    <div class="author-entry" data-submitter="true">
                        <input type="text" name="co_author_orcids" value="{author['orcid']}"
                            style="padding:0.6rem;border:1px solid var(--border);border-radius:4px;font-size:0.95rem;flex:1"
                            data-name="{author['name']}" readonly>
                        <span class="author-name">{author['name']} (you)</span>
                        <button type="button" class="move-author-up" onclick="moveAuthorUp(this)" title="Move up">&#8593;</button>
                        <button type="button" class="move-author-down" onclick="moveAuthorDown(this)" title="Move down">&#8595;</button>
                    </div>
                </div>
                <div class="hint" style="margin-bottom:0.5rem">Add all authors by ORCID iD. Use the arrows to set publication order — the first author is the lead. You must be listed as an author; you cannot remove yourself.</div>
                <button type="button" class="add-author-btn" id="add-author-btn">+ Add author</button>
            </div>

            <div class="form-group">
                <label>Subject classifications (select 3)</label>
                <div id="classification-rows"></div>
                <div class="hint">Select a domain then a subdomain for each row. Boxes turn green when both are selected.</div>
            </div>

            <div class="form-group">
                <div class="confirm-checkbox">
                    <input type="checkbox" name="reviewed" id="reviewed">
                    <label for="reviewed">I agree that even if this work was co-authored with AI, I have reviewed it for accuracy and integrity.</label>
                </div>
                <div class="confirm-checkbox">
                    <input type="checkbox" name="cc0_agree" id="cc0_agree">
                    <label for="cc0_agree">I dedicate this work to the public domain under <a href="https://creativecommons.org/publicdomain/zero/1.0/" target="_blank">CC0</a>.</label>
                </div>
                <div class="confirm-checkbox">
                    <input type="checkbox" name="coc_agree" id="coc_agree">
                    <label for="coc_agree">I have read and agree to the <a href="/code-of-conduct">Code of Conduct</a>.</label>
                </div>
            </div>

            <button type="button" class="btn-preview disabled" id="preview-btn" disabled onclick="showPreview(event)">Preview submission</button>
            <div class="preview-hints" id="preview-hints"></div>
        </form>
    </div>

    <div id="preview-section" style="display:none">
        <h2>Preview</h2>
        <p style="color:#888;margin-bottom:1.5rem">Please review your submission before confirming.</p>

        <div class="preview-card">
            <h2 id="preview-title"></h2>
            <div class="meta"><strong>Abstract:</strong> <span id="preview-abstract"></span></div>
            <div class="authors-list" id="preview-authors"></div>
            <div class="meta"><strong>Subjects:</strong> <span id="preview-subjects"></span></div>
            <div class="meta"><strong>File:</strong> <span id="preview-file"></span></div>
            <div class="meta"><strong>License:</strong> CC0 (Public Domain)</div>
        </div>

        <p style="margin:1.5rem 0">By confirming, you agree that the authors listed above are correct and that you have their permission to include them.</p>

        <form method="post" action="/api/submit" enctype="multipart/form-data" id="confirm-form">
            <!-- Re-submit all fields -->
            <input type="hidden" name="title" id="confirm-title">
            <input type="hidden" name="abstract" id="confirm-abstract">
            <input type="hidden" name="authors" id="confirm-authors">
            <input type="hidden" name="license" value="CC0">
            <input type="hidden" name="license_url" value="https://creativecommons.org/publicdomain/zero/1.0/">
            <input type="hidden" name="subjects" id="confirm-subjects">
            <input type="hidden" name="reviewed_agree" id="confirm-reviewed" value="">
            <input type="hidden" name="cc0_agree" id="confirm-cc0" value="">
            <input type="hidden" name="coc_agree" id="confirm-coc" value="">
            <!-- File needs to be re-attached — we'll use JS to copy it -->
            <input type="file" name="markdown" id="confirm-markdown" style="display:none">
            <button type="submit" class="btn btn-primary">Confirm and submit</button>
            <button type="button" class="btn" onclick="backToForm(event)" style="margin-left:0.5rem">Go back and edit</button>
        </form>
    </div>

    <div style="margin-top:1.5rem;font-size:0.85rem;color:#888">
        <p>After submission, your paper will be reviewed by a moderator before publication.
        You'll be able to track its status from <a href="/dashboard">My Submissions</a>.</p>
    </div>
    """
    return _page("Submit", body, author, extra_css_files=["/css/submit.css"], extra_js=submit_inline_js, extra_js_files=["/js/submit.js"], current_path="/submit")


@router.get("/submit/done/{article_id}", include_in_schema=False, response_class=HTMLResponse)
def submit_done_page(article_id: int, request: Request, retraction: str = ""):
    """Show submission confirmation with rendered article preview."""
    author = require_author(request)
    is_retraction = bool(retraction)
    with get_conn().connection() as conn:
        article = conn.execute(
            """SELECT id, ark, title, abstract, status, version, submitted_at,
                      source_markdown, subjects
               FROM articles WHERE id = %s AND submitted_by = %s""",
            (article_id, author["id"]),
        ).fetchone()
        if not article:
            raise HTTPException(404, "Submission not found")
        author_rows = conn.execute(
            """SELECT a.orcid, a.name FROM authors a
               JOIN article_authors aa ON a.id = aa.author_id
               WHERE aa.article_id = %s ORDER BY aa."order\"""",
            (article_id,),
        ).fetchall()

    # Render the article HTML and extract body content + KaTeX assets
    article_body, katex_head = _render_article_preview(article["source_markdown"])

    ark = article["ark"] or "(pending)"
    authors_html = ", ".join(
        f'{a["name"]} <span class="orcid">{a["orcid"]}</span>' for a in author_rows
    )
    subjects = article["subjects"] or []
    from oecd_codes import classification_tag
    subjects_html = "".join(classification_tag(s) for s in subjects)

    # Article-specific CSS
    article_css = """
    .article-content { max-width: 800px; margin: 0 auto; line-height: 1.6; }
    .article-content h1, .article-content h2, .article-content h3 { margin-top: 1.5em; margin-bottom: 0.5em; }
    .article-content h1 + h2, .article-content h2 + h3 { margin-top: 0.5em; }
    .article-content p { margin: 0.8em 0; }
    .article-content pre { background: #f5f2eb; padding: 1em; border-radius: 4px; overflow-x: auto; }
    .article-content code { font-family: 'IBM Plex Mono', monospace; }
    .article-content blockquote { border-left: 3px solid #c9c3b5; margin: 1em 0; padding-left: 1em; color: #555; }
    .article-content table { border-collapse: collapse; margin: 1em 0; }
    .article-content th, .article-content td { border: 1px solid #c9c3b5; padding: 0.5em; }
    .article-content img { max-width: 100%; height: auto; }
    .katex-display { overflow-x: auto; overflow-y: hidden; padding: 0.5rem 0; }
    .orcid { font-size: 0.85em; color: var(--muted); }
    .subject-tag { display: inline-block; background: var(--accent-soft); color: var(--accent); padding: 0.2em 0.6em; border-radius: 3px; font-size: 0.85rem; margin: 0.2em; }
    """

    body = f"""
    <div class="card" style="margin-bottom:1.5rem;border-left:4px solid #2D7A3E">
        <h2 style="color:#2D7A3E">{"Retraction submitted" if is_retraction else "Submission received"}</h2>
        <p>{"Your retraction notice has been submitted and is awaiting moderation. Once approved, the ARK will point to the retraction notice and the original will be preserved in the version history." if is_retraction else "Your paper has been submitted and is awaiting moderation."}</p>
        <p style="margin-top:0.5rem">
            <strong>Status:</strong> <span class="status-badge status-pending">pending</span>
            &middot; <strong>ARK:</strong> {ark}
            &middot; <strong>Version:</strong> {article["version"]}
        </p>
        <p style="margin-top:0.8rem">
            <a href="/dashboard" class="btn btn-primary">Go to My Submissions</a>
            <a href="/submit" class="btn" style="margin-left:0.5rem">Submit another paper</a>
        </p>
    </div>

    <h1>{article["title"]}</h1>
    <div class="meta" style="margin-bottom:1rem">
        <p><strong>Authors:</strong> {authors_html}</p>
        <p><strong>Subjects:</strong> {subjects_html}</p>
    </div>

    <div class="article-content">
        {article_body}
    </div>
    """
    return _page(
        "Submission Received",
        body,
        author,
        extra_css_files=["/css/article-content.css"],
        extra_head=katex_head,
        current_path="/submit",
    )


@router.get("/submit-version/{article_id}", include_in_schema=False, response_class=HTMLResponse)
def submit_version_page(article_id: int, request: Request):
    """Submit a new version of an existing article."""
    author = require_author(request)
    with get_conn().connection() as conn:
        article = conn.execute(
            "SELECT id, ark, title, version, status FROM articles WHERE id = %s",
            (article_id,),
        ).fetchone()
        if not article:
            raise HTTPException(404, "Article not found")
        # Verify the author is one of the article's authors
        is_author = conn.execute(
            "SELECT 1 FROM article_authors WHERE article_id = %s AND author_id = %s",
            (article_id, author["id"]),
        ).fetchone()
        if not is_author:
            raise HTTPException(403, "You can only submit new versions of your own articles")

    body = f"""
    <h1>Submit New Version</h1>
    <div class="card" style="margin-bottom:1.5rem">
        <h2>{article['title']}</h2>
        <div class="meta">
            Current version: v{article['version']}
            &middot; Status: <span class="status-badge status-{article['status']}">{article['status']}</span>
            {f'&middot; ARK: {article["ark"]}' if article.get('ark') else ''}
        </div>
        <p style="margin-top:0.5rem;font-size:0.9rem;color:#555">
            The new version will go through moderation again. Once approved, it will
            replace the current version and the ARK will transfer to the new version.
        </p>
    </div>
    <form method="post" action="/api/submit" enctype="multipart/form-data">
        <input type="hidden" name="supersedes_id" value="{article_id}">
        <div class="form-group">
            <label>Updated Markdown file (.md)</label>
            <input type="file" name="markdown" accept=".md,.markdown" required>
            <div class="hint">Max 25MB. The file is the version of record.</div>
        </div>
        <div class="form-group">
            <label>Title</label>
            <input type="text" name="title" required value="{article['title']}">
        </div>
        <div class="form-group">
            <label>Authors (JSON array)</label>
            <textarea name="authors" required>[{{"orcid": "{author['orcid']}", "name": "{author['name']}"}}]</textarea>
            <div class="hint">JSON array of {{"orcid": "...", "name": "...", "affiliation": "..."}} objects.</div>
        </div>
        <div class="form-group">
            <label>Abstract (optional)</label>
            <textarea name="abstract" placeholder="Brief abstract..."></textarea>
        </div>
        <div class="form-group">
            <label>Subjects (comma-separated, optional)</label>
            <input type="text" name="subjects" placeholder="AI, machine learning, ...">
        </div>
        <div class="form-group">
            <label>License</label>
            <select name="license" id="license-select">
                <option value="CC-BY-4.0">CC BY 4.0 (default)</option>
                <option value="CC-BY-SA-4.0">CC BY-SA 4.0</option>
                <option value="CC-BY-ND-4.0">CC BY-ND 4.0</option>
                <option value="CC0">CC0 (Public Domain)</option>
            </select>
            <input type="hidden" name="license_url" id="license-url" value="https://creativecommons.org/licenses/by/4.0/">
        </div>
        <button type="submit" class="btn btn-primary">Submit version for review</button>
    </form>
    <div style="margin-top:1.5rem"><a href="/dashboard">&larr; Back to My Submissions</a></div>
    <script>
    document.getElementById('license-select').addEventListener('change', function() {{
        var urls = {{
            'CC-BY-4.0': 'https://creativecommons.org/licenses/by/4.0/',
            'CC-BY-SA-4.0': 'https://creativecommons.org/licenses/by-sa/4.0/',
            'CC-BY-ND-4.0': 'https://creativecommons.org/licenses/by-nd/4.0/',
            'CC0': 'https://creativecommons.org/publicdomain/zero/1.0/'
        }};
        document.getElementById('license-url').value = urls[this.value] || '';
    }});
    </script>
    """
    return _page("Submit New Version", body, author)


# ─── Dashboard (author's submissions) ──────────────────────────────────────

@router.get("/dashboard", include_in_schema=False, response_class=HTMLResponse)
def dashboard_page(request: Request, deleted: str = ""):
    """Author's submissions dashboard."""
    author = require_author(request)
    deleted_banner = ""
    if deleted:
        deleted_banner = (
            '<div class="card" style="margin-bottom:1.5rem;border-left:4px solid #2D7A3E;background:#f0fff4">'
            "Submission deleted.</div>"
        )
    with get_conn().connection() as conn:
        rows = conn.execute(
            """SELECT id, ark, title, status, version, submitted_at, published_at
               FROM articles WHERE submitted_by = %s ORDER BY submitted_at DESC""",
            (author["id"],),
        ).fetchall()
        # Get the author's email for the notification settings section
        author_email = conn.execute(
            "SELECT email FROM authors WHERE id = %s", (author["id"],)
        ).fetchone()

    email_value = author_email["email"] if author_email and author_email["email"] else ""

    # Email notification settings — link to profile page
    if email_value:
        email_section = f"""
        <div class="card" style="margin-bottom:2rem">
            <h2 style="font-size:1.1rem">Notification Settings</h2>
            <p style="font-size:0.9rem;color:#555">
                Notification email: <strong>{email_value}</strong>
                &middot; <a href="/profile">Edit in profile</a>
            </p>
        </div>
        """
    else:
        email_section = """
        <div class="card" style="margin-bottom:2rem">
            <h2 style="font-size:1.1rem">Notification Settings</h2>
            <p style="font-size:0.9rem;color:#555">
                No notification email set.
                <a href="/profile">Add your email in your profile</a> to receive moderation updates.
            </p>
        </div>
        """

    if not rows:
        body = f"""
        {deleted_banner}
        {email_section}
        <div class="empty">
            <h3>No submissions yet</h3>
            <p>Submit your first paper.</p>
            <p style="margin-top:1rem"><a href="/submit" class="btn btn-primary">Submit a paper</a></p>
        </div>
        """
    else:
        cards = []
        for r in rows:
            status_class = f"status-{r['status']}"
            ark = r["ark"] or "(pending)"
            published = _format_date(r.get("published_at"))
            submitted = _format_date(r.get("submitted_at"))
            link = f'<a href="/article/{r["ark"]}">{r["title"]}</a>' if r["ark"] else r["title"]
            version_badge = f'<span class="status-badge" style="background:#e4e9ff;color:#2f5cff">v{r["version"]}</span>' if r.get("version") and r["version"] > 1 else ""
            actions = [f'<a href="/dashboard/preview/{r["id"]}" class="btn" style="font-size:0.8rem;padding:0.3rem 0.8rem">Preview</a>']
            if r["status"] in ("published", "superseded"):
                actions.append(f'<a href="/submit-version/{r["id"]}" class="btn" style="font-size:0.8rem;padding:0.3rem 0.8rem">Submit new version</a>')
                actions.append(f'<a href="/dashboard/retract/{r["id"]}" class="btn" style="font-size:0.8rem;padding:0.3rem 0.8rem;border-color:#b48a00;color:#b48a00">Retract</a>')
            if r["status"] in ("pending", "rejected"):
                actions.append(f'<a href="/dashboard/delete/{r["id"]}" class="btn btn-danger" style="font-size:0.8rem;padding:0.3rem 0.8rem">Delete</a>')
            actions_html = " ".join(actions)
            cards.append(f"""<div class="card">
<h2>{link}</h2>
<div class="meta">
    <span class="status-badge {status_class}">{r['status']}</span>
    {version_badge}
    &middot; Submitted {submitted}
    {f'&middot; Published {published}' if published else ''}
    &middot; ARK: {ark}
</div>
<div style="margin-top:0.5rem">{actions_html}</div>
</div>""")
        body = f"""
        <h1>My Submissions</h1>
        {deleted_banner}
        {email_section}
        <p style="margin-bottom:1.5rem"><a href="/submit" class="btn btn-primary">Submit new paper</a></p>
        {''.join(cards)}
        """
    return _page("My Submissions", body, author, current_path="/dashboard")


# ─── Submission preview & delete (author's own submissions) ────────────────
#
# The public /article/{ark} routes only serve *published* articles (an ARK is
# only assigned on approval), so pending/rejected submissions have no public
# view. These dashboard-scoped routes let the submitter preview their own
# submission in any status, and delete it while it is still unpublished.

_ARTICLE_CONTENT_CSS = """
.article-content { max-width: 800px; margin: 0 auto; line-height: 1.6; }
.article-content h1, .article-content h2, .article-content h3 { margin-top: 1.5em; margin-bottom: 0.5em; }
.article-content h1 + h2, .article-content h2 + h3 { margin-top: 0.5em; }
.article-content p { margin: 0.8em 0; }
.article-content pre { background: #f5f2eb; padding: 1em; border-radius: 4px; overflow-x: auto; }
.article-content code { font-family: 'IBM Plex Mono', monospace; }
.article-content blockquote { border-left: 3px solid #c9c3b5; margin: 1em 0; padding-left: 1em; color: #555; }
.article-content table { border-collapse: collapse; margin: 1em 0; }
.article-content th, .article-content td { border: 1px solid #c9c3b5; padding: 0.5em; }
.article-content img { max-width: 100%; height: auto; }
.article-content figure { margin: 2rem 0; text-align: center; }
.article-content figcaption { font-size: 0.9rem; color: #666; margin-top: 0.5rem; }
.katex-display { overflow-x: auto; overflow-y: hidden; padding: 0.5rem 0; }
.orcid { font-size: 0.85em; color: var(--muted); }
.subject-tag { display: inline-block; background: var(--accent-soft); color: var(--accent); padding: 0.2em 0.6em; border-radius: 3px; font-size: 0.85rem; margin: 0.2em; }
/* Bibliography: Pandoc CSL output uses csl-left-margin / csl-right-inline
   divs. Without this CSS they stack vertically, putting the citation
   number on a separate line from the entry. */
.article-content .csl-left-margin { display: inline-block; min-width: 2.5em; }
.article-content .csl-right-inline { display: inline; }
"""


def _render_article_preview(source_markdown: str) -> tuple[str, str]:
    """Render Markdown to an HTML body fragment + KaTeX head assets.

    Returns (article_body_html, katex_head_html).
    Used by the submit confirmation page and the dashboard preview page
    to show rendered article content inside the GenRxiv page template.
    """
    import re as _re
    from articles import render_html

    try:
        full_html = render_html(source_markdown)
        # Extract body content
        m = _re.search(r"<body[^>]*>(.*)</body>", full_html, _re.DOTALL)
        article_body = m.group(1) if m else full_html
        # Extract KaTeX CSS link — match both /> and > endings (HTML5)
        katex_links = _re.findall(r'<link[^>]*katex[^>]*?/?>', full_html)
        # Extract KaTeX scripts (katex.min.js only, not auto-render)
        katex_scripts = _re.findall(
            r'<script[^>]*katex\.min\.js[^>]*></script>', full_html
        )
        # Extract auto-render script (has the onload handler)
        auto_render = _re.findall(
            r'<script[^>]*auto-render[^>]*>.*?</script>', full_html, _re.DOTALL
        )
        katex_head = "\n".join(katex_links + katex_scripts + auto_render)
        return article_body, katex_head
    except Exception as e:
        logger.error("Article preview rendering failed: %s", e)
        return '<p class="empty">Preview rendering failed.</p>', ""


def _author_own_article(article_id: int, author: dict):
    """Load an article owned by the author (submitter), or 404.

    Used by the preview/delete dashboard routes. Returns the article row
    regardless of status so the author can preview pending/rejected work.
    """
    from articles import get_article_by_id_for_author
    article = get_article_by_id_for_author(article_id, author["id"])
    if not article:
        raise HTTPException(404, "Submission not found")
    return article


@router.get("/dashboard/preview/{article_id}", include_in_schema=False, response_class=HTMLResponse)
def dashboard_preview_page(article_id: int, request: Request):
    """Render the author's own submission as HTML (any status)."""
    author = require_author(request)
    article = _author_own_article(article_id, author)

    with get_conn().connection() as conn:
        author_rows = conn.execute(
            """SELECT a.orcid, a.name FROM authors a
               JOIN article_authors aa ON a.id = aa.author_id
               WHERE aa.article_id = %s ORDER BY aa."order\"""",
            (article_id,),
        ).fetchall()

    article_body, katex_head = _render_article_preview(article["source_markdown"])

    ark = article["ark"] or "(pending)"
    authors_html = ", ".join(
        f'{a["name"]} <span class="orcid">{a["orcid"]}</span>' for a in author_rows
    )
    subjects = article["subjects"] or []
    from oecd_codes import classification_tag
    subjects_html = "".join(classification_tag(s) for s in subjects)
    status = article["status"]
    status_note = ""
    if status == "pending":
        status_note = (
            '<div class="card" style="margin-bottom:1.5rem;border-left:4px solid #b48a00;background:#fffdf0">'
            '<strong>Awaiting moderation.</strong> This preview is only visible to you '
            "and the moderators until it is approved and published.</div>"
        )
    elif status == "rejected":
        status_note = (
            '<div class="card" style="margin-bottom:1.5rem;border-left:4px solid #c0392b;background:#fdf0f0">'
            "<strong>Rejected.</strong> This submission was not accepted for publication.</div>"
        )

    body = f"""
    <div class="meta" style="margin-bottom:1rem">
        <span class="status-badge status-{status}">{status}</span>
        &middot; <strong>ARK:</strong> {ark}
        &middot; <strong>Version:</strong> v{article["version"]}
        <span style="margin-left:1rem">
            <a href="/dashboard/preview/{article_id}/markdown" class="btn" style="font-size:0.8rem;padding:0.3rem 0.8rem">Markdown</a>
            <a href="/dashboard/preview/{article_id}/pdf" class="btn" style="font-size:0.8rem;padding:0.3rem 0.8rem">PDF</a>
        </span>
    </div>
    {status_note}
    <h1>{article["title"]}</h1>
    <div class="meta" style="margin-bottom:1rem">
        <p><strong>Authors:</strong> {authors_html}</p>
        <p><strong>Subjects:</strong> {subjects_html}</p>
    </div>
    <div class="article-content">
        {article_body}
    </div>
    <div style="margin-top:1.5rem"><a href="/dashboard">&larr; Back to My Submissions</a></div>
    """
    return _page(
        f"Preview: {article['title']}",
        body,
        author,
        extra_css_files=["/css/article-content.css"],
        extra_head=katex_head,
        current_path="/dashboard",
    )


@router.get("/dashboard/preview/{article_id}/markdown", include_in_schema=False)
def dashboard_preview_markdown(article_id: int, request: Request):
    """Download the original Markdown source of the author's own submission."""
    author = require_author(request)
    article = _author_own_article(article_id, author)
    filename = f"{article['ark'].replace('/', '_') if article['ark'] else f'submission-{article_id}'}.md"
    return Response(
        content=article["source_markdown"].encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/dashboard/preview/{article_id}/pdf", include_in_schema=False)
def dashboard_preview_pdf(article_id: int, request: Request):
    """Render the author's own submission as a PDF on the fly."""
    author = require_author(request)
    article = _author_own_article(article_id, author)
    from articles import render_pdf
    try:
        pdf_bytes = render_pdf(article["source_markdown"])
    except Exception as e:
        logger.error("PDF rendering failed for article %s: %s", article_id, e)
        raise HTTPException(502, "PDF rendering failed. The conversion service may be unavailable.")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="preview-{article_id}.pdf"',
        },
    )


@router.get("/dashboard/delete/{article_id}", include_in_schema=False, response_class=HTMLResponse)
def dashboard_delete_confirm(article_id: int, request: Request):
    """Confirmation page before deleting an author's own submission."""
    author = require_author(request)
    article = _author_own_article(article_id, author)
    status = article["status"]
    from articles import DELETABLE_STATUSES
    if status not in DELETABLE_STATUSES:
        body = f"""
        <div class="card" style="border-left:4px solid #c0392b">
            <h2>Cannot delete this submission</h2>
            <p>This submission is <strong>{status}</strong>. Only
            {'/'.join(DELETABLE_STATUSES)} submissions can be deleted — published
            articles carry a persistent ARK and may already be cited externally.</p>
            <p style="margin-top:1rem"><a href="/dashboard" class="btn">&larr; Back to My Submissions</a></p>
        </div>
        """
        return _page("Cannot delete", body, author, current_path="/dashboard")
    body = f"""
    <div class="card" style="border-left:4px solid #c0392b">
        <h2>Delete submission?</h2>
        <p>You are about to permanently delete your submission
        <strong>&ldquo;{article['title']}&rdquo;</strong>
        (status: <span class="status-badge status-{status}">{status}</span>).</p>
        <p style="margin-top:0.5rem;color:#555;font-size:0.9rem">
            This removes the stored Markdown, any rendered HTML/PDF, and the
            submission record. This action cannot be undone.
        </p>
        <form method="post" action="/dashboard/delete/{article_id}" style="margin-top:1rem">
            <button type="submit" class="btn btn-danger">Yes, delete this submission</button>
            <a href="/dashboard" class="btn" style="margin-left:0.5rem">Cancel</a>
        </form>
    </div>
    """
    return _page("Delete submission?", body, author, current_path="/dashboard")


@router.post("/dashboard/delete/{article_id}", include_in_schema=False)
def dashboard_delete_submit(article_id: int, request: Request):
    """Delete an author's own pending/rejected submission, then redirect."""
    author = require_author(request)
    from articles import delete_article
    delete_article(article_id, author["id"])
    return RedirectResponse(url="/dashboard?deleted=1", status_code=303)


# ─── Author retraction (published articles) ────────────────────────────────
#
# A retraction is a new version of the article that goes through the normal
# moderation pipeline. On approval the ARK transfers to the retraction notice
# and the original is preserved as a superseded version. This keeps the
# scholarly record intact (the ARK persists, citations resolve to the
# retraction notice) — unlike hard delete, which would break external links.

@router.get("/dashboard/retract/{article_id}", include_in_schema=False, response_class=HTMLResponse)
def dashboard_retract_confirm(article_id: int, request: Request):
    """Confirmation page for retracting a published article."""
    author = require_author(request)
    with get_conn().connection() as conn:
        article = conn.execute(
            "SELECT id, title, status, version FROM articles WHERE id = %s",
            (article_id,),
        ).fetchone()
        if not article:
            raise HTTPException(404, "Article not found")
        is_author_row = conn.execute(
            "SELECT 1 FROM article_authors WHERE article_id = %s AND author_id = %s",
            (article_id, author["id"]),
        ).fetchone()
    if not is_author_row:
        raise HTTPException(403, "You can only retract your own articles")
    if article["status"] not in ("published", "superseded"):
        body = f"""
        <div class="card" style="border-left:4px solid #c0392b">
            <h2>Cannot retract this submission</h2>
            <p>Only published articles can be retracted. This submission is
            <strong>{article['status']}</strong>.
            {"Use the Delete button to remove a pending or rejected submission." if article['status'] in ('pending', 'rejected') else ""}</p>
            <p style="margin-top:1rem"><a href="/dashboard" class="btn">&larr; Back to My Submissions</a></p>
        </div>
        """
        return _page("Cannot retract", body, author, current_path="/dashboard")
    body = f"""
    <div class="card" style="border-left:4px solid #b48a00;background:#fffdf0">
        <h2>Retract this article</h2>
        <p>You are about to submit a <strong>retraction notice</strong> for
        <strong>&ldquo;{article['title']}&rdquo;</strong> (v{article['version']}).</p>
        <p style="margin-top:0.5rem;font-size:0.9rem;color:#555">
            A retraction is a new version of the article that goes through
            moderation. Once approved, the ARK will point to the retraction
            notice and the original will be preserved in the version history.
            The ARK stays valid — external citations will resolve to the
            retraction notice rather than silently breaking.
        </p>
        <form method="post" action="/dashboard/retract/{article_id}" style="margin-top:1rem">
            <div class="form-group">
                <label>Reason for retraction</label>
                <textarea name="reason" rows="4" required
                    placeholder="Explain why this article is being retracted (e.g. an error in the results, the data could not be reproduced...)"></textarea>
                <div class="hint">This text appears on the retraction notice page.</div>
            </div>
            <button type="submit" class="btn btn-danger">Submit retraction for review</button>
            <a href="/dashboard" class="btn" style="margin-left:0.5rem">Cancel</a>
        </form>
    </div>
    """
    return _page("Retract article?", body, author, current_path="/dashboard")


@router.post("/dashboard/retract/{article_id}", include_in_schema=False)
def dashboard_retract_submit(article_id: int, request: Request, reason: str = Form(...)):
    """Create a retraction version and send it through moderation."""
    author = require_author(request)
    from articles import create_retraction
    result = create_retraction(article_id, reason, author)
    return RedirectResponse(
        url=f"/submit/done/{result['id']}?retraction=1", status_code=303
    )


# ─── Profile page ──────────────────────────────────────────────────────────

@router.get("/profile", include_in_schema=False, response_class=HTMLResponse)
def profile_page(request: Request):
    """Author profile page with email settings."""
    author = require_author(request)
    with get_conn().connection() as conn:
        row = conn.execute(
            "SELECT id, orcid, name, email, affiliation, orcid_works_count, orcid_record_fetched_at FROM authors WHERE id = %s",
            (author["id"],),
        ).fetchone()
        article_count = conn.execute(
            "SELECT COUNT(*) AS c FROM articles WHERE submitted_by = %s", (author["id"],)
        ).fetchone()["c"]
        published_count = conn.execute(
            "SELECT COUNT(*) AS c FROM articles WHERE submitted_by = %s AND status = 'published'",
            (author["id"],),
        ).fetchone()["c"]

    email_value = row["email"] if row and row["email"] else ""
    affiliation_value = row["affiliation"] if row and row["affiliation"] else ""
    is_admin = author["orcid"] in config.admin_orcids
    works_count = row["orcid_works_count"] if row and row["orcid_works_count"] else 0
    fetched_at = row["orcid_record_fetched_at"] if row and row["orcid_record_fetched_at"] else None
    fetched_str = _format_date(fetched_at) if fetched_at else "never"

    AFFILIATION_OPTIONS = [
        "Independent Researcher",
        "Academic",
        "Industry",
        "Government",
        "Non-profit",
    ]

    saved = request.query_params.get("saved")
    saved_msg = ""
    if saved == "email":
        saved_msg = '<div class="card" style="background:#e8f5e9;border:1px solid #4caf50;margin-bottom:1.5rem;padding:1rem">Email saved successfully.</div>'
    elif saved == "affiliation":
        saved_msg = '<div class="card" style="background:#e8f5e9;border:1px solid #4caf50;margin-bottom:1.5rem;padding:1rem">Affiliation saved successfully.</div>'

    # Build affiliation dropdown
    aff_options_html = ""
    for opt in AFFILIATION_OPTIONS:
        selected = " selected" if opt == affiliation_value else ""
        aff_options_html += f'<option value="{opt}"{selected}>{opt}</option>'

    body = f"""
    <h1>{author['name']}</h1>
    {saved_msg}
    <div class="card" style="margin-bottom:1.5rem">
        <div class="meta" style="margin-bottom:0.5rem">
            <strong>ORCID:</strong>
            <a href="https://orcid.org/{author['orcid']}" target="_blank">{author['orcid']}</a>
        </div>
        <div class="meta" style="margin-bottom:0.5rem">
            <strong>Affiliation:</strong> {affiliation_value or '<span style="color:#888">Not set</span>'}
        </div>
        <div class="meta">
            <strong>Role:</strong> {'Administrator' if is_admin else 'Author'}
        </div>
        <div class="meta" style="margin-top:0.5rem">
            <strong>Articles:</strong> {published_count} published, {article_count - published_count} other
        </div>
        <div class="meta" style="margin-top:0.5rem">
            <strong>ORCID publications:</strong> {works_count}
            <span style="color:#888;font-size:0.85rem">(cached {fetched_str})</span>
        </div>
    </div>

    <div class="card" style="margin-bottom:1.5rem">
        <h2 style="font-size:1.1rem">Notification Settings</h2>
        <p style="font-size:0.9rem;color:#555;margin-bottom:1rem">
            Enter your email to receive notifications when your submissions are approved or rejected.
            ORCID's public API doesn't share email, so you need to add it here.
        </p>
        <form method="post" action="/profile/email">
            <div class="form-group">
                <label>Email for notifications (optional)</label>
                <input type="email" name="email" value="{email_value}" placeholder="you@example.com">
            </div>
            <button type="submit" class="btn btn-primary">Save email</button>
        </form>
    </div>

    <div class="card">
        <h2 style="font-size:1.1rem">Affiliation</h2>
        <form method="post" action="/profile/affiliation">
            <div class="form-group">
                <label>Your affiliation</label>
                <select name="affiliation">
                    <option value="">— Select —</option>
                    {aff_options_html}
                </select>
            </div>
            <button type="submit" class="btn btn-primary">Save affiliation</button>
        </form>
    </div>

    <div style="margin-top:1.5rem">
        <a href="/dashboard">&larr; My Submissions</a>
    </div>
    """
    return _page("Profile", body, author, current_path="/profile")


@router.post("/profile/email", include_in_schema=False)
def update_profile_email(request: Request, email: str = Form(default="")):
    """Handle email form submission from profile page."""
    import re
    author = require_author(request)
    email = email.strip() if email else ""
    if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(400, "Invalid email address")
    with get_conn().connection() as conn:
        conn.execute(
            "UPDATE authors SET email = %s WHERE id = %s",
            (email or None, author["id"]),
        )
        conn.commit()
    return RedirectResponse(url="/profile?saved=email", status_code=303)


@router.post("/profile/affiliation", include_in_schema=False)
def update_profile_affiliation(request: Request, affiliation: str = Form(default="")):
    """Handle affiliation form submission from profile page."""
    author = require_author(request)
    affiliation = affiliation.strip() if affiliation else ""
    with get_conn().connection() as conn:
        conn.execute(
            "UPDATE authors SET affiliation = %s WHERE id = %s",
            (affiliation or None, author["id"]),
        )
        conn.commit()
    return RedirectResponse(url="/profile?saved=affiliation", status_code=303)


# ─── Admin page ────────────────────────────────────────────────────────────

@router.get("/admin", include_in_schema=False, response_class=HTMLResponse)
def admin_page(request: Request, withdrawn: str = ""):
    """Admin moderation queue and stats."""
    reviewer = require_reviewer(request)
    is_admin = _is_admin(reviewer)
    withdrawn_banner = ""
    if withdrawn:
        withdrawn_banner = (
            '<div class="card" style="margin-bottom:1.5rem;border-left:4px solid #c0392b;background:#fdf0f0">'
            "Article withdrawn. The ARK now resolves to a tombstone page.</div>"
        )
    with get_conn().connection() as conn:
        pending = conn.execute(
            """SELECT a.id, a.title, a.submitted_at,
                      au.name as submitter_name, au.orcid as submitter_orcid
               FROM articles a
               LEFT JOIN authors au ON a.submitted_by = au.id
               WHERE a.status = 'pending'
               ORDER BY a.submitted_at ASC""",
        ).fetchall()
        stats = {
            "total_articles": conn.execute("SELECT COUNT(*) as c FROM articles WHERE status = 'published'").fetchone()["c"],
            "total_downloads": conn.execute("SELECT COUNT(*) as c FROM downloads").fetchone()["c"],
            "agent_downloads": conn.execute("SELECT COUNT(*) as c FROM downloads WHERE is_agent = true").fetchone()["c"],
            "human_downloads": conn.execute("SELECT COUNT(*) as c FROM downloads WHERE is_agent = false").fetchone()["c"],
            "pending": len(pending),
        }
        recent = conn.execute(
            """SELECT a.id, a.ark, a.title, a.status, a.published_at
               FROM articles a
               ORDER BY a.submitted_at DESC LIMIT 10""",
        ).fetchall()

    stats_html = f"""
    <div class="stats-grid">
        <div class="stat-card"><div class="num">{stats['total_articles']}</div><div class="label">Published</div></div>
        <div class="stat-card"><div class="num">{stats['pending']}</div><div class="label">Pending</div></div>
        <div class="stat-card"><div class="num">{stats['total_downloads']}</div><div class="label">Downloads</div></div>
        <div class="stat-card"><div class="num">{stats['agent_downloads']}</div><div class="label">Agent downloads</div></div>
        <div class="stat-card"><div class="num">{stats['human_downloads']}</div><div class="label">Human downloads</div></div>
    </div>"""

    if pending:
        # Fetch screening reports for pending submissions
        from screening import get_screening_report
        pending_cards = []
        for p in pending:
            submitted = _format_date(p.get("submitted_at"))
            # Get screening report if available
            screening = get_screening_report(p["id"])
            screening_html = ""
            if screening:
                if screening["verdict"] == "auto_approve":
                    screening_html = '<div class="meta" style="margin-top:0.5rem"><span class="status-badge status-published">Screening: auto-approve</span></div>'
                elif screening["verdict"] == "flag_for_review":
                    flags = ""
                    if screening["report"] and screening["report"].get("flags"):
                        flags = " — " + ", ".join(screening["report"]["flags"])
                    screening_html = f'<div class="meta" style="margin-top:0.5rem"><span class="status-badge status-pending" style="background:#fffdf0;color:#b48a00;border:1px solid #b48a00">Screening: flagged{flags}</span></div>'
                elif screening["error"]:
                    screening_html = f'<div class="meta" style="margin-top:0.5rem"><span class="status-badge status-rejected">Screening error: {screening["error"]}</span></div>'
            pending_cards.append(f"""<div class="card">
<h2>{p['title']}</h2>
<div class="meta">Submitted by <a href="/author/{p['submitter_orcid']}">{p['submitter_name']}</a> on {submitted}</div>
{screening_html}
<div style="margin-top:1rem;display:flex;gap:0.5rem">
    <a href="/admin/submission/{p['id']}" class="btn btn-primary">Review</a>
    <form method="post" action="/admin/articles/{p['id']}" style="display:inline">
        <input type="hidden" name="action" value="approve">
        <button type="submit" class="btn">Approve</button>
    </form>
    <form method="post" action="/admin/articles/{p['id']}" style="display:inline">
        <input type="hidden" name="action" value="reject">
        <button type="submit" class="btn btn-danger">Reject</button>
    </form>
</div>
</div>""")
        queue_html = f"<h2>Moderation Queue</h2>{''.join(pending_cards)}"
    else:
        queue_html = '<div class="empty"><h3>No pending submissions</h3></div>'

    if recent:
        recent_cards = []
        for r in recent:
            status_class = f"status-{r['status']}"
            link = f'<a href="/article/{r["ark"]}">{r["title"]}</a>' if r["ark"] else r["title"]
            recent_cards.append(f"""<div class="card">
<h2>{link}</h2>
<div class="meta"><span class="status-badge {status_class}">{r['status']}</span> &middot; ID: {r['id']}</div>
</div>""")
        recent_html = f"<h2>Recent Activity</h2>{''.join(recent_cards)}"
    else:
        recent_html = ""

    admin_links = ""
    if is_admin:
        admin_links = '<div style="margin-top:1rem;display:flex;gap:0.5rem;flex-wrap:wrap"><a href="/admin/authors" class="btn">Author Management</a><a href="/admin/roles" class="btn">Role Management</a></div>'

    body = f"""
    <h1>{'Admin' if is_admin else 'Reviewer'} Dashboard</h1>
    {withdrawn_banner}
    {stats_html}
    {queue_html}
    {recent_html}
    {admin_links}
    """
    return _page("Moderation", body, reviewer, current_path="/admin")


# ─── Admin submission detail page ──────────────────────────────────────────

@router.get("/admin/submission/{article_id}", include_in_schema=False, response_class=HTMLResponse)
def admin_submission_detail(article_id: int, request: Request):
    """View submission details (reviewer or admin)."""
    reviewer = require_reviewer(request)
    is_admin = _is_admin(reviewer)
    with get_conn().connection() as conn:
        article = conn.execute(
            "SELECT * FROM articles WHERE id = %s", (article_id,)
        ).fetchone()
        if not article:
            raise HTTPException(404, "Submission not found")
        authors = conn.execute(
            """SELECT a.orcid, a.name, a.affiliation
               FROM authors a
               JOIN article_authors aa ON a.id = aa.author_id
               WHERE aa.article_id = %s
               ORDER BY aa."order\"""",
            (article_id,),
        ).fetchall()
        submitter = conn.execute(
            "SELECT name, orcid FROM authors WHERE id = %s", (article["submitted_by"],)
        ).fetchone() if article.get("submitted_by") else None

    authors_html = "".join(
        f"<li><a href='/author/{a['orcid']}'>{a['name']}</a> ({a['orcid']})" +
        (f" &mdash; {a['affiliation']}" if a.get('affiliation') else "") +
        "</li>"
        for a in authors
    )

    # Screening report (if automated screening ran)
    from screening import get_screening_report
    screening = get_screening_report(article_id)
    screening_section = ""
    if screening:
        verdict_label = {
            "auto_approve": "Auto-approved (clean)",
            "flag_for_review": "Flagged for human review",
            "screening_failed": "Screening failed",
            "screening_disabled": "Screening not enabled",
        }.get(screening["verdict"], screening["verdict"])
        report_details = ""
        if screening["report"]:
            r = screening["report"]
            flags_html = ", ".join(r.get("flags", [])) or "none"
            report_details = f"""
            <p><strong>format_ok:</strong> {r.get('format_ok')}</p>
            <p><strong>in_scope:</strong> {r.get('in_scope')}</p>
            <p><strong>spam_likelihood:</strong> {r.get('spam_likelihood')}</p>
            <p><strong>has_abstract:</strong> {r.get('has_abstract')}</p>
            <p><strong>has_references:</strong> {r.get('has_references')}</p>
            <p><strong>has_jailbreak:</strong> {r.get('has_jailbreak')}</p>
            <p><strong>has_prohibited_content:</strong> {r.get('has_prohibited_content')}</p>
            <p><strong>flags:</strong> {flags_html}</p>
            <p><strong>summary:</strong> {r.get('summary', '')}</p>
            """
        elif screening["error"]:
            report_details = f"<p><strong>Error:</strong> {screening['error']}</p>"
        screening_section = f"""
    <div class="card">
        <h3>Automated Screening Report</h3>
        <p><strong>Verdict:</strong> {verdict_label} &middot; <strong>Model:</strong> {screening['model']}</p>
        {report_details}
    </div>
    """

    # Show a preview of the markdown (first 2000 chars)
    md_preview = article["source_markdown"][:2000]
    if len(article["source_markdown"]) > 2000:
        md_preview += "\n\n... (truncated)"

    body = f"""
    <h1>{article['title']}</h1>
    <div style="margin-bottom:1.5rem">
        <span class="status-badge status-{article['status']}">{article['status']}</span>
        &middot; Submitted {_format_date(article.get('submitted_at'))}
        {f'&middot; by <a href="/author/{submitter["orcid"]}">{submitter["name"]}</a>' if submitter else ''}
    </div>

    <div class="card">
        <h3>Authors</h3>
        <ul style="margin-left:1.5rem;margin-top:0.5rem">{authors_html}</ul>
    </div>

    {f'<div class="card"><h3>Abstract</h3><p>{article["abstract"]}</p></div>' if article.get('abstract') else ''}

    {f'<div class="card"><h3>Subjects</h3><p>{", ".join(article["subjects"])}</p></div>' if article.get('subjects') else ''}

    {screening_section}

    <div class="card">
        <h3>Markdown Preview</h3>
        <pre style="white-space:pre-wrap;font-family:'IBM Plex Mono',monospace;font-size:0.85rem;background:rgba(0,0,0,0.03);padding:1rem;border-radius:4px;overflow-x:auto">{md_preview}</pre>
    </div>

    {f'''
    <div style="display:flex;gap:0.5rem;margin-top:1.5rem">
        <form method="post" action="/admin/articles/{article_id}" style="display:inline">
            <input type="hidden" name="action" value="approve">
            <button type="submit" class="btn btn-primary">Approve &amp; Publish</button>
        </form>
        <form method="post" action="/admin/articles/{article_id}" style="display:inline">
            <input type="hidden" name="action" value="reject">
            <button type="submit" class="btn btn-danger">Reject</button>
        </form>
    </div>
    ''' if article['status'] == 'pending' else ''}

    {f'''
    <div class="card" style="margin-top:1.5rem;border-left:4px solid #c0392b">
        <h3 style="color:#c0392b">Withdraw this article</h3>
        <p style="font-size:0.9rem;color:#555">
            Withdrawal removes the content from public access but keeps the ARK
            resolving to a tombstone page. Use this for DMCA/DSA takedowns,
            research-integrity findings, or legal orders. A reason is required
            and is recorded for audit.
        </p>
        <form method="post" action="/admin/articles/{article_id}/withdraw" style="margin-top:0.5rem">
            <div class="form-group">
                <label>Reason (required)</label>
                <input type="text" name="reason" required
                    placeholder="e.g. DMCA notice #123, integrity case #456">
            </div>
            <button type="submit" class="btn btn-danger">Withdraw article</button>
        </form>
    </div>
    ''' if is_admin and article['status'] == 'published' else ''}

    {f'''
    <div class="card" style="margin-top:1.5rem;border-left:4px solid #b48a00">
        <h3 style="color:#b48a00">Author management (CoC enforcement)</h3>
        <p style="font-size:0.9rem;color:#555">
            Suspend or ban this submission's author for Code of Conduct violations.
            Suspended authors cannot submit new papers. Banned authors cannot log in.
            Existing published work is preserved in both cases.
        </p>
        <form method="post" action="/admin/authors/{article["submitted_by"]}/suspend" style="margin-top:0.5rem;display:inline">
            <input type="text" name="reason" required placeholder="CoC violation reason"
                style="width:300px;display:inline-block;margin-right:0.5rem">
            <button type="submit" class="btn btn-danger">Suspend author</button>
        </form>
        <form method="post" action="/admin/authors/{article["submitted_by"]}/ban" style="margin-top:0.5rem;display:inline">
            <input type="text" name="reason" required placeholder="CoC violation reason"
                style="width:300px;display:inline-block;margin-right:0.5rem">
            <button type="submit" class="btn btn-danger">Ban author</button>
        </form>
    </div>
    ''' if is_admin and article.get('submitted_by') else ''}

    <div style="margin-top:1.5rem"><a href="/admin">&larr; Back to queue</a></div>
    """
    return _page(f"Submission: {article['title']}", body, reviewer)


@router.post("/admin/articles/{article_id}/withdraw", include_in_schema=False)
def admin_withdraw_submit(article_id: int, request: Request, reason: str = Form("")):
    """Withdraw a published article (admin only, recorded reason)."""
    admin = require_admin(request)
    from articles import withdraw_article
    withdraw_article(article_id, reason, admin)
    return RedirectResponse(url="/admin?withdrawn=1", status_code=303)


# ─── Admin form-based moderation (POST handler for HTML forms) ─────────────

class ModerationForm(BaseModel):
    action: str
    note: str = ""


@router.post("/admin/articles/{article_id}", include_in_schema=False)
def moderate_article_form(
    article_id: int,
    request: Request,
    action: str = "",
    note: str = "",
):
    """Handle form-based moderation (redirects back to admin)."""
    reviewer = require_reviewer(request)
    from articles import moderate_article as _mod
    # Call the API handler
    result = _mod(article_id, ModerationForm(action=action, note=note), reviewer)
    # Redirect back to admin
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/admin/authors/{author_id}/suspend", include_in_schema=False)
def admin_suspend_author(author_id: int, request: Request, reason: str = Form(...)):
    """Suspend an author via HTML form (admin only)."""
    admin = require_admin(request)
    from articles import AuthorStatusAction, update_author_status
    update_author_status(author_id, AuthorStatusAction(status="suspended", reason=reason), admin)
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/admin/authors/{author_id}/ban", include_in_schema=False)
def admin_ban_author(author_id: int, request: Request, reason: str = Form(...)):
    """Ban an author via HTML form (admin only)."""
    admin = require_admin(request)
    from articles import AuthorStatusAction, update_author_status
    update_author_status(author_id, AuthorStatusAction(status="banned", reason=reason), admin)
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/admin/authors/{author_id}/reactivate", include_in_schema=False)
def admin_reactivate_author(author_id: int, request: Request):
    """Reactivate a suspended/banned author (admin only)."""
    admin = require_admin(request)
    from articles import AuthorStatusAction, update_author_status
    update_author_status(author_id, AuthorStatusAction(status="active"), admin)
    return RedirectResponse(url="/admin/authors", status_code=303)


@router.get("/admin/authors", include_in_schema=False, response_class=HTMLResponse)
def admin_authors_page(request: Request, status: str = "", q: str = ""):
    """Author management page (admin only)."""
    admin = require_admin(request)
    search_term = q.strip()
    with get_conn().connection() as conn:
        if search_term:
            like = f"%{search_term}%"
            if status:
                rows = conn.execute(
                    """SELECT id, orcid, github_id, name, email, affiliation,
                              account_status, status_reason, status_changed_at,
                              created_at
                       FROM authors
                       WHERE account_status = %s
                         AND (name ILIKE %s OR orcid ILIKE %s OR github_id ILIKE %s OR email ILIKE %s)
                       ORDER BY status_changed_at DESC NULLS LAST, created_at DESC""",
                    (status, like, like, like, like),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT id, orcid, github_id, name, email, affiliation,
                              account_status, status_reason, status_changed_at,
                              created_at
                       FROM authors
                       WHERE name ILIKE %s OR orcid ILIKE %s OR github_id ILIKE %s OR email ILIKE %s
                       ORDER BY
                         CASE account_status
                             WHEN 'banned' THEN 0
                             WHEN 'suspended' THEN 1
                             ELSE 2
                         END, created_at DESC""",
                    (like, like, like, like),
                ).fetchall()
        elif status:
            rows = conn.execute(
                """SELECT id, orcid, github_id, name, email, affiliation,
                          account_status, status_reason, status_changed_at,
                          created_at
                   FROM authors WHERE account_status = %s
                   ORDER BY status_changed_at DESC NULLS LAST, created_at DESC""",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, orcid, github_id, name, email, affiliation,
                          account_status, status_reason, status_changed_at,
                          created_at
                   FROM authors ORDER BY
                   CASE account_status
                       WHEN 'banned' THEN 0
                       WHEN 'suspended' THEN 1
                       ELSE 2
                   END, created_at DESC""",
            ).fetchall()

    # Search box
    search_box = f'''<form method="get" action="/admin/authors" style="margin-bottom:1rem;display:flex;gap:0.5rem;align-items:center">
        <input type="text" name="q" value="{q}" placeholder="Search name, ORCID, GitHub, or email" style="flex:1;max-width:400px;padding:0.4rem 0.6rem;border:1px solid var(--rule);border-radius:4px;font-size:0.9rem">
        <button type="submit" class="btn">Search</button>
        {f'<a href="/admin/authors" class="btn">Clear</a>' if q else ''}
    </form>'''

    filter_links = '<div style="margin-bottom:1rem;display:flex;gap:0.5rem">'
    for label, val in [("All", ""), ("Active", "active"), ("Suspended", "suspended"), ("Banned", "banned")]:
        qs = f"?status={val}" if val else ""
        if q:
            qs += f"&q={q}" if not qs else f"&q={q}"
            qs = f"?q={q}&status={val}" if val else f"?q={q}"
        cls = 'btn btn-primary' if (val == status) else 'btn'
        filter_links += f'<a href="/admin/authors{qs}" class="{cls}">{label}</a>'
    filter_links += '</div>'

    cards = []
    for a in rows:
        status_badge = {
            "active": '<span class="status-badge status-published">active</span>',
            "suspended": '<span class="status-badge status-pending" style="background:#fffdf0;color:#b48a00;border:1px solid #b48a00">suspended</span>',
            "banned": '<span class="status-badge status-rejected">banned</span>',
        }.get(a["account_status"], a["account_status"])

        reason_html = f'<div class="meta" style="margin-top:0.25rem"><strong>Reason:</strong> {a["status_reason"]}</div>' if a.get("status_reason") else ''
        changed_html = f'<div class="meta" style="margin-top:0.25rem">Changed: {_format_date(a.get("status_changed_at"))}</div>' if a.get("status_changed_at") else ''

        actions = ''
        is_env_admin = (a["orcid"] and a["orcid"] in config.admin_orcids) or (a.get("github_id") and a["github_id"] in config.admin_github_ids)
        if a["account_status"] != "active" and not is_env_admin:
            actions = f'''<form method="post" action="/admin/authors/{a["id"]}/reactivate" style="margin-top:0.5rem;display:inline">
                <button type="submit" class="btn btn-primary">Reactivate</button>
            </form>'''
        elif a["account_status"] == "active" and not is_env_admin:
            actions = f'''<div style="margin-top:0.5rem;display:flex;gap:0.5rem;flex-wrap:wrap">
                <form method="post" action="/admin/authors/{a["id"]}/suspend" style="display:inline">
                    <input type="text" name="reason" required placeholder="Reason" style="width:200px;display:inline-block">
                    <button type="submit" class="btn btn-danger">Suspend</button>
                </form>
                <form method="post" action="/admin/authors/{a["id"]}/ban" style="display:inline">
                    <input type="text" name="reason" required placeholder="Reason" style="width:200px;display:inline-block">
                    <button type="submit" class="btn btn-danger">Ban</button>
                </form>
            </div>'''
        elif is_env_admin:
            actions = '<div class="meta" style="margin-top:0.5rem;color:var(--muted)"><em>Admin account (env) — cannot be modified</em></div>'

        orcid_display = a["orcid"] or ""
        github_display = f' &middot; GitHub: {a["github_id"]}' if a.get("github_id") else ""
        cards.append(f"""<div class="card">
<h2>{a['name']}</h2>
<div class="meta">{status_badge} &middot; {orcid_display}{github_display} &middot; Joined {_format_date(a.get('created_at'))}</div>
{reason_html}
{changed_html}
{actions}
</div>""")

    body = f"""
    <h1>Author Management</h1>
    <p style="color:var(--ink-soft);margin-bottom:1rem">
        Suspend or ban authors for Code of Conduct violations. Suspended authors
        cannot submit new papers. Banned authors cannot log in. Existing
        published work is preserved in both cases.
    </p>
    {search_box}
    {filter_links}
    {''.join(cards) if cards else '<div class="empty"><h3>No authors found</h3></div>'}
    <div style="margin-top:1.5rem"><a href="/admin">&larr; Back to dashboard</a></div>
    """
    return _page("Author Management", body, admin, current_path="/admin/authors")


@router.get("/admin/roles", include_in_schema=False, response_class=HTMLResponse)
def admin_roles_page(request: Request, q: str = ""):
    """Role management page (admin only) — promote/demote authors to reviewer or admin."""
    admin = require_admin(request)
    search_term = q.strip()
    with get_conn().connection() as conn:
        if search_term:
            like = f"%{search_term}%"
            rows = conn.execute(
                """SELECT id, orcid, github_id, name, email, role,
                          account_status, created_at
                   FROM authors
                   WHERE name ILIKE %s OR orcid ILIKE %s OR github_id ILIKE %s OR email ILIKE %s
                   ORDER BY
                     CASE WHEN role = 'admin' THEN 0
                          WHEN role = 'reviewer' THEN 1
                          ELSE 2 END,
                     created_at DESC""",
                (like, like, like, like),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, orcid, github_id, name, email, role,
                          account_status, created_at
                   FROM authors ORDER BY
                     CASE WHEN role = 'admin' THEN 0
                          WHEN role = 'reviewer' THEN 1
                          ELSE 2 END,
                     created_at DESC""",
            ).fetchall()

    search_box = f'''<form method="get" action="/admin/roles" style="margin-bottom:1rem;display:flex;gap:0.5rem;align-items:center">
        <input type="text" name="q" value="{q}" placeholder="Search name, ORCID, GitHub, or email" style="flex:1;max-width:400px;padding:0.4rem 0.6rem;border:1px solid var(--rule);border-radius:4px;font-size:0.9rem">
        <button type="submit" class="btn">Search</button>
        {f'<a href="/admin/roles" class="btn">Clear</a>' if q else ''}
    </form>'''

    cards = []
    for a in rows:
        db_role = a["role"]
        is_env_admin = (a["orcid"] and a["orcid"] in config.admin_orcids) or (a.get("github_id") and a["github_id"] in config.admin_github_ids)
        is_env_reviewer = (a["orcid"] and a["orcid"] in config.reviewer_orcids) or (a.get("github_id") and a["github_id"] in config.reviewer_github_ids)
        is_self = a["id"] == admin["id"]

        role_badge = {
            "admin": '<span class="status-badge status-published">admin</span>',
            "reviewer": '<span class="status-badge status-pending" style="background:#fffdf0;color:#b48a00;border:1px solid #b48a00">reviewer</span>',
            "author": '<span class="status-badge" style="background:#f0f0f0;color:#666">author</span>',
        }.get(db_role, db_role)

        env_note = ""
        if is_env_admin:
            env_note = ' <span style="color:var(--muted);font-size:0.8rem">(env: admin)</span>'
        elif is_env_reviewer:
            env_note = ' <span style="color:var(--muted);font-size:0.8rem">(env: reviewer)</span>'

        actions = ""
        if is_self:
            actions = '<div class="meta" style="margin-top:0.5rem;color:var(--muted)"><em>This is you — cannot change your own role</em></div>'
        elif is_env_admin:
            actions = '<div class="meta" style="margin-top:0.5rem;color:var(--muted)"><em>Env-var admin — cannot be changed via UI</em></div>'
        else:
            buttons = []
            if db_role != "reviewer":
                buttons.append(f'''<form method="post" action="/admin/roles/{a["id"]}" style="display:inline">
                    <input type="hidden" name="role" value="reviewer">
                    <button type="submit" class="btn">Make Reviewer</button>
                </form>''')
            if db_role != "admin":
                buttons.append(f'''<form method="post" action="/admin/roles/{a["id"]}" style="display:inline">
                    <input type="hidden" name="role" value="admin">
                    <button type="submit" class="btn btn-primary">Make Admin</button>
                </form>''')
            if db_role != "author":
                buttons.append(f'''<form method="post" action="/admin/roles/{a["id"]}" style="display:inline">
                    <input type="hidden" name="role" value="author">
                    <button type="submit" class="btn btn-danger">Remove Role</button>
                </form>''')
            actions = f'<div style="margin-top:0.5rem;display:flex;gap:0.5rem;flex-wrap:wrap">{"".join(buttons)}</div>'

        orcid_display = a["orcid"] or ""
        github_display = f' &middot; GitHub: {a["github_id"]}' if a.get("github_id") else ""
        github_form = f'''<form method="post" action="/admin/authors/{a["id"]}/github" style="margin-top:0.5rem;display:flex;gap:0.5rem;align-items:center;flex-wrap:wrap">
            <label style="font-size:0.85rem;color:var(--muted)">GitHub handle:</label>
            <input type="text" name="github_id" value="{a["github_id"] or ""}" placeholder="username" style="width:150px;padding:0.3rem 0.5rem;border:1px solid var(--rule);border-radius:4px;font-size:0.85rem">
            <button type="submit" class="btn" style="font-size:0.8rem">Save</button>
        </form>'''
        cards.append(f"""<div class="card">
<h2>{a['name']}{env_note}</h2>
<div class="meta">{role_badge} &middot; {orcid_display}{github_display} &middot; Joined {_format_date(a.get('created_at'))}</div>
{actions}
{github_form}
</div>""")

    body = f"""
    <h1>Role Management</h1>
    <p style="color:var(--ink-soft);margin-bottom:1rem">
        Promote authors to reviewer or admin, or remove their role. Reviewers
        can approve and reject submissions. Admins can additionally withdraw
        articles, suspend/ban authors, and manage roles. Users configured via
        environment variables (ADMIN_ORCIDS, REVIEWER_ORCIDS, etc.) are shown
        with an <em>(env)</em> note and cannot be changed here.
    </p>
    {search_box}
    {''.join(cards) if cards else '<div class="empty"><h3>No authors found</h3></div>'}
    <div style="margin-top:1.5rem"><a href="/admin">&larr; Back to dashboard</a></div>
    """
    return _page("Role Management", body, admin, current_path="/admin/roles")


@router.post("/admin/roles/{author_id}", include_in_schema=False)
def admin_roles_update(request: Request, author_id: int, role: str = Form(...)):
    """Update an author's role via the HTML form (admin only)."""
    from articles import update_author_role, RoleAction
    admin = require_admin(request)
    update_author_role(author_id, RoleAction(role=role), admin)
    return RedirectResponse(url="/admin/roles", status_code=303)


@router.post("/admin/authors/{author_id}/github", include_in_schema=False)
def admin_github_update(request: Request, author_id: int, github_id: str = Form("")):
    """Update an author's GitHub handle via the HTML form (admin only)."""
    from articles import update_author_github, GitHubHandleUpdate
    admin = require_admin(request)
    handle = github_id.strip() if github_id else ""
    update_author_github(author_id, GitHubHandleUpdate(github_id=handle or None), admin)
    return RedirectResponse(url="/admin/roles", status_code=303)
