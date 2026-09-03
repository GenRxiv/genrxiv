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

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from config import config
from db import get_conn
from auth import get_current_author, require_author, require_admin

router = APIRouter()

# ─── Shared template helpers ───────────────────────────────────────────────

PAGE_CSS = """
:root {
    --paper: #EDEAE2;
    --ink: #1B1E27;
    --cobalt: #2F5CFF;
    --muted: #C9C3B5;
    --border: #D8D2C4;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, sans-serif;
    color: var(--ink);
    background: var(--paper);
    line-height: 1.7;
    font-size: 1.05rem;
}
a { color: var(--cobalt); text-decoration: none; }
a:hover { text-decoration: underline; }
h1, h2, h3, h4 { font-family: 'Fraunces', Georgia, serif; line-height: 1.3; }
.container { max-width: 52rem; margin: 0 auto; padding: 2rem 1.5rem; }
header {
    border-bottom: 1px solid var(--border);
    padding: 1rem 1.5rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 1rem;
}
header .brand { font-family: 'Fraunces', Georgia, serif; font-size: 1.4rem; font-weight: 600; }
header .brand a { color: var(--ink); }
header nav { display: flex; gap: 1.2rem; flex-wrap: wrap; }
header nav a { color: var(--ink); font-size: 0.95rem; }
.btn {
    display: inline-block;
    padding: 0.5rem 1.2rem;
    border: 1px solid var(--cobalt);
    border-radius: 4px;
    color: var(--cobalt);
    font-size: 0.95rem;
    cursor: pointer;
    background: transparent;
    transition: all 0.15s;
}
.btn:hover { background: var(--cobalt); color: #fff; text-decoration: none; }
.btn-primary { background: var(--cobalt); color: #fff; }
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


def _header_html(author: dict | None) -> str:
    """Render the site header with nav."""
    nav_links = '<a href="/browse">Browse</a><a href="/keywords">Keywords</a><a href="/api/stats">Stats</a>'
    if author:
        auth_links = f'<a href="/dashboard">My Submissions</a><a href="/submit" class="btn btn-primary">Submit</a><a href="/auth/me" style="font-size:0.85rem">{author["name"]}</a><a href="/auth/logout" style="font-size:0.85rem">Sign out</a>'
    else:
        auth_links = f'<a href="/auth/orcid?redirect=/browse" class="btn">Sign in with ORCID</a><a href="/submit" class="btn btn-primary">Submit</a>'
    return f"""<header>
<div class="brand"><a href="/">{config.site_name}</a></div>
<nav>{nav_links}</nav>
<nav>{auth_links}</nav>
</header>"""


def _footer_html() -> str:
    return f"""<footer>
