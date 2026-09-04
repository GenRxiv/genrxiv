"""
GenRxiv conversion service.

POST /render/html      -> renders Markdown to HTML with KaTeX math (primary)
POST /convert/markdown -> compiles Markdown to PDF via Pandoc + Tectonic (download)
POST /signup           -> stores launch-notification email signups

Each job runs in its own throwaway temp directory, with a hard wall-clock
timeout and no network access during compilation (Tectonic is invoked with
--untrusted, which disables shell-escape and restricts file access to the
job directory).

GenRxiv accepts Markdown submissions only — no LaTeX uploads, no PDF uploads.
The Markdown source is the version of record; HTML and PDF are renders.
"""
import asyncio
import json as _json
import re
import shutil
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from pydantic import BaseModel, EmailStr

from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

app = FastAPI(title="GenRxiv Conversion Service")

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://genrxiv.org", "http://localhost:8080"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

DB_PATH = Path("/data/signups.db")

def _init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS signups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            notify_launch INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

# Initialize the signup database — tolerate failure in environments where
# the default path isn't writable (e.g. CI runners without /data/).
# Tests monkeypatch DB_PATH and re-init before use.
try:
    _init_db()
except (OSError, PermissionError):
    pass


class SignupRequest(BaseModel):
    email: EmailStr
    notify_on_launch: bool = False


