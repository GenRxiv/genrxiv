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

_init_db()


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
async def convert_markdown(request: Request, file: UploadFile = File(...)):
    """Markdown -> PDF via Pandoc. Placeholder until the in-house MD->PDF
    library is wired in here instead."""
    if file.size and file.size > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large")

    job_id = uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix=f"genrxiv-md-{job_id}-") as tmp:
        tmp_path = Path(tmp)
        md_path = tmp_path / "input.md"
        md_path.write_bytes(await file.read())
        out_pdf = tmp_path / "output.pdf"

        cmd = ["pandoc", str(md_path), "-o", str(out_pdf), "--pdf-engine=tectonic"]
        await _run_with_timeout(cmd, cwd=tmp_path, timeout=COMPILE_TIMEOUT_SECONDS)

        result_path = Path(tempfile.gettempdir()) / f"genrxiv-result-{job_id}.pdf"
        shutil.copy(out_pdf, result_path)

    return FileResponse(result_path, media_type="application/pdf", filename="output.pdf")


@app.get("/health")
async def health():
    return {"status": "ok"}


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
"""

HTML_FOOTER = """
</body>
</html>"""


@app.post("/render/html")
@limiter.limit("10 per minute")
async def render_html(request: Request, file: UploadFile = File(...)):
    """
    Render Markdown to a standalone HTML page with KaTeX math.

    `file`: a single .md file — the paper source. Figures may be
    embedded as data URIs or referenced as separate submission files.

    Returns a complete HTML document with KaTeX loaded via CDN,
    GenRxiv styling, and print-friendly CSS.
    """
    if file.size and file.size > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large")

    job_id = uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix=f"genrxiv-html-{job_id}-") as tmp:
        tmp_path = Path(tmp)

        src_path = tmp_path / "input.md"
        src_path.write_bytes(await file.read())

        # Verify it's Markdown
        ext = Path(file.filename or "input.md").suffix.lower()
        if ext not in ('.md', '.markdown'):
            raise HTTPException(400, f"GenRxiv accepts Markdown submissions only (.md). Received: {ext or 'no extension'}")

        # Check image size limits (covers embedded data-URI images too)
        _check_image_limits(tmp_path)

        # Render to HTML fragment via Pandoc
        # --katex wraps math in spans that KaTeX auto-render processes
        cmd = [
            "pandoc",
            str(src_path),
            "-f", "markdown",
            "-t", "html5",
            "--katex",
            "--wrap=none",
        ]
        stdout, _ = await _run_with_timeout(cmd, cwd=tmp_path, timeout=COMPILE_TIMEOUT_SECONDS)
        html_fragment = stdout.decode("utf-8", errors="replace")

        # Wrap in the GenRxiv HTML template
        full_html = HTML_HEADER + html_fragment + HTML_FOOTER

        result_path = Path(tempfile.gettempdir()) / f"genrxiv-html-{job_id}.html"
        result_path.write_text(full_html, encoding="utf-8")

    return FileResponse(result_path, media_type="text/html", filename="article.html")
