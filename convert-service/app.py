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

# Official ORCID iD icon (green circle, white "iD"), self-hosted at /orcid.svg.
# Embedded here so the PDF compiler can write it into the job temp directory
# (Tectonic runs with --untrusted / no network access). The same SVG is
# served as a static asset by nginx for the HTML render.
ORCID_ICON_SVG = (
    '<svg width="32" height="32" fill="none" xmlns="http://www.w3.org/2000/svg">'
    '<path fill-rule="evenodd" clip-rule="evenodd" '
    'd="M32 16c0 8.837-7.163 16-16 16-8.838 0-16-7.163-16-16C0 7.162 7.162 0 16 0c8.837 0 16 7.162 16 16Z" '
    'fill="#A6CE39"/>'
    '<path fill-rule="evenodd" clip-rule="evenodd" '
    'd="M18.813 9.637h-5.45v13.9h5.474c4.555 0 7.35-3.378 7.35-6.95 0-1.635-.562-3.372-1.77-4.704'
    '-1.215-1.336-3.065-2.246-5.605-2.246ZM18.6 21.3h-2.813v-9.425H18.5c1.823 0 3.12.552 3.96 1.4'
    '.842.849 1.252 2.021 1.252 3.312 0 .784-.239 1.967-.993 2.948-.745.969-2.01 1.765-4.119 1.765Z'
    'm5.311-4.026c-.251 1.74-1.494 4.276-5.311 4.276h-3.063H18.6c3.817 0 5.06-2.536 5.311-4.276Z'
    'm1.812-2.405c-.657-2.601-2.85-4.982-6.91-4.982h-5.2 5.2c4.06 0 6.253 2.38 6.91 4.982Z'
    'm.215 1.718ZM8.363 9.675v13.887h2.425V9.675H8.363Z'
    'm2.175 13.637H8.612h1.925Z'
    'M9.575 8.65c.84 0 1.513-.689 1.513-1.513 0-.823-.673-1.512-1.513-1.512'
    '-.838 0-1.512.674-1.512 1.513 0 .823.672 1.512 1.512 1.512Z" fill="#fff"/>'
    '</svg>'
)

