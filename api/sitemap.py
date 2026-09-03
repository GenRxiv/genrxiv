"""
GenRxiv API — sitemap, robots.txt, and web pages.
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


@router.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    """robots.txt — allow all, point to sitemap."""
    return f"""User-agent: *
Allow: /
Disallow: /admin/
Disallow: /api/submit

Sitemap: {config.base_url}/sitemap.xml
"""
