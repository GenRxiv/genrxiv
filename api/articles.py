"""
GenRxiv API — article submission, viewing, and moderation.
"""
import hashlib
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, Request, HTTPException, Depends, UploadFile, File, Form, Query
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel

from config import config
from db import get_conn
from auth import get_current_author, require_author, require_admin

router = APIRouter()

# ─── Helpers ───────────────────────────────────────────────────────────────

AGENT_PATTERNS = [
    "gptbot", "chatgpt", "claude", "anthropic", "googlebot", "bingbot",
    "slackbot", "twitterbot", "linkedinbot", "perplexitybot", "amazonbot",
    "applebot", "facebookexternalhit", "python-requests", "curl", "wget",
    "postmanruntime", "semrushbot", "ahrefsbot", "dotbot", "rogerbot",
    "bytespider", "yandexbot", "baiduspider", "sogou",
]


def is_agent(user_agent: str) -> bool:
    ua = (user_agent or "").lower()
    return any(p in ua for p in AGENT_PATTERNS)


def ip_hash(ip: str) -> str:
    return hashlib.sha256(ip.encode()).hexdigest()[:16]


def assign_ark(article_id: int) -> str:
    return f"ark:/{config.ark_naan}/genrxiv-{article_id:04d}"


def render_html(markdown: str) -> str:
    """Call conversion service to render Markdown → HTML."""
    with httpx.Client(timeout=120) as client:
        r = client.post(
            f"{config.convert_service_url}/render/html",
            files={"file": ("input.md", markdown.encode("utf-8"), "text/markdown")},
        )
        r.raise_for_status()
        return r.text


def render_pdf(markdown: str) -> bytes:
    """Call conversion service to render Markdown → PDF."""
    import time
    time.sleep(1)  # Avoid rate limit on conversion service
    with httpx.Client(timeout=120) as client:
        r = client.post(
            f"{config.convert_service_url}/convert/markdown",
            files={"file": ("input.md", markdown.encode("utf-8"), "text/markdown")},
        )
        r.raise_for_status()
        return r.content


def save_article_file(article_id: int, ext: str, content: bytes | str) -> str:
    """Save rendered file to disk, return relative path."""
    files_dir = Path(config.files_dir)
    files_dir.mkdir(parents=True, exist_ok=True)
    article_dir = files_dir / str(article_id)
    article_dir.mkdir(parents=True, exist_ok=True)
    filename = f"article.{ext}"
    filepath = article_dir / filename
    if isinstance(content, str):
        filepath.write_text(content, encoding="utf-8")
    else:
        filepath.write_bytes(content)
    return f"{article_id}/{filename}"


def track_download(article_id: int, fmt: str, request: Request):
    """Record a download/view."""
    ua = request.headers.get("user-agent", "")
    agent = is_agent(ua)
    client_ip = request.client.host if request.client else ""
    with get_conn().connection() as conn:
        conn.execute(
            "INSERT INTO downloads (article_id, format, user_agent, is_agent, ip_hash) VALUES (%s, %s, %s, %s, %s)",
            (article_id, fmt, ua[:500], agent, ip_hash(client_ip)),
        )
        conn.commit()


def get_article_by_ark(ark: str) -> dict | None:
    with get_conn().connection() as conn:
        row = conn.execute(
            """SELECT a.*, array_agg(aa.author_id ORDER BY aa."order") AS author_ids
               FROM articles a
               LEFT JOIN article_authors aa ON a.id = aa.article_id
               WHERE a.ark = %s AND a.status = 'published'
               GROUP BY a.id""",
            (ark,),
        ).fetchone()
    return row


def get_article_authors(article_id: int) -> list[dict]:
    with get_conn().connection() as conn:
        rows = conn.execute(
            """SELECT a.id, a.orcid, a.name, a.affiliation
               FROM authors a
               JOIN article_authors aa ON a.id = aa.author_id
               WHERE aa.article_id = %s
               ORDER BY aa."order\"""",
            (article_id,),
        ).fetchall()
    return rows