@app.post("/signup")
@limiter.limit("5 per minute, 20 per hour")
async def signup(req: SignupRequest, request: Request):
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute(
            "INSERT OR IGNORE INTO signups (email, notify_launch, created_at) VALUES (?, ?, ?)",
            (req.email, int(req.notify_on_launch), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok", "email": req.email}

COMPILE_TIMEOUT_SECONDS = 60
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25MB — plenty for source + figures
MAX_IMAGE_BYTES = 500 * 1024  # 500KB per image
MAX_TOTAL_IMAGE_BYTES = 2 * 1024 * 1024  # 2MB total images per submission


def _check_image_limits(tmp_path: Path):
    """Check that images in the job directory stay within size limits."""
    image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.tiff'}
    total = 0
    for f in tmp_path.rglob('*'):
        if f.is_file() and f.suffix.lower() in image_extensions:
            if f.stat().st_size > MAX_IMAGE_BYTES:
                raise HTTPException(
                    413,
                    f"Image '{f.name}' is {f.stat().st_size // 1024}KB — limit is {MAX_IMAGE_BYTES // 1024}KB per image. Use SVG or compress the image.",
                )
            total += f.stat().st_size
    if total > MAX_TOTAL_IMAGE_BYTES:
        raise HTTPException(
            413,
            f"Total image size is {total // 1024}KB — limit is {MAX_TOTAL_IMAGE_BYTES // 1024 // 1024}MB per submission. Use SVG figures where possible.",
        )


# ─── Citation handling ──────────────────────────────────────────────────────

# IEEE-style numbered citations (citation-order)
IEEE_CSL = """<?xml version="1.0" encoding="utf-8"?>
<style xmlns="http://purl.org/net/xbib/CSL" class="in-text" version="1.0" default-locale="en-US">
  <citation collapse="citation-number">
    <sort>
      <key variable="citation-number"/>
    </sort>
    <layout prefix="[" suffix="]" delimiter=", ">
      <text variable="citation-number"/>
    </layout>
  </citation>
  <bibliography entry-spacing="0" second-field-align="flush">
    <layout suffix=".">
      <text variable="citation-number" prefix="[" suffix="] "/>
      <names variable="author">
        <name sort-separator=", " initialize-with=". " delimiter=", " and="text" delimiter-precedes-last="always"/>
        <label form="short" prefix=", "/>
        <substitute>
          <text variable="title"/>
        </substitute>
      </names>
      <text variable="title" prefix=", " quotes="true"/>
      <text variable="container-title" prefix=", " font-style="italic"/>
      <date variable="issued" prefix=", ">
        <date-part name="year"/>
      </date>
      <text variable="volume" prefix=", vol. "/>
      <text variable="page" prefix=", pp. "/>
      <text variable="publisher" prefix=", "/>
    </layout>
  </bibliography>
</style>"""

import re as _re

BIBTEX_BLOCK_RE = _re.compile(r"```bibtex\n(.*?)```", _re.DOTALL)


def _extract_bibtex(md_text: str) -> tuple[str, str | None]:
    """Extract BibTeX from a ```bibtex fenced code block.

    Returns (markdown_without_bibtex_block, bibtex_content).
    If no BibTeX block is found, returns (original_markdown, None).
    """
    match = BIBTEX_BLOCK_RE.search(md_text)
    if not match:
        return md_text, None
    bibtex = match.group(1).strip()
    # Remove the bibtex code block from the markdown
    # Also remove the preceding "## References" heading if it's
    # immediately before the block and there's nothing else
    cleaned = BIBTEX_BLOCK_RE.sub("", md_text)
    # Clean up any empty references heading left behind
    cleaned = _re.sub(r"## References\s*\n\s*\n", "", cleaned)
    return cleaned, bibtex


def _prepare_citations(tmp_path: Path, md_text: str) -> list[str]:
    """Extract BibTeX and write .bib and .csl files if citations are present.

    Returns extra Pandoc args to add. If no BibTeX block is found,
    returns an empty list (no citeproc).
    """
    cleaned_md, bibtex = _extract_bibtex(md_text)
    if not bibtex:
        return []

    bib_path = tmp_path / "refs.bib"
    bib_path.write_text(bibtex, encoding="utf-8")

    csl_path = tmp_path / "ieee.csl"
    csl_path.write_text(IEEE_CSL, encoding="utf-8")

    # Write the cleaned markdown back (without the bibtex block)
    (tmp_path / "input.md").write_text(cleaned_md, encoding="utf-8")

    return ["--citeproc", f"--bibliography={bib_path}", f"--csl={csl_path}"]


async def _run_with_timeout(cmd: list[str], cwd: Path, timeout: int):
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise HTTPException(422, "Compilation exceeded time limit — check for infinite loops or oversized packages.")
    if proc.returncode != 0:
        raise HTTPException(422, f"Compilation failed:\n{stderr.decode(errors='replace')[-4000:]}")
    return stdout, stderr


@app.post("/convert/markdown")
@limiter.limit("10 per minute")
async def convert_markdown(
    request: Request,
    file: UploadFile = File(...),
):
    """Markdown -> PDF via Pandoc + Tectonic.

    The Markdown file should include YAML front matter with title,
    authors, and abstract; these are prepended to the body as a
    header block in the PDF.
    """
    if file.size and file.size > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large")

    job_id = uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix=f"genrxiv-md-{job_id}-") as tmp:
        tmp_path = Path(tmp)
        md_path = tmp_path / "input.md"
        md_bytes = await file.read()
        md_text = md_bytes.decode("utf-8", errors="replace")

        # Parse front matter and extract body
        meta, body_text = _parse_front_matter(md_text)

        # Prepend metadata as Markdown header
        header_md = _build_metadata_markdown_from_meta(meta)
        if header_md:
            body_text = header_md + "\n\n" + body_text
        md_path.write_text(body_text, encoding="utf-8")
        out_pdf = tmp_path / "output.pdf"

        # Extract BibTeX citations if present
        cite_args = _prepare_citations(tmp_path, body_text)

        cmd = ["pandoc", str(md_path), "-o", str(out_pdf), "--pdf-engine=tectonic"] + cite_args
        await _run_with_timeout(cmd, cwd=tmp_path, timeout=COMPILE_TIMEOUT_SECONDS)

        result_path = Path(tempfile.gettempdir()) / f"genrxiv-result-{job_id}.pdf"
        shutil.copy(out_pdf, result_path)

    return FileResponse(result_path, media_type="application/pdf", filename="output.pdf")


@app.get("/health")
async def health():
    return {"status": "ok"}


def _parse_front_matter(md_text: str) -> tuple[dict, str]:
    """Parse YAML front matter from Markdown using PyYAML.

    Returns (metadata_dict, body_text).
    metadata_dict has keys: title, abstract, authors (list of {orcid, name}).
    body_text is the Markdown without the front matter.
    """
    import yaml

    # Allow no trailing newline after closing ---
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n?', md_text, re.DOTALL)
    if not m:
        return {}, md_text

    yaml_text = m.group(1)
    body = md_text[m.end():]

    try:
        meta = yaml.safe_load(yaml_text)
    except yaml.YAMLError:
        return {}, md_text

    if not isinstance(meta, dict):
        return {}, md_text

    return meta, body


def _build_metadata_header_from_meta(meta: dict) -> str:
    """Build an HTML header block from parsed front matter metadata."""
    import html as _html

    parts = []
    title = meta.get("title", "")
    if title:
        parts.append(f'<h1 class="paper-title">{_html.escape(title)}</h1>')

    authors = meta.get("authors", [])
    if isinstance(authors, list) and authors:
        author_names = []
        for a in authors:
            if isinstance(a, dict) and a.get("name"):
                name = _html.escape(a["name"])
                orcid = a.get("orcid", "")
                if orcid:
                    author_names.append(
                        f'<span class="paper-author">{name} '
                        f'<a href="https://orcid.org/{_html.escape(orcid)}" '
                        f'target="_blank" rel="noopener">'
                        f'<img src="https://orcid.org/static/vectors/orcid.icon.svg" '
                        f'alt="ORCID" style="width:0.9em;height:0.9em;vertical-align:middle;margin-left:0.2em">'
                        f'</a></span>'
                    )
                else:
                    author_names.append(f'<span class="paper-author">{name}</span>')
        if author_names:
            parts.append('<div class="paper-authors">' + ", ".join(author_names) + "</div>")

    abstract = meta.get("abstract", "")
    if abstract:
        parts.append(
            f'<div class="paper-abstract"><h2>Abstract</h2>'
            f'<p>{_html.escape(abstract)}</p></div>'
        )

    if not parts:
        return ""

    return (
        '<div class="paper-header" style="margin-bottom:2rem;padding-bottom:1.5rem;'
        'border-bottom:1px solid var(--muted);">'
        + "".join(parts)
        + "</div>"
    )


def _build_metadata_markdown_from_meta(meta: dict) -> str:
    """Build a Markdown header block from parsed front matter metadata (for PDF)."""
    parts = []
    title = meta.get("title", "")
    if title:
        parts.append(f"# {title}")

    authors = meta.get("authors", [])
    if isinstance(authors, list) and authors:
        names = []
        for a in authors:
            if isinstance(a, dict) and a.get("name"):
                orcid = a.get("orcid", "")
                if orcid:
                    names.append(f"{a['name']} (ORCID: {orcid})")
                else:
                    names.append(a["name"])
        if names:
            parts.append("\n".join(names))

    abstract = meta.get("abstract", "")
    if abstract:
        parts.append(f"## Abstract\n\n{abstract}")

    if not parts:
        return ""

    return "\n\n".join(parts)


HTML_HEADER = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GenRxiv Preprint</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js"
    onload="renderMathInElement(document.body, {
        delimiters: [
            {left: '$$', right: '$$', display: true},
            {left: '$', right: '$', display: false},
            {left: '\\\\[', right: '\\\\]', display: true},
            {left: '\\\\(', right: '\\\\)', display: false},
        ],
        throwOnError: false,
    });"></script>
