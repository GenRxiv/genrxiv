"""
GenRxiv API — web UI pages (HTML).

Simple server-rendered pages using Jinja2 templates:
- /submit — submission form
- /dashboard — author's submissions
- /admin — moderation queue and stats
- /browse — article listing
- /author/{orcid} — author profile page
- /keywords — keyword cloud
"""
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from config import config
from db import get_conn
from auth import get_current_author, require_author, require_admin
from orcid_client import fetch_orcid_works_count

router = APIRouter()

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
    return f'<select name="keywords" multiple size="10" required style="width:100%;padding:0.6rem;border:1px solid var(--border);border-radius:4px;font-size:1rem;font-family:inherit">{options}</select>'


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
.card .keywords { margin-top: 0.5rem; }
.card .keywords a {
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
.keyword-cloud { display: flex; flex-wrap: wrap; gap: 0.5rem; }
.keyword-cloud a {
    background: #fff;
    border: 1px solid var(--border);
    padding: 0.3rem 0.8rem;
    border-radius: 4px;
    color: var(--ink);
}
.keyword-cloud a:hover { border-color: var(--cobalt); color: var(--cobalt); }
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
        auth_area = (
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
            f'{submit_link}'
        )
    return f"""<nav style="display:flex;justify-content:space-between;align-items:center;padding:0.6rem 1.5rem;border-bottom:1px solid var(--rule);font-size:0.9rem">
<div style="display:flex;gap:1.2rem;align-items:center">
<a href="/" style="font-weight:600;color:var(--accent);text-decoration:none">{config.site_name}</a>
{nav_link("/browse", "Browse")}
{nav_link("/keywords", "Keywords")}
{nav_link("/stats", "Stats")}
<a href="/feed.xml" style="color:var(--ink);text-decoration:none">Feed</a>
</div>
<div style="display:flex;gap:0.8rem;align-items:center">
{auth_area}
</div>
</nav>"""


def _footer_html() -> str:
    return f"""<footer>
<p>{config.site_name} &mdash; An open archive for AI-generated research.</p>
<p><a href="/api/articles">API</a> &middot; <a href="/oai?verb=Identify">OAI-PMH</a> &middot; <a href="/feed.xml">Feed</a> &middot; <a href="/sitemap.xml">Sitemap</a> &middot; <a href="/robots.txt">robots.txt</a></p>
</footer>"""


def _page(
    title: str,
    body: str,
    author: dict | None = None,
    extra_css: str = "",
    extra_js: str = "",
    raw_title: bool = False,
    wrap_container: bool = True,
    current_path: str = "",
) -> HTMLResponse:
    """Render a full HTML page."""
    page_title = title if raw_title else f"{title} &middot; {config.site_name}"
    if wrap_container:
        body = f'<div class="container">\n{body}\n</div>'
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{page_title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,500;0,9..144,600;1,9..144,400&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<link rel="icon" href="/mark.svg" type="image/svg+xml">
<link rel="alternate" type="application/atom+xml" title="{config.site_name} — Recent Articles" href="/feed.xml">
<style>{PAGE_CSS}{extra_css}</style>
</head>
<body>
{_header_html(author, current_path)}
{body}
{_footer_html()}
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


def _article_card(article: dict, show_endorsements: bool = False) -> str:
    """Render an article card."""
    ark = article.get("ark", "")
    title = article.get("title", "Untitled")
    abstract = article.get("abstract") or ""
    keywords = article.get("keywords", [])
    published = _format_date(article.get("published_at"))
    kw_html = " ".join(
        f'<a href="/keywords/{quote(k)}">{k}</a>' for k in keywords
    ) if keywords else ""
    authors_html = ""
    if "authors" in article and article["authors"]:
        authors_html = "<div class='meta'>" + ", ".join(
            f'<a href="/author/{a["orcid"]}">{a["name"]}</a>' for a in article["authors"]
        ) + "</div>"
    elif "author_names" in article and article["author_names"]:
        authors_html = f"<div class='meta'>{article['author_names']}</div>"
    return f"""<div class="card">
<h2><a href="/article/{ark}">{title}</a></h2>
{authors_html}
{f'<div class="abstract">{abstract}</div>' if abstract else ''}
{f'<div class="keywords">{kw_html}</div>' if kw_html else ''}
<div class="meta">Published {published} &middot; ARK: {ark}</div>
</div>"""


# ─── ORCID lookup for co-author entry ──────────────────────────────────────

@router.get("/api/orcid-lookup/{orcid}")
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


@router.get("/", response_class=HTMLResponse)
def splash_page(request: Request):
    """Splash page — served through FastAPI so it shares the nav with all pages."""
    author = get_current_author(request)
    body = """
<div class="splash">
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

    <p class="status"><span class="dot"></span>Now accepting submissions &mdash; building in the open</p>

    <p>
        GenRxiv is a preprint archive for research substantially generated or
        co-generated by AI, submitted in Markdown and openly available to
        human and machine readers alike. We're building the archive itself
        before we open submissions, and we'd like the community involved from
        here, not just after launch.
    </p>

    <h3>Planned subject areas</h3>
    <div class="subjects">
        <span class="subject-tag">Life Sciences</span>
        <span class="subject-tag">Physical Sciences</span>
        <span class="subject-tag">Computer Science</span>
        <span class="subject-tag">Social Sciences</span>
        <span class="subject-tag">Humanities</span>
        <span class="subject-tag">Interdisciplinary</span>
    </div>

    <h3>What a GenRxiv preprint looks like</h3>
    <div class="paper-card">
        <div class="paper-meta">genrxiv:2026.00001 &middot; posted 2026-01-15</div>
        <h4>Emergent Symbolic Reasoning in Multi-Agent LLM Systems Under Constrained Communication Bandwidth</h4>
        <p class="paper-authors">A. Chen, R. Okafor, with assistance from Claude 3.5 (Anthropic)</p>
        <p class="paper-abstract">
            We demonstrate that groups of large language models, when restricted to
            low-bandwidth symbolic channels, spontaneously develop compositional
            protocols resembling human mathematical notation. We characterize the
            conditions under which this emergence occurs and propose a framework&hellip;
        </p>
        <div class="paper-badges">
            <span class="badge badge-ai">AI co-generated</span>
            <span class="badge badge-format">Markdown</span>
            <span class="badge badge-status">Preprint</span>
        </div>
    </div>

    <h3>Submission standards</h3>
    <p>
        GenRxiv starts from the assumption that AI was involved. That's the
        premise, not the exception. So there's one rule: state plainly what
        the AI did. A single honest sentence is enough &mdash; "drafted by an LLM,
        verified and revised by the authors" or "fully generated, checked for
        accuracy." The disclosure is about honesty, not paperwork.
    </p>
    <p>
        Beyond that: submit in Markdown (there's a ready-made
        <a href="https://github.com/GenRxiv/genrxiv/blob/main/docs/AUTHOR_PROMPT.md">author prompt</a>
        that produces the right format from any LLM), attribute authorship to
        humans with an ORCID iD, and license the work openly.
    </p>

    <h3>Roadmap</h3>
    <div class="roadmap">
        <div class="roadmap-item">
            <span class="roadmap-status done">Done</span>
            <span class="roadmap-label">Platform infrastructure (FastAPI, PostgreSQL, conversion service)</span>
        </div>
        <div class="roadmap-item">
            <span class="roadmap-status done">Done</span>
            <span class="roadmap-label">Markdown to HTML &amp; PDF rendering (KaTeX math, print-ready)</span>
        </div>
        <div class="roadmap-item">
            <span class="roadmap-status done">Done</span>
            <span class="roadmap-label">ORCID author identity and OAuth login</span>
        </div>
        <div class="roadmap-item">
            <span class="roadmap-status done">Done</span>
            <span class="roadmap-label">Machine-readable access (OAI-PMH, sitemap, JSON-LD, ARK identifiers)</span>
        </div>
        <div class="roadmap-item">
            <span class="roadmap-status done">Done</span>
            <span class="roadmap-label">Nightly backups, email delivery, submission policies</span>
        </div>
        <div class="roadmap-item">
            <span class="roadmap-status active">Active</span>
            <span class="roadmap-label">End-to-end submission testing</span>
        </div>
        <div class="roadmap-item">
            <span class="roadmap-status planned">Planned</span>
            <span class="roadmap-label">Open submissions go live</span>
        </div>
        <div class="roadmap-item">
            <span class="roadmap-status planned">Planned</span>
            <span class="roadmap-label">Community moderation and endorsement system</span>
        </div>
    </div>

    <h2>Get involved</h2>
    <p>
        Leave your email if you'd like to help shape GenRxiv &mdash; as an early
        contributor, reviewer, or just a second pair of eyes.
    </p>

    <form id="interest-form">
        <label class="field-label" for="email">Email</label>
        <input type="email" id="email" name="email" placeholder="you@example.com" required>
        <div class="checkbox-row">
            <input type="checkbox" id="notify" name="notify_on_launch" value="yes">
            <label for="notify">Notify me when GenRxiv goes live</label>
        </div>
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
        extra_css=SPLASH_CSS,
        extra_js=SPLASH_JS,
        raw_title=True,
        wrap_container=False,
    )


# ─── Browse page ───────────────────────────────────────────────────────────

@router.get("/browse", response_class=HTMLResponse)
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
                f"""SELECT a.id, a.ark, a.title, a.abstract, a.keywords, a.published_at,
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
                f"""SELECT a.id, a.ark, a.title, a.abstract, a.keywords, a.published_at,
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


# ─── Keywords page ─────────────────────────────────────────────────────────

@router.get("/keywords", response_class=HTMLResponse)
def keywords_page(request: Request):
    """Keyword cloud."""
    author = get_current_author(request)
    with get_conn().connection() as conn:
        rows = conn.execute(
            """SELECT keyword, COUNT(*) as count
               FROM articles, unnest(keywords) AS keyword
               WHERE status = 'published'
               GROUP BY keyword
               ORDER BY count DESC, keyword ASC""",
        ).fetchall()

    if not rows:
        body = '<div class="empty"><h3>No keywords yet</h3><p>Keywords appear once articles are published.</p></div>'
    else:
        # Scale font sizes by count
        max_count = max(r["count"] for r in rows)
        links = []
        for r in rows:
            size = 0.85 + (r["count"] / max_count) * 0.8
            links.append(
                f'<a href="/keywords/{quote(r["keyword"])}/articles" style="font-size:{size:.1f}rem">{r["keyword"]} <span style="color:#888">({r["count"]})</span></a>'
            )
        body = f"""
        <h1>Keywords</h1>
        <p style="color:#888;margin-bottom:1.5rem">{len(rows)} keyword{'s' if len(rows) != 1 else ''} across published articles</p>
        <div class="keyword-cloud">{''.join(links)}</div>
        """
    return _page("Keywords", body, author, current_path="/keywords")


@router.get("/stats", response_class=HTMLResponse)
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
            "total_authors": conn.execute("SELECT COUNT(*) AS c FROM authors").fetchone()["c"],
            "total_downloads": conn.execute("SELECT COUNT(*) AS c FROM downloads").fetchone()["c"],
            "agent_downloads": conn.execute(
                "SELECT COUNT(*) AS c FROM downloads WHERE is_agent = TRUE"
            ).fetchone()["c"],
            "human_downloads": conn.execute(
                "SELECT COUNT(*) AS c FROM downloads WHERE is_agent = FALSE"
            ).fetchone()["c"],
            "total_endorsements": conn.execute(
                "SELECT COUNT(*) AS c FROM endorsements"
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
        ("Endorsements", "total_endorsements"),
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


# ─── Keyword articles page ─────────────────────────────────────────────────

@router.get("/keywords/{keyword:path}/articles", response_class=HTMLResponse)
def keyword_articles(keyword: str, request: Request, page: int = 1, per_page: int = 20):
    """Articles by keyword."""
    from urllib.parse import unquote
    keyword = unquote(keyword)
    author = get_current_author(request)
    offset = (page - 1) * per_page
    with get_conn().connection() as conn:
        rows = conn.execute(
            """SELECT a.id, a.ark, a.title, a.abstract, a.keywords, a.published_at,
                      string_agg(au.name, ', ' ORDER BY aa."order") as author_names
               FROM articles a
               LEFT JOIN article_authors aa ON a.id = aa.article_id
               LEFT JOIN authors au ON aa.author_id = au.id
               WHERE a.status = 'published' AND %s = ANY(a.keywords)
               GROUP BY a.id
               ORDER BY a.published_at DESC LIMIT %s OFFSET %s""",
            (keyword, per_page, offset),
        ).fetchall()
        total = conn.execute(
            """SELECT COUNT(*) as c FROM articles
               WHERE status = 'published' AND %s = ANY(keywords)""",
            (keyword,),
        ).fetchone()["c"]

    cards = "".join(_article_card(r) for r in rows) if rows else ""
    if not cards:
        cards = '<div class="empty"><h3>No articles with this keyword</h3></div>'

    body = f"""
    <h1>Keyword: {keyword}</h1>
    <p style="color:#888;margin-bottom:1.5rem">{total} article{'s' if total != 1 else ''}</p>
    {cards}
    <div style="margin-top:1.5rem"><a href="/keywords">&larr; All keywords</a></div>
    """
    return _page(f"Keyword: {keyword}", body, author)


# ─── Author profile page ───────────────────────────────────────────────────

@router.get("/author/{orcid:path}", response_class=HTMLResponse)
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
            """SELECT a.id, a.ark, a.title, a.abstract, a.keywords, a.published_at,
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
        endorsement_count = conn.execute(
            """SELECT COUNT(*) as c FROM endorsements e
               JOIN articles a ON e.article_id = a.id
               WHERE e.author_id = %s AND a.status = 'published'""",
            (author["id"],),
        ).fetchone()["c"]

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
        <div class="stat-card"><div class="num">{endorsement_count}</div><div class="label">Endorsements given</div></div>
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
    const nameSpan = document.createElement('span');
    nameSpan.className = 'author-name';
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
    div.appendChild(removeBtn);
    container.appendChild(div);
    if (orcid) lookupOrcid(input, nameSpan);
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

    if (!title) missing.push('title');
    if (!abstract) missing.push('abstract');
    if (!mdFile) missing.push('Markdown file');
    if (classCount < 3) missing.push((3 - classCount) + ' more classification' + ((3 - classCount) > 1 ? 's' : ''));
    if (!reviewed) missing.push('review confirmation');
    if (!cc0) missing.push('CC0 agreement');
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
    var submitterOrcid = document.querySelector('[name="submitter_orcid"]').value;
    var submitterName = document.querySelector('[name="submitter_name"]').value;
    var coAuthorInputs = document.querySelectorAll('[name="co_author_orcids"]');
    var keywords = getSelectedClassifications();

    // Gather all authors
    var authors = [{orcid: submitterOrcid, name: submitterName}];
    coAuthorInputs.forEach(function(input) {
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
    var kwHtml = keywords.map(function(k) { return '<span class="subject-tag">' + k + '</span>'; }).join(' ');

    document.getElementById('preview-title').textContent = title;
    document.getElementById('preview-abstract').textContent = abstract;
    document.getElementById('preview-authors').innerHTML = authorsHtml;
    document.getElementById('preview-keywords').innerHTML = kwHtml;
    document.getElementById('preview-file').textContent = mdFile.name + ' (' + (mdFile.size / 1024).toFixed(1) + ' KB)';

    // Store authors JSON for final submission
    document.getElementById('authors-json').value = JSON.stringify(authors);

    // Copy values to confirm form
    document.getElementById('confirm-title').value = title;
    document.getElementById('confirm-abstract').value = abstract;
    document.getElementById('confirm-authors').value = JSON.stringify(authors);
    document.getElementById('confirm-keywords').value = keywords.join(', ');
    // Copy the file to the confirm form's file input
    var confirmFile = document.getElementById('confirm-markdown');
    confirmFile.files = mdFile;

    // Show preview, hide form
    document.getElementById('submit-form').style.display = 'none';
    document.getElementById('preview-section').style.display = 'block';
}

function backToForm(e) {
    e.preventDefault();
    document.getElementById('submit-form').style.display = 'block';
    document.getElementById('preview-section').style.display = 'none';
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
window.addEventListener('beforeunload', function(e) {
    if (_submitConfirmed) return;
    var form = document.getElementById('main-form');
    if (!form) return;
    var hasData = false;
    // Text inputs and textareas
    form.querySelectorAll('input[type="text"], textarea').forEach(function(el) {
        if (el.value.trim()) hasData = true;
    });
    // File input
    var fileInput = form.querySelector('input[type="file"]');
    if (fileInput && fileInput.files && fileInput.files.length > 0) hasData = true;
    // Checkboxes
    form.querySelectorAll('input[type="checkbox"]').forEach(function(el) {
        if (el.checked) hasData = true;
    });
    // Selects (classification rows)
    form.querySelectorAll('select').forEach(function(el) {
        if (el.value) hasData = true;
    });
    // Co-author ORCID inputs (added dynamically but inside the form)
    form.querySelectorAll('input[name="co_author_orcids"]').forEach(function(el) {
        if (el.value.trim()) hasData = true;
    });
    if (hasData) {
        e.preventDefault();
        e.returnValue = 'You have unsaved changes. Are you sure you want to leave?';
        return 'You have unsaved changes. Are you sure you want to leave?';
    }
});

// Clear the flag when the confirm form is submitted
document.addEventListener('DOMContentLoaded', function() {
    var confirmForm = document.getElementById('confirm-form');
    if (confirmForm) {
        confirmForm.addEventListener('submit', function() { _submitConfirmed = true; });
    }
});
"""


@router.get("/submit", response_class=HTMLResponse)
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
    submit_js = SUBMIT_JS.replace("__OECD_JSON__", oecd_json)

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
            <input type="hidden" name="ai_disclosure" value="AI-generated content, reviewed and verified by the authors.">

            <div class="form-group">
                <label>Markdown file (.md)</label>
                <input type="file" name="markdown" accept=".md,.markdown" required>
                <div class="hint">Max 25MB. The file is the version of record.</div>
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
                <label>Authors</label>
                <div id="co-authors">
                    <div class="author-entry">
                        <input type="text" value="{author['orcid']}" readonly
                            style="padding:0.6rem;border:1px solid var(--border);border-radius:4px;font-size:0.95rem;flex:1;background:var(--paper-warm)"
                            data-name="{author['name']}">
                        <span class="author-name">{author['name']} (you)</span>
                    </div>
                </div>
                <div class="hint" style="margin-bottom:0.5rem">Add co-authors by ORCID iD. Names are looked up automatically.</div>
                <button type="button" class="add-author-btn" id="add-author-btn">+ Add co-author</button>
            </div>

            <div class="form-group">
                <label>Subject classifications (select 3)</label>
                <div id="classification-rows"></div>
                <div class="hint">Select a domain then a subdomain for each row. Boxes turn green when both are selected.</div>
            </div>

            <div class="form-group">
                <div class="confirm-checkbox">
                    <input type="checkbox" name="reviewed" id="reviewed">
                    <label for="reviewed">I confirm that this content was AI-generated, and I have reviewed and verified it for accuracy and integrity.</label>
                </div>
                <div class="confirm-checkbox">
                    <input type="checkbox" name="cc0_agree" id="cc0_agree">
                    <label for="cc0_agree">I dedicate this work to the public domain under <a href="https://creativecommons.org/publicdomain/zero/1.0/" target="_blank">CC0</a>.</label>
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
            <div class="meta"><strong>Subjects:</strong> <span id="preview-keywords"></span></div>
            <div class="meta"><strong>File:</strong> <span id="preview-file"></span></div>
            <div class="meta"><strong>License:</strong> CC0 (Public Domain)</div>
            <div class="meta"><strong>AI disclosure:</strong> AI-generated content, reviewed and verified by the authors.</div>
        </div>

        <p style="margin:1.5rem 0">By confirming, you agree that the authors listed above are correct and that you have their permission to include them.</p>

        <form method="post" action="/api/submit" enctype="multipart/form-data" id="confirm-form">
            <!-- Re-submit all fields -->
            <input type="hidden" name="title" id="confirm-title">
            <input type="hidden" name="abstract" id="confirm-abstract">
            <input type="hidden" name="authors" id="confirm-authors">
            <input type="hidden" name="license" value="CC0">
            <input type="hidden" name="license_url" value="https://creativecommons.org/publicdomain/zero/1.0/">
            <input type="hidden" name="ai_disclosure" value="AI-generated content, reviewed and verified by the authors.">
            <input type="hidden" name="keywords" id="confirm-keywords">
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
    return _page("Submit", body, author, extra_css=SUBMIT_CSS, extra_js=submit_js, current_path="/submit")


@router.get("/submit-version/{article_id}", response_class=HTMLResponse)
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
            <label>AI disclosure</label>
            <textarea name="ai_disclosure" required placeholder="State plainly what the AI did.">Drafted by an AI, verified by the authors.</textarea>
        </div>
        <div class="form-group">
            <label>Abstract (optional)</label>
            <textarea name="abstract" placeholder="Brief abstract..."></textarea>
        </div>
        <div class="form-group">
            <label>Keywords (comma-separated, optional)</label>
            <input type="text" name="keywords" placeholder="AI, machine learning, ...">
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

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request):
    """Author's submissions dashboard."""
    author = require_author(request)
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
            new_version_link = ""
            if r["status"] in ("published", "superseded"):
                new_version_link = f' <a href="/submit-version/{r["id"]}" class="btn" style="font-size:0.8rem;padding:0.3rem 0.8rem">Submit new version</a>'
            cards.append(f"""<div class="card">
<h2>{link}</h2>
<div class="meta">
    <span class="status-badge {status_class}">{r['status']}</span>
    {version_badge}
    &middot; Submitted {submitted}
    {f'&middot; Published {published}' if published else ''}
    &middot; ARK: {ark}
</div>
<div style="margin-top:0.5rem">{new_version_link}</div>
</div>""")
        body = f"""
        <h1>My Submissions</h1>
        {email_section}
        <p style="margin-bottom:1.5rem"><a href="/submit" class="btn btn-primary">Submit new paper</a></p>
        {''.join(cards)}
        """
    return _page("My Submissions", body, author, current_path="/dashboard")


# ─── Profile page ──────────────────────────────────────────────────────────

@router.get("/profile", response_class=HTMLResponse)
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


@router.post("/profile/email")
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


@router.post("/profile/affiliation")
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

@router.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    """Admin moderation queue and stats."""
    admin = require_admin(request)
    with get_conn().connection() as conn:
        pending = conn.execute(
            """SELECT a.id, a.title, a.ai_disclosure, a.submitted_at,
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
        pending_cards = []
        for p in pending:
            submitted = _format_date(p.get("submitted_at"))
            pending_cards.append(f"""<div class="card">
<h2>{p['title']}</h2>
<div class="meta">Submitted by <a href="/author/{p['submitter_orcid']}">{p['submitter_name']}</a> on {submitted}</div>
<div class="abstract"><strong>AI disclosure:</strong> {p['ai_disclosure']}</div>
<div style="margin-top:1rem;display:flex;gap:0.5rem">
    <form method="post" action="/admin/articles/{p['id']}" style="display:inline">
        <input type="hidden" name="action" value="approve">
        <button type="submit" class="btn btn-primary">Approve</button>
    </form>
    <form method="post" action="/admin/articles/{p['id']}" style="display:inline">
        <input type="hidden" name="action" value="reject">
        <button type="submit" class="btn btn-danger">Reject</button>
    </form>
    <a href="/admin/submission/{p['id']}" class="btn">View details</a>
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

    body = f"""
    <h1>Admin Dashboard</h1>
    {stats_html}
    {queue_html}
    {recent_html}
    """
    return _page("Admin", body, admin, current_path="/admin")


# ─── Admin submission detail page ──────────────────────────────────────────

@router.get("/admin/submission/{article_id}", response_class=HTMLResponse)
def admin_submission_detail(article_id: int, request: Request):
    """View submission details (admin only)."""
    admin = require_admin(request)
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

    <div class="card">
        <h3>AI Disclosure</h3>
        <p>{article['ai_disclosure']}</p>
    </div>

    {f'<div class="card"><h3>Abstract</h3><p>{article["abstract"]}</p></div>' if article.get('abstract') else ''}

    {f'<div class="card"><h3>Keywords</h3><p>{", ".join(article["keywords"])}</p></div>' if article.get('keywords') else ''}

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

    <div style="margin-top:1.5rem"><a href="/admin">&larr; Back to queue</a></div>
    """
    return _page(f"Submission: {article['title']}", body, admin)


# ─── Admin form-based moderation (POST handler for HTML forms) ─────────────

class ModerationForm(BaseModel):
    action: str
    note: str = ""


@router.post("/admin/articles/{article_id}")
def moderate_article_form(
    article_id: int,
    request: Request,
    action: str = "",
    note: str = "",
):
    """Handle form-based moderation (redirects back to admin)."""
    admin = require_admin(request)
    from articles import moderate_article as _mod
    # Call the API handler
    result = _mod(article_id, ModerationForm(action=action, note=note), admin)
    # Redirect back to admin
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/admin", status_code=303)