def build_jsonld(article: dict, authors: list[dict]) -> dict:
    """Build Schema.org ScholarArticle JSON-LD."""
    base = config.base_url
    ark = article["ark"]
    jsonld = {
        "@context": "https://schema.org",
        "@type": "ScholarlyArticle",
        "@id": ark,
        "identifier": ark,
        "url": f"{base}/article/{ark}",
        "headline": article["title"],
    }
    if article.get("abstract"):
        jsonld["abstract"] = article["abstract"]
    if authors:
        jsonld["author"] = []
        for a in authors:
            author_obj = {"@type": "Person", "name": a["name"]}
            if a.get("orcid"):
                author_obj["@id"] = f"https://orcid.org/{a['orcid']}"
            if a.get("affiliation"):
                author_obj["affiliation"] = {"@type": "Organization", "name": a["affiliation"]}
            jsonld["author"].append(author_obj)
    if article.get("published_at"):
        jsonld["datePublished"] = article["published_at"].strftime("%Y-%m-%d")
    if article.get("license_url"):
        jsonld["license"] = article["license_url"]
    if article.get("keywords"):
        jsonld["keywords"] = ", ".join(article["keywords"])
    jsonld["inLanguage"] = "en"
    jsonld["isPartOf"] = {
        "@type": "PublicationVolume",
        "name": config.site_name,
        "publisher": {"@type": "Organization", "name": config.site_name},
    }
    return jsonld


# ─── Submission ────────────────────────────────────────────────────────────

class AuthorInput(BaseModel):
    orcid: str
    name: str
    affiliation: str | None = None


@router.post("/api/submit")
async def submit(
    request: Request,
    markdown: UploadFile = File(...),
    title: str = Form(...),
    authors: str = Form(...),
    ai_disclosure: str = Form(...),
    abstract: str = Form(""),
    license: str = Form("CC-BY-4.0"),
    license_url: str = Form("https://creativecommons.org/licenses/by/4.0/"),
    keywords: str = Form(""),
    _author: dict = Depends(require_author),
):
    """Submit a Markdown paper."""
    # Validate file
    content = await markdown.read()
    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(413, "File too large (25MB max)")
    ext = Path(markdown.filename or "input.md").suffix.lower()
    if ext not in (".md", ".markdown"):
        raise HTTPException(400, "GenRxiv accepts Markdown only (.md)")

    md_text = content.decode("utf-8", errors="replace")

    # Parse authors JSON
    try:
        author_list = json.loads(authors)
        if not isinstance(author_list, list) or not author_list:
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(400, "authors must be a JSON array of {orcid, name} objects")

    # Parse keywords
    kw_list = [k.strip() for k in keywords.split(",") if k.strip()] if keywords else []

    # Insert article
    with get_conn().connection() as conn:
        row = conn.execute(
            """INSERT INTO articles (title, abstract, ai_disclosure, license, license_url, keywords, source_markdown, submitted_by, status)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending')
               RETURNING id, ark, status, submitted_at""",
            (title, abstract or None, ai_disclosure, license, license_url, kw_list, md_text, _author["id"]),
        ).fetchone()
        article_id = row["id"]

        # Upsert authors and link
        for i, a in enumerate(author_list):
            existing = conn.execute(
                "SELECT id FROM authors WHERE orcid = %s", (a["orcid"],)
            ).fetchone()
            if existing:
                author_id = existing["id"]
                conn.execute(
                    "UPDATE authors SET name = %s, affiliation = COALESCE(%s, affiliation) WHERE id = %s",
                    (a["name"], a.get("affiliation"), author_id),
                )
            else:
                new_author = conn.execute(
                    "INSERT INTO authors (orcid, name, affiliation) VALUES (%s, %s, %s) RETURNING id",
                    (a["orcid"], a["name"], a.get("affiliation")),
                ).fetchone()
                author_id = new_author["id"]
            conn.execute(
                "INSERT INTO article_authors (article_id, author_id, \"order\") VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (article_id, author_id, i),
            )
        conn.commit()

    return {
        "id": article_id,
        "ark": assign_ark(article_id),
        "status": "pending",
        "submitted_at": row["submitted_at"].isoformat(),
    }