<style>
:root {
    --paper: #EDEAE2;
    --ink: #1B1E27;
    --cobalt: #2F5CFF;
    --muted: #C9C3B5;
}
body {
    font-family: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, sans-serif;
    color: var(--ink);
    background: var(--paper);
    max-width: 46rem;
    margin: 0 auto;
    padding: 2rem 1.5rem;
    line-height: 1.7;
    font-size: 1.05rem;
}
h1, h2, h3, h4, h5, h6 {
    font-family: 'Fraunces', Georgia, serif;
    line-height: 1.3;
}
h1 { font-size: 2rem; margin-top: 2rem; }
h2 { font-size: 1.5rem; margin-top: 1.8rem; }
a { color: var(--cobalt); }
figure { margin: 2rem 0; text-align: center; }
figure img, img { max-width: 100%; height: auto; }
figcaption { font-size: 0.9rem; color: #666; margin-top: 0.5rem; }
code {
    font-family: 'IBM Plex Mono', monospace;
    background: rgba(0,0,0,0.05);
    padding: 0.15em 0.3em;
    border-radius: 3px;
    font-size: 0.9em;
}
pre {
    background: rgba(0,0,0,0.05);
    padding: 1rem;
    border-radius: 6px;
    overflow-x: auto;
}
pre code { background: none; padding: 0; }
blockquote {
    border-left: 3px solid var(--cobalt);
    margin: 1.5rem 0;
    padding: 0.5rem 1.5rem;
    color: #555;
}
table { border-collapse: collapse; width: 100%; margin: 1.5rem 0; }
th, td { border: 1px solid var(--muted); padding: 0.5rem 0.75rem; text-align: left; }
th { background: rgba(0,0,0,0.03); }
.katex-display { overflow-x: auto; overflow-y: hidden; padding: 0.5rem 0; }
.paper-title { margin-bottom: 0.5rem; }
.paper-authors { font-size: 1.1rem; color: #444; margin-bottom: 1rem; }
.paper-author { white-space: nowrap; }
.paper-abstract h2 { font-size: 1.2rem; margin-bottom: 0.3rem; }
.paper-abstract p { font-size: 0.95rem; color: #444; }

@media print {
    body {
        background: #fff;
        max-width: none;
        padding: 0;
        font-size: 11pt;
    }
    .no-print { display: none !important; }
    a { color: inherit; text-decoration: none; }
    pre, blockquote, figure { break-inside: avoid; }
    h1, h2, h3 { break-after: avoid; }
}
</style>
</head>
<body>
<div style="background:rgba(47,92,255,0.08);border:1px solid rgba(47,92,255,0.2);border-radius:6px;padding:0.75rem 1rem;margin-bottom:2rem;font-size:0.9rem;color:var(--ink);">
<strong>AI-generated research.</strong> This article was generated or co-generated using AI and reviewed by the author(s) before submission to GenRxiv.
</div>
"""

HTML_FOOTER = """
</body>
</html>"""


@app.post("/render/html")
@limiter.limit("10 per minute")
async def render_html(
    request: Request,
    file: UploadFile = File(...),
):
    """
    Render Markdown to a standalone HTML page with KaTeX math.

    `file`: a single .md file — the paper source. The file should
    include YAML front matter with title, authors, and abstract;
    these are rendered as a header block at the top of the document.

    Returns a complete HTML document with KaTeX loaded via CDN,
    GenRxiv styling, and print-friendly CSS.
    """
    if file.size and file.size > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large")

    job_id = uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix=f"genrxiv-html-{job_id}-") as tmp:
        tmp_path = Path(tmp)

        src_path = tmp_path / "input.md"
        md_bytes = await file.read()
        src_path.write_bytes(md_bytes)

        # Verify it's Markdown
        ext = Path(file.filename or "input.md").suffix.lower()
        if ext not in ('.md', '.markdown'):
            raise HTTPException(400, f"GenRxiv accepts Markdown submissions only (.md). Received: {ext or 'no extension'}")

        # Check image size limits (covers embedded data-URI images too)
        _check_image_limits(tmp_path)

        # Parse front matter and extract body
        md_text = md_bytes.decode("utf-8", errors="replace")
        meta, body_text = _parse_front_matter(md_text)

        # Write the body (without front matter) for Pandoc
        body_path = tmp_path / "body.md"
        body_path.write_text(body_text, encoding="utf-8")

        # Extract BibTeX citations if present and prepare citeproc args
        cite_args = _prepare_citations(tmp_path, body_text)

        # Render to HTML fragment via Pandoc
        cmd = [
            "pandoc",
            str(body_path),
            "-f", "markdown",
            "-t", "html5",
            "--katex",
            "--wrap=none",
        ] + cite_args
        stdout, _ = await _run_with_timeout(cmd, cwd=tmp_path, timeout=COMPILE_TIMEOUT_SECONDS)
        html_fragment = stdout.decode("utf-8", errors="replace")

        # Build metadata header from front matter and wrap in the GenRxiv HTML template
        meta_header = _build_metadata_header_from_meta(meta)
        full_html = HTML_HEADER + meta_header + html_fragment + HTML_FOOTER

        result_path = Path(tempfile.gettempdir()) / f"genrxiv-html-{job_id}.html"
        result_path.write_text(full_html, encoding="utf-8")

    return FileResponse(result_path, media_type="text/html", filename="article.html")