# ARK Alliance logo (inverse: white ark symbol on gold circle).
# Based on the official logo from https://arks.org/resources/ (offered for
# implementor use). Embedded here so the PDF compiler can write it into the
# job temp directory.
ARK_LOGO_SVG = (
    '<svg width="64" height="64" viewBox="0 0 682 684" xmlns="http://www.w3.org/2000/svg">'
    '<circle cx="341" cy="342" r="341" fill="#d29604"/>'
    '<path fill="#ffffff" '
    'd="m 161,164 c 0.056,6.3 2.3,13 4.1,19 0.49,1.7 1.1,5.2 2.7,6.2 3.5,2.2 17,-4.2 18,0.96'
    ' 0.7,2.9 -1.5,7.2 -1.9,10 -1.1,9.1 -2.2,19 -4.2,28 -2.6,12 -3.7,24 -5.7,36 -0.65,3.7 -0.31,11'
    ' -3,14 -2.6,2.6 -6.8,1.5 -10,1.8 -7.3,0.67 -14,1.9 -22,2.6 -32,3.1 -64,2.6 -96,1.2 0,54 8.2,106'
    ' 32,154 19,39 46,77 80,105 41,33 84,58 136,71 16,4.2 34,8.2 51,8.6 8.8,0.22 18,-1.8 26,-3.1'
    ' 26,-3.8 52,-11 76,-22 84,-36 151,-107 181,-193 14,-39 19,-79 18,-120 -32,1.4 -64,1 -96,-1.2'
    ' -7.5,-0.51 -15,-2.2 -22,-2.6 -3.3,-0.18 -7.6,0.77 -9.9,-2.3 -3.8,-5 -3.2,-18 -4.3,-24'
    ' -4.1,-21 -6.1,-43 -10,-65 l 19,1.9 6.4,-26 c -43,-5.8 -83,-15 -124,-29 -13,-4.6 -27,-10'
    ' -39,-16 -5.8,-2.8 -13,-8.9 -19,-9.1 -6.4,-0.26 -15,6.4 -21,9.2 -15,7.1 -30,13 -45,19'
    ' -25,10 -54,17 -80,21 -12,1.9 -24,2.2 -36,4.6 m 324,108 c -33,-4.5 -67,-18 -98,-31'
    ' -9.7,-4.2 -19,-8.3 -29,-13 -3.9,-2.1 -10,-6.9 -15,-6.9 -3,-0.04 -6.9,2.6 -9.6,4'
    ' -7.4,3.7 -15,8.1 -22,11 -25,10 -50,20 -76,27 -10,3 -23,8.2 -33,8.2 1.3,-29 9.7,-59 13,-88'
    ' 31,-6.4 61,-17 91,-27 8.9,-3.1 17,-7.1 26,-10 3.4,-1.3 7.2,-3.9 11,-3.7 7.1,0.3 16,5.9 22,8.5'
    ' 15,6.2 31,13 47,17 14,4.2 29,8.2 43,12 3.6,1 12,1 15,4.2 3.8,5.5 2.9,18 4.1,25 3.8,20 8.3,42'
    ' 10,63 m -157,-12 v 33 c 0,3.5 1.3,10 -0.66,13 -3,4.7 -12,7 -17,8.9 -14,5.4 -27,12 -42,17'
    ' -48,16 -97,28 -148,31 -14,0.95 -28,0.035 -42,0.035 l -6.4,-51 c 58,0 115,-5.7 172,-22 17,-5'
    ' 35,-11 52,-18 10,-4.2 22,-11 33,-13 m 286,52 c 0,12 -2.6,24 -3.8,36 -0.29,3.1 -0.36,12 -3,14'
    ' -3,2.3 -12,0.66 -16,0.66 -15,0 -28,-0.72 -43,-2.4 -38,-4.6 -75,-10 -112,-22 -22,-6.7 -42,-18'
    ' -64,-24 v 31 c 9.6,1.7 20,7.4 29,11 16,6 33,11 49,16 48,13 98,20 148,20 -0.36,5.7 -3.3,11'
    ' -5.6,16 -3.7,8.4 -7.2,17 -12,25 -1.9,3.5 -3.9,11 -7.9,12 -3.5,1.5 -7.3,-0.62 -11,-0.86'
    ' -9,-0.61 -18,-1.8 -27,-2.5 -40,-3.2 -84,-13 -121,-28 -13,-5.4 -28,-14 -42,-17 v 21 c 0,2.6'
    ' -0.74,6.6 1,8.7 2.7,3.3 9.8,4.8 14,6.3 11,4.3 22,8.8 34,12 43,13 89,27 134,27 v 3.8 c -5,2.6'
    ' -9,9.7 -13,14 -8.2,10 -17,20 -27,28 -2.9,2.3 -5.5,5.9 -9,7.4 -2.7,1.2 -6.8,-0.43 -9.6,-0.87'
    ' -8.2,-1.3 -16,-3.5 -24,-5.3 -21,-4.6 -42,-11 -62,-19 -13,-4.8 -27,-9.1 -38,-16 v 22 l 0.66,8.7'
    ' 7,3.7 20,7.7 74,22 c -7,8.5 -23,15 -33,19 -27,11 -54,21 -83,24 v -332 c 10,3 21,8.8 31,13'
    ' 18,7 36,13 54,18 56,16 112,21 170,21 m -286,26 v 36 c 0,3.6 1.4,11 -0.66,14 -2.6,4 -10,6'
    ' -15,7.6 -11,4.1 -22,10 -33,14 -42,14 -84,28 -129,31 -9.8,0.69 -19,2.5 -29,2.5 -2.5,9.4e-4'
    ' -6.7,1.4 -8.9,0.49 -3.9,-1.6 -6.6,-9.7 -8.4,-13 -6.1,-13 -14,-26 -17,-40 56,0 113,-9.3'
    ' 166,-26 16,-4.8 32,-10 47,-17 8.6,-3.5 18,-9.3 27,-11 m 0,82 v 41 c 0,3.9 1.6,12 -0.66,16'
    ' -2.5,3.6 -10,5.5 -14,7.2 -13,5.6 -25,11 -38,16 -23,7.8 -45,15 -68,20 -6.9,1.6 -20,7.1 -27,4.8'
    ' -4.2,-1.4 -7.2,-5.5 -10,-8.4 -6.1,-5.8 -12,-12 -18,-18 -6.5,-6.4 -20,-18 -21,-27 18,0 37,-3.3'
    ' 55,-6.8 29,-5.8 58,-12 86,-22 12,-4.2 24,-8.4 35,-13 7,-3 14,-7.7 22,-9.3 m 0,88 v 56 l'
    ' -0.64,27 c -30,-5.6 -59,-13 -87,-27 -9,-4.4 -22,-9 -29,-17 l 64,-18 33,-13 z"/>'
    '</svg>'
)

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


# Strips "Figure N." or "Fig. N." prefix from image alt text to prevent
# Pandoc from producing "Figure 1: Figure 1. ..." in PDF captions.
_FIG_PREFIX_RE = _re.compile(r'!\[(Figure\s+\d+\.?|Fig\.\s+\d+\.?)\s*', _re.IGNORECASE)