# ─── Author's own submissions ──────────────────────────────────────────────

@router.get("/api/submissions")
def my_submissions(_author: dict = Depends(require_author)):
    """List the current author's submissions."""
    with get_conn().connection() as conn:
        rows = conn.execute(
            """SELECT id, ark, title, status, submitted_at, published_at
               FROM articles WHERE submitted_by = %s ORDER BY submitted_at DESC""",
            (_author["id"],),
        ).fetchall()
    return {"items": rows}


# ─── Public article listing ────────────────────────────────────────────────

@router.get("/api/articles")
def list_articles(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    format: str = Query("json"),
    q: str = Query(""),
):
    """List published articles, paginated."""
    offset = (page - 1) * per_page
    with get_conn().connection() as conn:
        if q:
            rows = conn.execute(
                """SELECT id, ark, title, abstract, keywords, published_at, license
                   FROM articles
                   WHERE status = 'published'
                     AND (title ILIKE %s OR abstract ILIKE %s)
                   ORDER BY published_at DESC LIMIT %s OFFSET %s""",
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
                """SELECT id, ark, title, abstract, keywords, published_at, license
                   FROM articles WHERE status = 'published'
                   ORDER BY published_at DESC LIMIT %s OFFSET %s""",
                (per_page, offset),
            ).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) as c FROM articles WHERE status = 'published'"
            ).fetchone()["c"]

    if format == "jsonld":
        items = []
        for row in rows:
            authors = get_article_authors(row["id"])
            items.append(build_jsonld(row, authors))
        return {"items": items, "total": total, "page": page, "per_page": per_page}

    return {
        "items": [
            {
                "id": r["id"],
                "ark": r["ark"],
                "title": r["title"],
                "abstract": r["abstract"],
                "keywords": r["keywords"],
                "published_at": r["published_at"].isoformat() if r["published_at"] else None,
                "license": r["license"],
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.get("/api/articles/{article_id}")
def get_article_meta(article_id: int, format: str = Query("json")):
    """Get article metadata."""
    with get_conn().connection() as conn:
        row = conn.execute(
            "SELECT * FROM articles WHERE id = %s AND status = 'published'", (article_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "Article not found")
    authors = get_article_authors(article_id)
    if format == "jsonld":
        return build_jsonld(row, authors)
    return {
        "id": row["id"],
        "ark": row["ark"],
        "title": row["title"],
        "abstract": row["abstract"],
        "ai_disclosure": row["ai_disclosure"],
        "license": row["license"],
        "license_url": row["license_url"],
        "keywords": row["keywords"],
        "authors": authors,
        "published_at": row["published_at"].isoformat() if row["published_at"] else None,
    }


# ─── Article viewing (HTML/PDF/Markdown/JSON-LD) ───────────────────────────
# NOTE: Specific routes (with suffixes) must be registered BEFORE the
# catch-all {ark:path} route, otherwise FastAPI matches the catch-all first.

@router.get("/article/{ark:path}/pdf")
def download_pdf(ark: str, request: Request):
    """Download article as PDF."""
    from urllib.parse import unquote
    ark = unquote(ark)
    article = get_article_by_ark(ark)
    if not article:
        raise HTTPException(404, "Article not found")
    track_download(article["id"], "pdf", request)
    if article["pdf_path"]:
        filepath = Path(config.files_dir) / article["pdf_path"]
        if filepath.exists():
            return FileResponse(filepath, media_type="application/pdf", filename=f"{ark.replace('/', '_')}.pdf")
    # Fallback: render on the fly
    pdf_bytes = render_pdf(article["source_markdown"])
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{ark.replace("/", "_")}.pdf"'},
    )


@router.get("/article/{ark:path}/markdown")
def download_markdown(ark: str, request: Request):
    """Download original Markdown source."""
    from urllib.parse import unquote
    ark = unquote(ark)
    article = get_article_by_ark(ark)
    if not article:
        raise HTTPException(404, "Article not found")
    track_download(article["id"], "markdown", request)
    return Response(
        content=article["source_markdown"].encode("utf-8"),
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{ark.replace("/", "_")}.md"'},
    )


@router.get("/article/{ark:path}/jsonld")
def article_jsonld(ark: str):
    """Get article as JSON-LD."""
    from urllib.parse import unquote
    ark = unquote(ark)
    article = get_article_by_ark(ark)
    if not article:
        raise HTTPException(404, "Article not found")
    authors = get_article_authors(article["id"])
    return build_jsonld(article, authors)


@router.get("/article/{ark:path}", response_class=HTMLResponse)
def view_article(ark: str, request: Request):
    """View article as HTML."""
    from urllib.parse import unquote
    ark = unquote(ark)
    article = get_article_by_ark(ark)
    if not article:
        raise HTTPException(404, "Article not found")
    track_download(article["id"], "html", request)
    if article["html_path"]:
        filepath = Path(config.files_dir) / article["html_path"]
        if filepath.exists():
            return HTMLResponse(filepath.read_text(encoding="utf-8"))
    # Fallback: render on the fly
    html = render_html(article["source_markdown"])
    return HTMLResponse(html)


# ─── Moderation (admin) ────────────────────────────────────────────────────

class ModerationAction(BaseModel):
    action: str  # "approve" or "reject"
    note: str = ""


@router.get("/admin/queue")
def moderation_queue(_admin: dict = Depends(require_admin)):
    """List pending submissions."""
    with get_conn().connection() as conn:
        rows = conn.execute(
            """SELECT a.id, a.title, a.ai_disclosure, a.submitted_at,
                      a.submitted_by, au.name as submitter_name, au.orcid as submitter_orcid
               FROM articles a
               LEFT JOIN authors au ON a.submitted_by = au.id
               WHERE a.status = 'pending'
               ORDER BY a.submitted_at ASC""",
        ).fetchall()
    return {"items": rows}


@router.patch("/admin/articles/{article_id}")
def moderate_article(
    article_id: int,
    action: ModerationAction,
    admin: dict = Depends(require_admin),
):
    """Approve or reject a submission."""
    with get_conn().connection() as conn:
        row = conn.execute(
            "SELECT id, status, source_markdown FROM articles WHERE id = %s", (article_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Article not found")
        if row["status"] != "pending":
            raise HTTPException(400, f"Article is already {row['status']}")

        if action.action == "approve":
            ark = assign_ark(article_id)
            # Render HTML and PDF
            html = render_html(row["source_markdown"])
            pdf = render_pdf(row["source_markdown"])
            html_path = save_article_file(article_id, "html", html)
            pdf_path = save_article_file(article_id, "pdf", pdf)

            conn.execute(
                """UPDATE articles
                   SET status = 'published', ark = %s, html_path = %s, pdf_path = %s,
                       published_at = now(), moderated_by = %s, moderated_at = now(),
                       moderation_note = %s
                   WHERE id = %s""",
                (ark, html_path, pdf_path, admin["id"], action.note or None, article_id),
            )
            conn.commit()
            return {"id": article_id, "ark": ark, "status": "published"}

        elif action.action == "reject":
            conn.execute(
                """UPDATE articles
                   SET status = 'rejected', moderated_by = %s, moderated_at = now(),
                       moderation_note = %s
                   WHERE id = %s""",
                (admin["id"], action.note or None, article_id),
            )
            conn.commit()
            return {"id": article_id, "status": "rejected"}

        else:
            raise HTTPException(400, "action must be 'approve' or 'reject'")


# ─── Stats ─────────────────────────────────────────────────────────────────

@router.get("/admin/stats")
def admin_stats(_admin: dict = Depends(require_admin)):
    """Aggregate stats."""
    with get_conn().connection() as conn:
        total_articles = conn.execute(
            "SELECT COUNT(*) as c FROM articles WHERE status = 'published'"
        ).fetchone()["c"]
        total_downloads = conn.execute("SELECT COUNT(*) as c FROM downloads").fetchone()["c"]
        agent_downloads = conn.execute(
            "SELECT COUNT(*) as c FROM downloads WHERE is_agent = true"
        ).fetchone()["c"]
        human_downloads = conn.execute(
            "SELECT COUNT(*) as c FROM downloads WHERE is_agent = false"
        ).fetchone()["c"]
        pending = conn.execute(
            "SELECT COUNT(*) as c FROM articles WHERE status = 'pending'"
        ).fetchone()["c"]

    return {
        "total_articles": total_articles,
        "total_downloads": total_downloads,
        "agent_downloads": agent_downloads,
        "human_downloads": human_downloads,
        "pending_submissions": pending,
    }


@router.get("/api/articles/{article_id}/stats")
def article_stats(article_id: int, _author: dict = Depends(get_current_author)):
    """Per-article download stats."""
    with get_conn().connection() as conn:
        row = conn.execute("SELECT id FROM articles WHERE id = %s", (article_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Article not found")
        total = conn.execute(
            "SELECT COUNT(*) as c FROM downloads WHERE article_id = %s", (article_id,)
        ).fetchone()["c"]
        by_format = conn.execute(
            """SELECT format, COUNT(*) as c, SUM(CASE WHEN is_agent THEN 1 ELSE 0 END) as agent
               FROM downloads WHERE article_id = %s GROUP BY format""",
            (article_id,),
        ).fetchall()
    return {
        "total_downloads": total,
        "by_format": {r["format"]: {"total": r["c"], "agent": r["agent"]} for r in by_format},
    }


# ─── Endorsements (community upvotes) ──────────────────────────────────────

@router.post("/api/articles/{article_id}/endorse")
def endorse_article(
    article_id: int,
    author: dict = Depends(require_author),
):
    """Endorse an article (community upvote). One endorsement per author per article."""
    with get_conn().connection() as conn:
        row = conn.execute(
            "SELECT id FROM articles WHERE id = %s AND status = 'published'", (article_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Article not found")
        existing = conn.execute(
            "SELECT id FROM endorsements WHERE article_id = %s AND author_id = %s",
            (article_id, author["id"]),
        ).fetchone()
        if existing:
            raise HTTPException(409, "Already endorsed")
        conn.execute(
            "INSERT INTO endorsements (article_id, author_id) VALUES (%s, %s)",
            (article_id, author["id"]),
        )
        conn.commit()
    return {"status": "endorsed", "article_id": article_id}


@router.delete("/api/articles/{article_id}/endorse")
def unendorse_article(
    article_id: int,
    author: dict = Depends(require_author),
):
    """Remove endorsement."""
    with get_conn().connection() as conn:
        conn.execute(
            "DELETE FROM endorsements WHERE article_id = %s AND author_id = %s",
            (article_id, author["id"]),
        )
        conn.commit()
    return {"status": "unendorsed", "article_id": article_id}


@router.get("/api/articles/{article_id}/endorsements")
def article_endorsements(article_id: int):
    """Get endorsement count and list for an article."""
    with get_conn().connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) as c FROM endorsements WHERE article_id = %s", (article_id,)
        ).fetchone()["c"]
        endorsers = conn.execute(
            """SELECT a.orcid, a.name, e.endorsed_at
               FROM endorsements e
               JOIN authors a ON e.author_id = a.id
               WHERE e.article_id = %s
               ORDER BY e.endorsed_at DESC""",
            (article_id,),
        ).fetchall()
    return {
        "count": count,
        "endorsers": endorsers,
    }


# ─── Author pages ──────────────────────────────────────────────────────────

@router.get("/api/authors/{orcid:path}")
def author_profile(orcid: str):
    """Get author profile and their published articles."""
    from urllib.parse import unquote
    orcid = unquote(orcid)
    with get_conn().connection() as conn:
        author = conn.execute(
            "SELECT id, orcid, name, affiliation, created_at FROM authors WHERE orcid = %s",
            (orcid,),
        ).fetchone()
        if not author:
            raise HTTPException(404, "Author not found")
        articles = conn.execute(
            """SELECT a.id, a.ark, a.title, a.abstract, a.keywords, a.published_at
               FROM articles a
               JOIN article_authors aa ON a.id = aa.article_id
               WHERE aa.author_id = %s AND a.status = 'published'
               ORDER BY a.published_at DESC""",
            (author["id"],),
        ).fetchall()
        endorsement_count = conn.execute(
            """SELECT COUNT(*) as c FROM endorsements e
               JOIN articles a ON e.article_id = a.id
               WHERE e.author_id = %s AND a.status = 'published'""",
            (author["id"],),
        ).fetchone()["c"]
    return {
        "author": author,
        "articles": articles,
        "endorsement_count": endorsement_count,
    }


# ─── Keyword browsing ──────────────────────────────────────────────────────

@router.get("/api/keywords")
def list_keywords():
    """List all keywords with article counts."""
    with get_conn().connection() as conn:
        rows = conn.execute(
            """SELECT keyword, COUNT(*) as count
               FROM articles, unnest(keywords) AS keyword
               WHERE status = 'published'
               GROUP BY keyword
               ORDER BY count DESC, keyword ASC""",
        ).fetchall()
    return {"keywords": rows}


@router.get("/api/keywords/{keyword:path}/articles")
def articles_by_keyword(keyword: str, page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100)):
    """List published articles by keyword."""
    from urllib.parse import unquote
    keyword = unquote(keyword)
    offset = (page - 1) * per_page
    with get_conn().connection() as conn:
        rows = conn.execute(
            """SELECT id, ark, title, abstract, keywords, published_at
               FROM articles
               WHERE status = 'published' AND %s = ANY(keywords)
               ORDER BY published_at DESC LIMIT %s OFFSET %s""",
            (keyword, per_page, offset),
        ).fetchall()
        total = conn.execute(
            """SELECT COUNT(*) as c FROM articles
               WHERE status = 'published' AND %s = ANY(keywords)""",
            (keyword,),
        ).fetchone()["c"]
    return {
        "keyword": keyword,
        "items": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
    }


# ─── Public stats (agent-readable) ─────────────────────────────────────────

@router.get("/api/stats")
def public_stats():
    """Public stats — no auth required, agent-readable."""
    with get_conn().connection() as conn:
        total_articles = conn.execute(
            "SELECT COUNT(*) as c FROM articles WHERE status = 'published'"
        ).fetchone()["c"]
        total_authors = conn.execute("SELECT COUNT(*) as c FROM authors").fetchone()["c"]
        total_downloads = conn.execute("SELECT COUNT(*) as c FROM downloads").fetchone()["c"]
        agent_downloads = conn.execute(
            "SELECT COUNT(*) as c FROM downloads WHERE is_agent = true"
        ).fetchone()["c"]
        human_downloads = conn.execute(
            "SELECT COUNT(*) as c FROM downloads WHERE is_agent = false"
        ).fetchone()["c"]
        total_endorsements = conn.execute("SELECT COUNT(*) as c FROM endorsements").fetchone()["c"]
        # Top downloaded articles
        top_articles = conn.execute(
            """SELECT a.id, a.ark, a.title, COUNT(d.id) as downloads
               FROM articles a
               LEFT JOIN downloads d ON a.id = d.article_id
               WHERE a.status = 'published'
               GROUP BY a.id, a.ark, a.title
               ORDER BY downloads DESC LIMIT 10""",
        ).fetchall()
    return {
        "total_articles": total_articles,
        "total_authors": total_authors,
        "total_downloads": total_downloads,
        "agent_downloads": agent_downloads,
        "human_downloads": human_downloads,
        "total_endorsements": total_endorsements,
        "top_articles": top_articles,
    }
