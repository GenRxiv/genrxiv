"""
GenRxiv API — main FastAPI application.

Mounts all routers: auth, articles, OAI-PMH, sitemap.
Initializes database schema on startup.
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

from config import config
from db import init_pool, init_schema
from auth import router as auth_router
from articles import router as articles_router
from oai import router as oai_router
from sitemap import router as sitemap_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB pool and schema on startup."""
    init_pool()
    init_schema()
    os.makedirs(config.files_dir, exist_ok=True)
    yield


app = FastAPI(
    title="GenRxiv API",
    description="An open archive for AI-generated research.",
    version="1.0.0",
    lifespan=lifespan,
)

# Mount routers
app.include_router(auth_router)
app.include_router(articles_router)
app.include_router(oai_router)
app.include_router(sitemap_router)

# Static files (CSS, JS for web pages)
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/health")
def health():
    return {"status": "ok", "service": "genrxiv-api"}


@app.get("/", response_class=HTMLResponse)
def index():
    """Simple landing redirect — the real splash page is served by nginx."""
    return HTMLResponse(
        f'<html><head><meta http-equiv="refresh" content="0;url={config.base_url}/"></head></html>'
    )