<p>{config.site_name} &mdash; An open archive for AI-generated research.</p>
<p><a href="/api/articles">API</a> &middot; <a href="/oai?verb=Identify">OAI-PMH</a> &middot; <a href="/feed.xml">Feed</a> &middot; <a href="/sitemap.xml">Sitemap</a> &middot; <a href="/robots.txt">robots.txt</a></p>
</footer>"""


def _page(title: str, body: str, author: dict | None = None) -> HTMLResponse:
    """Render a full HTML page."""
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} &middot; {config.site_name}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:wght@400;600;700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<link rel="alternate" type="application/atom+xml" title="{config.site_name} — Recent Articles" href="/feed.xml">
<style>{PAGE_CSS}</style>
</head>
<body>
{_header_html(author)}
<div class="container">
{body}
</div>
{_footer_html()}
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


# ─── Browse page ───────────────────────────────────────────────────────────

@router.get("/browse", response_class=HTMLResponse)
def browse_page(
    request: Request,
    page: int = 1,
    per_page: int = 20,
    q: str = "",
):
    """Browse published articles."""
    author = get_current_author(request)
    offset = (page - 1) * per_page
    with get_conn().connection() as conn:
        if q:
            rows = conn.execute(
                """SELECT a.id, a.ark, a.title, a.abstract, a.keywords, a.published_at,
                          string_agg(au.name, ', ' ORDER BY aa."order") as author_names
                   FROM articles a
                   LEFT JOIN article_authors aa ON a.id = aa.article_id
                   LEFT JOIN authors au ON aa.author_id = au.id
                   WHERE a.status = 'published'
                     AND (a.title ILIKE %s OR a.abstract ILIKE %s)
                   GROUP BY a.id
                   ORDER BY a.published_at DESC LIMIT %s OFFSET %s""",
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
                """SELECT a.id, a.ark, a.title, a.abstract, a.keywords, a.published_at,
                          string_agg(au.name, ', ' ORDER BY aa."order") as author_names
                   FROM articles a
                   LEFT JOIN article_authors aa ON a.id = aa.article_id
                   LEFT JOIN authors au ON aa.author_id = au.id
                   WHERE a.status = 'published'
                   GROUP BY a.id
                   ORDER BY a.published_at DESC LIMIT %s OFFSET %s""",
                (per_page, offset),
            ).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) as c FROM articles WHERE status = 'published'"
            ).fetchone()["c"]

    cards = "".join(_article_card(r) for r in rows) if rows else ""
    if not cards:
        cards = '<div class="empty"><h3>No articles yet</h3><p>Be the first to submit.</p></div>'

    # Pagination
    pages = (total + per_page - 1) // per_page
    pagination = ""
    if pages > 1:
        parts = []
        for p in range(1, pages + 1):
            if p == page:
                parts.append(f'<span class="current">{p}</span>')
            else:
                qs = f"?page={p}" + (f"&q={quote(q)}" if q else "")
                parts.append(f'<a href="/browse{qs}">{p}</a>')
        pagination = f'<div class="pagination">{"".join(parts)}</div>'

    search_box = f"""
    <form method="get" action="/browse" style="margin-bottom:1.5rem">
        <input type="text" name="q" value="{q}" placeholder="Search articles..." style="width:60%;padding:0.5rem;border:1px solid var(--border);border-radius:4px;font-size:1rem">
        <button type="submit" class="btn">Search</button>
    </form>"""

    body = f"""
    <h1>Browse Articles</h1>
    <p style="color:#888;margin-bottom:1.5rem">{total} published article{'s' if total != 1 else ''}</p>
    {search_box}
    {cards}
    {pagination}
    """
    return _page("Browse", body, author)


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
    return _page("Keywords", body, author)


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
            "SELECT id, orcid, name, affiliation, created_at FROM authors WHERE orcid = %s",
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

    body = f"""
    <div class="author-info">
        <div>
            <div class="name">{author['name']}</div>
            <div class="orcid"><a href="https://orcid.org/{author['orcid']}">ORCID: {author['orcid']}</a></div>
            {f'<div style="font-size:0.9rem;color:#555;margin-top:0.3rem">{author["affiliation"]}</div>' if author.get('affiliation') else ''}
        </div>
    </div>
    <div class="stats-grid" style="margin-bottom:2rem">
        <div class="stat-card"><div class="num">{len(articles)}</div><div class="label">Published articles</div></div>
        <div class="stat-card"><div class="num">{endorsement_count}</div><div class="label">Endorsements given</div></div>
    </div>
    <h2>Articles</h2>
    {cards}
    """
    return _page(author["name"], body, author_session)


# ─── Submit page ───────────────────────────────────────────────────────────

@router.get("/submit", response_class=HTMLResponse)
def submit_page(request: Request):
    """Submission form."""
    author = get_current_author(request)
    if not author:
        body = f"""
        <div class="empty">
            <h3>Sign in to submit</h3>
            <p>You need an ORCID to submit to {config.site_name}.</p>
            <p style="margin-top:1rem"><a href="/auth/orcid?redirect=/submit" class="btn btn-primary">Sign in with ORCID</a></p>
        </div>
        """
        return _page("Submit", body, None)

    body = f"""
    <h1>Submit a Paper</h1>
    <p style="color:#888;margin-bottom:1.5rem">GenRxiv accepts Markdown submissions only. Markdown is the version of record.</p>
    <form method="post" action="/api/submit" enctype="multipart/form-data">
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
            <label>Authors (JSON array)</label>
            <textarea name="authors" required>[{{"orcid": "{author['orcid']}", "name": "{author['name']}"}}]</textarea>
            <div class="hint">JSON array of {{"orcid": "...", "name": "...", "affiliation": "..."}} objects. You can add co-authors.</div>
        </div>
        <div class="form-group">
            <label>AI disclosure</label>
            <textarea name="ai_disclosure" required placeholder="State plainly what the AI did.">Drafted by an AI, verified by the authors.</textarea>
            <div class="hint">GenRxiv assumes AI was involved. Just state what it did.</div>
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
        <button type="submit" class="btn btn-primary">Submit for review</button>
    </form>
    <div style="margin-top:1.5rem;font-size:0.85rem;color:#888">
        <p>After submission, your paper will be reviewed by a moderator before publication.
        You'll be able to track its status from <a href="/dashboard">My Submissions</a>.</p>
    </div>
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
    return _page("Submit", body, author)


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

    if not rows:
        body = """
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
            # Show "Submit new version" link for published or superseded articles
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
        <p style="margin-bottom:1.5rem"><a href="/submit" class="btn btn-primary">Submit new paper</a></p>
        {''.join(cards)}
        """
    return _page("My Submissions", body, author)


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
    return _page("Admin", body, admin)


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
