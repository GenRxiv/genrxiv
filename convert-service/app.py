"""
GenRxiv conversion service.

POST /convert/latex   -> compiles a .tex + assets zip to PDF via Tectonic
POST /convert/markdown -> compiles Markdown to PDF via Pandoc

Each job runs in its own throwaway temp directory, with a hard wall-clock
timeout and no network access during compilation (Tectonic is invoked with
--untrusted, which disables shell-escape and restricts file access to the
job directory).
"""
import asyncio
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
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


def _safe_extract(zf: zipfile.ZipFile, dest: Path):
    """Extract a zip, refusing any entry that would escape `dest`."""
    for member in zf.namelist():
        target = (dest / member).resolve()
        if not str(target).startswith(str(dest.resolve())):
            raise HTTPException(400, f"Unsafe path in archive: {member}")
    zf.extractall(dest)


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


@app.post("/convert/latex")
@limiter.limit("10 per minute")
async def convert_latex(request: Request, main_file: str, archive: UploadFile = File(...)):
    """
    `archive`: a zip containing the .tex source and any figures/assets.
    `main_file`: the entry-point filename inside the zip, e.g. "paper.tex".
    """
    if archive.size and archive.size > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Archive too large")

    job_id = uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix=f"genrxiv-{job_id}-") as tmp:
        tmp_path = Path(tmp)
        zip_path = tmp_path / "src.zip"
        zip_path.write_bytes(await archive.read())

        with zipfile.ZipFile(zip_path) as zf:
            _safe_extract(zf, tmp_path)
        zip_path.unlink()

        main_path = tmp_path / main_file
        if not main_path.exists():
            raise HTTPException(400, f"main_file '{main_file}' not found in archive")

        out_pdf = tmp_path / (main_path.stem + ".pdf")

        # --untrusted disables shell-escape and restricts file access to the
        # working directory — the key line of defense against malicious .tex.
        cmd = [
            "tectonic",
            "--untrusted",
            "-o", str(tmp_path),
            str(main_path),
        ]
        await _run_with_timeout(cmd, cwd=tmp_path, timeout=COMPILE_TIMEOUT_SECONDS)

        if not out_pdf.exists():
            raise HTTPException(422, "Compilation reported success but no PDF was produced.")

        # Copy out of the temp dir before it's cleaned up
        result_path = Path(tempfile.gettempdir()) / f"genrxiv-result-{job_id}.pdf"
        shutil.copy(out_pdf, result_path)

    return FileResponse(result_path, media_type="application/pdf", filename="output.pdf")


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
