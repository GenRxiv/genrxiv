"""
GenRxiv API — sitemap, robots.txt, RSS feed, and web pages.
"""
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from fastapi import APIRouter, Request
from fastapi.responses import Response, HTMLResponse, PlainTextResponse

from config import config
from db import get_conn

router = APIRouter()


@router.get("/sitemap.xml", response_class=PlainTextResponse)
def sitemap():
    """XML sitemap of all published articles."""
    with get_conn().connection() as conn:
        rows = conn.execute(
            "SELECT ark, published_at FROM articles WHERE status = 'published' ORDER BY published_at DESC"
        ).fetchall()

    urls = []
    for r in rows:
        loc = f"{config.base_url}/article/{escape(r['ark'])}"
        lastmod = r["published_at"].strftime("%Y-%m-%dT%H:%M:%S+00:00") if r["published_at"] else ""
        urls.append(f"""  <url>
    <loc>{loc}</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
  </url>""")

    # Add the homepage
    urls.insert(0, f"""  <url>
    <loc>{config.base_url}/</loc>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>""")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{chr(10).join(urls)}
</urlset>"""
    return Response(xml, media_type="application/xml")


@router.get("/feed.xml", response_class=PlainTextResponse)
def atom_feed():
    """Atom 1.0 feed of the 20 most recent published articles."""
    with get_conn().connection() as conn:
        rows = conn.execute(
            """SELECT a.id, a.ark, a.title, a.abstract, a.published_at,
                      au.name as author_name, au.orcid as author_orcid
               FROM articles a
               LEFT JOIN article_authors aa ON a.id = aa.article_id
               LEFT JOIN authors au ON aa.author_id = au.id
               WHERE a.status = 'published'
               ORDER BY a.published_at DESC
               LIMIT 20""",
        ).fetchall()

    # Group authors by article
    articles = {}
    order = []
    for r in rows:
        aid = r["id"]
        if aid not in articles:
            articles[aid] = {
                "ark": r["ark"],
                "title": r["title"],
                "abstract": r["abstract"],
                "published_at": r["published_at"],
                "authors": [],
            }
            order.append(aid)
        if r["author_name"]:
            articles[aid]["authors"].append(r["author_name"])

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entries = []
    for aid in order:
        a = articles[aid]
        url = f"{config.base_url}/article/{escape(a['ark'])}"
        updated = a["published_at"].strftime("%Y-%m-%dT%H:%M:%SZ") if a["published_at"] else now
        author_names = ", ".join(a["authors"]) or "Unknown"
        summary = escape(a["abstract"] or "")
        entries.append(f"""  <entry>
    <id>{url}</id>
    <title>{escape(a['title'])}</title>
    <link href="{url}"/>
    <updated>{updated}</updated>
    <author><name>{escape(author_names)}</name></author>
    <summary>{summary}</summary>
  </entry>""")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>{escape(config.site_name)} — Recent Articles</title>
  <link href="{config.base_url}/feed.xml" rel="self"/>
  <link href="{config.base_url}/"/>
  <id>{config.base_url}/</id>
  <updated>{now}</updated>
{chr(10).join(entries)}
</feed>"""
    return Response(xml, media_type="application/atom+xml")


@router.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    """robots.txt — allow all, point to sitemap and API discovery."""
    return f"""User-agent: *
Allow: /
Disallow: /admin/
Disallow: /api/submit

Sitemap: {config.base_url}/sitemap.xml

# API discovery for agents
OpenAPI-Schema: {config.base_url}/api/openapi.json
Agent-Guide: {config.base_url}/api/agent-guide
AI-Plugin-Manifest: {config.base_url}/.well-known/ai-plugin.json
FOS-Taxonomy: {config.base_url}/api/fos
OAI-PMH-Endpoint: {config.base_url}/oai
Atom-Feed: {config.base_url}/feed.xml
"""