def _strip_figure_prefix(md_text: str) -> str:
    """Remove 'Figure N.' / 'Fig. N.' prefix from image alt text.

    Pandoc's implicit_figures feature automatically numbers figures and
    prepends 'Figure N:' to the caption. If the author also wrote
    'Figure 1.' in the alt text, the result is 'Figure 1: Figure 1. ...'
    This function strips the author's prefix so only Pandoc's remains.
    """
    return _FIG_PREFIX_RE.sub(r'![', md_text)


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
        # Strip "Figure N." prefix from image alt text to avoid
        # Pandoc producing "Figure 1: Figure 1. ..." in captions
        body_text = _strip_figure_prefix(body_text)
        md_path.write_text(body_text, encoding="utf-8")
        out_pdf = tmp_path / "output.pdf"

        # Write the ORCID and ARK logo SVGs so Pandoc can embed them in the PDF
        # (Tectonic runs with --untrusted — no network access at compile time).
        (tmp_path / "orcid.svg").write_text(ORCID_ICON_SVG, encoding="utf-8")
        (tmp_path / "ark-logo.svg").write_text(ARK_LOGO_SVG, encoding="utf-8")

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
                        f'target="_blank" rel="noopener" aria-label="ORCID iD">'
                        f'<img src="/orcid.svg" alt="ORCID iD" '
                        f'style="width:0.9em;height:0.9em;vertical-align:super;margin-left:0.2em">'
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

    ark = meta.get("ark", "")
    if ark:
        parts.append(
            f'<div class="paper-ark" style="font-size:0.85rem;color:var(--muted);'
            f'margin-top:0.5rem">'
            f'<img src="/ark-logo.svg?v=4" alt="ARK" '
            f'style="width:0.9em;height:0.9em;vertical-align:middle;margin-right:0.2em">'
            f'<a href="https://n2t.net/{_html.escape(ark)}" '
            f'style="color:inherit;text-decoration:none">{_html.escape(ark)}</a>'
            f'</div>'
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
    """Build a Markdown header block from parsed front matter metadata (for PDF).

    The ORCID icon is referenced as ``orcid.svg`` (a relative path). The
    caller must write that file into the Pandoc working directory before
    invoking Tectonic — see ORCID_ICON_SVG.
    """
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
                    # Inline image (not a figure — text precedes it) linked
                    # to the ORCID profile.
                    names.append(
                        f"{a['name']} "
                        f"[![ORCID iD](orcid.svg){{width=0.9em}}]"
                        f"(https://orcid.org/{orcid})"
                    )
                else:
                    names.append(a["name"])
        if names:
            parts.append("\n".join(names))

    abstract = meta.get("abstract", "")
    if abstract:
        parts.append(f"## Abstract\n\n{abstract}")

    ark = meta.get("ark", "")
    if ark:
        parts.append(
            f"[![ARK](ark-logo.svg){{width=0.9em}}](https://n2t.net/{ark}) {ark}"
        )

    if not parts:
        return ""

    return "\n\n".join(parts)


HTML_HEADER = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GenRxiv Preprint</title>
<meta name="description" content="">
<link rel="stylesheet" href="/css/article.css">
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
<script>
// Pandoc --katex wraps math in <span class="math inline">...</span> and
// <span class="math display">...</span>. The auto-render script above
// only looks for $...$ delimiters in text nodes, so it misses these.
// This script finds Pandoc's math spans and renders them with katex.render().
window.addEventListener('DOMContentLoaded', function() {
    if (typeof katex === 'undefined') return;
    document.querySelectorAll('span.math.inline').forEach(function(el) {
        katex.render(el.textContent, el, { throwOnError: false, displayMode: false });
    });
    document.querySelectorAll('span.math.display').forEach(function(el) {
        katex.render(el.textContent, el, { throwOnError: false, displayMode: true });
    });
});
</script>
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

        # Strip "Figure N." prefix from image alt text to avoid
        # duplicate captions ("Figure 1: Figure 1. ...")
        body_text = _strip_figure_prefix(body_text)

        # Extract BibTeX citations if present and prepare citeproc args.
        # _prepare_citations writes the cleaned markdown (without the
        # bibtex block) to tmp_path / "input.md" and returns pandoc args.
        cite_args = _prepare_citations(tmp_path, body_text)

        # Use the cleaned markdown if citations were found, otherwise
        # write the original body for Pandoc.
        if cite_args:
            body_path = tmp_path / "input.md"
        else:
            body_path = tmp_path / "body.md"
            body_path.write_text(body_text, encoding="utf-8")

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
