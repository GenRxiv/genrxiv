"""
GenRxiv API — article submission, viewing, and moderation.
"""
import hashlib
import io
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

import httpx2 as httpx
from fastapi import APIRouter, Request, HTTPException, Depends, UploadFile, File, Form, Query
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, field_validator

from config import config
from db import get_conn
from auth import get_current_author, require_author, require_admin, require_reviewer
from notifications import notify_approved, notify_rejected
from ratelimit import limiter

router = APIRouter()
logger = logging.getLogger(__name__)

# ─── Constants ─────────────────────────────────────────────────────────────

MAX_TITLE_LENGTH = 500
MAX_ABSTRACT_LENGTH = 5000
MAX_SUBJECTS = 20
MAX_SUBJECT_LENGTH = 100
MAX_AUTHORS = 50
MAX_MARKDOWN_SIZE = 25 * 1024 * 1024  # 25 MB
ALLOWED_EXTENSIONS = {".md", ".markdown"}
ALLOWED_LICENSES = {
    "CC0": "https://creativecommons.org/publicdomain/zero/1.0/",
}

ORCID_PATTERN = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


def _yaml_escape(value: str) -> str:
    """Escape a string for use as a double-quoted YAML scalar."""
    # Escape backslashes and double quotes
    return value.replace("\\", "\\\\").replace('"', '\\"')


_FRONT_MATTER_RE = re.compile(r'^---\s*\n(.*?)\n---\s*\n?', re.DOTALL)


def _strip_front_matter(md_text: str) -> str:
    """Remove YAML front matter from Markdown, returning just the body."""
    m = _FRONT_MATTER_RE.match(md_text)
    if m:
        return md_text[m.end():]
    return md_text


def _extract_front_matter(md_text: str) -> dict | None:
    """Parse YAML front matter from a Markdown file using PyYAML.

    Returns a dict with keys like title, abstract, authors, subjects,
    or None if the file has no front matter or parsing fails.
    """
    m = _FRONT_MATTER_RE.match(md_text)
    if not m:
        return None
    yaml_text = m.group(1)
    try:
        import yaml
        data = yaml.safe_load(yaml_text)
        if not isinstance(data, dict):
            return None
        return data
    except Exception:
        return None


def _merge_front_matter(md_text: str, title: str, authors: list[dict], abstract: str, subjects: list[str] | None = None) -> str:
    """Merge form metadata into the Markdown file as YAML front matter.

    If the file already has front matter, the form values override it.
    If not, a new front matter block is prepended.
    The stored file is always a complete document with front matter
    including title, abstract, authors, and subjects.
    """
    body = _strip_front_matter(md_text)

    # Build YAML front matter from form data
    lines = ["---"]
    lines.append(f'title: "{_yaml_escape(title)}"')
    lines.append(f'abstract: "{_yaml_escape(abstract)}"')
    lines.append("authors:")
    for a in authors:
        lines.append(f'  - orcid: "{_yaml_escape(a["orcid"])}"')
        lines.append(f'    name: "{_yaml_escape(a["name"])}"')
        if a.get("affiliation"):
            lines.append(f'    affiliation: "{_yaml_escape(a["affiliation"])}"')
    if subjects:
        lines.append("subjects:")
        for s in subjects:
            lines.append(f'  - "{_yaml_escape(s)}"')
    lines.append("---")

    front_matter = "\n".join(lines)
    return front_matter + "\n\n" + body


def _check_duplicate_content(md_text: str, title: str, abstract: str) -> list[str]:
    """Check for title/abstract/references duplicated in both front matter and body.

    Returns a list of error messages (empty if no duplicates found).
    This is the subset of _check_content_issues that is enforced on
    both /api/submit and /api/validate.
    """
    all_errors, _ = _check_content_issues(md_text, title, abstract)
    # Only return the duplication errors (title, abstract, references, ORCID)
    dup_keywords = ["front matter", "rendered twice", "bibtex block", "malformed ORCID"]
    return [e for e in all_errors if any(kw in e.lower() for kw in dup_keywords)]


def _content_hash(md_text: str) -> str:
    """Compute a normalised hash of the markdown body for duplicate detection.

    Strips YAML front matter and whitespace differences so that
    re-uploads of the same paper (with minor formatting changes) still
    match.
    """
    body = _strip_front_matter(md_text)
    # Normalise: collapse whitespace, strip leading/trailing
    normalised = re.sub(r"\s+", " ", body).strip().lower()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def check_duplicate_submission(
    title: str,
    md_text: str,
    author_id: int,
    exclude_id: int | None = None,
) -> list[dict]:
    """Check for duplicate submissions in the database.

    Returns a list of matching articles (id, title, status, submitted_at).
    A match is either:
    - The same content hash (normalised body text matches)
    - The same title (case-insensitive) by the same author

    Excludes the article with ``exclude_id`` (used when submitting a new
    version, which legitimately has the same content).
    """
    body = _strip_front_matter(md_text)
    normalised = re.sub(r"\s+", " ", body).strip().lower()
    content_hash = hashlib.sha256(normalised.encode("utf-8")).hexdigest()
    title_lower = title.strip().lower()

    # Fetch candidate rows by title, then compare content hash in Python.
    # This avoids a full-table scan on the large source_markdown column.
    with get_conn().connection() as conn:
        if exclude_id is not None:
            rows = conn.execute(
                """SELECT id, title, status, submitted_at, source_markdown
                   FROM articles
                   WHERE LOWER(TRIM(title)) = %s AND id != %s
                   ORDER BY id""",
                (title_lower, exclude_id),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, title, status, submitted_at, source_markdown
                   FROM articles
                   WHERE LOWER(TRIM(title)) = %s
                   ORDER BY id""",
                (title_lower,),
            ).fetchall()

    matches = []
    for r in rows:
        row_body = _strip_front_matter(r["source_markdown"])
        row_normalised = re.sub(r"\s+", " ", row_body).strip().lower()
        row_hash = hashlib.sha256(row_normalised.encode("utf-8")).hexdigest()
        if row_hash == content_hash:
            matches.append({
                "id": r["id"],
                "title": r["title"],
                "status": r["status"],
                "submitted_at": r["submitted_at"].isoformat() if r["submitted_at"] else None,
                "match_type": "content",
            })
        else:
            # Same title, different content — still flag it
            matches.append({
                "id": r["id"],
                "title": r["title"],
                "status": r["status"],
                "submitted_at": r["submitted_at"].isoformat() if r["submitted_at"] else None,
                "match_type": "title",
            })
    return matches


def _check_content_issues(md_text: str, title: str, abstract: str) -> tuple[list[str], list[str]]:
    """Check for content issues in the Markdown file.

    Returns (errors, hints).
    Errors are blocking — the submission is rejected.
    Hints are non-blocking suggestions.
    """
    errors = []
    hints = []

    # Parse front matter — allow no trailing newline after closing ---
    fm_match = re.match(r'^---\s*\n(.*?)\n---\s*\n?', md_text, re.DOTALL)
    if not fm_match:
        # No front matter — check body-only issues
        body_text = md_text
    else:
        fm_yaml = fm_match.group(1)
        body_text = md_text[fm_match.end():]

        # ── Duplicate title: front matter + H1 in body ──
        fm_title_match = re.search(r'^title:\s*["\']?(.*?)["\']?\s*$', fm_yaml, re.MULTILINE)
        has_fm_title = bool(fm_title_match) or bool(title)
        effective_title = (fm_title_match.group(1).strip() if fm_title_match else "") or title

        if has_fm_title and effective_title:
            body_h1_match = re.match(r'^#\s+(.+?)\s*$', body_text, re.MULTILINE)
            if body_h1_match:
                body_h1 = body_h1_match.group(1).strip()
                if body_h1.lower() == effective_title.lower():
                    errors.append(
                        f'Title "{effective_title}" appears in both YAML front matter and as '
                        f'an H1 ("# {body_h1}") in the body. Remove the H1 from the body — '
                        f'the front matter title is rendered as the document header.'
                    )

        # ── Duplicate abstract: front matter + ## Abstract in body ──
        fm_abstract_match = re.search(r'^abstract:\s*["\']?(.*?)["\']?\s*$', fm_yaml, re.MULTILINE)
        has_fm_abstract = bool(fm_abstract_match) or bool(abstract)

        if has_fm_abstract and re.search(r'^##\s*[Aa]bstract\s*$', body_text, re.MULTILINE):
            errors.append(
                'Abstract appears in both YAML front matter and as a "## Abstract" section '
                'in the body. Remove the abstract section from the body — the front matter '
                'abstract is rendered as the document header.'
            )

        # ── Duplicate references: BibTeX block + manual references section ──
        has_bibtex = "```bibtex" in md_text
        if has_bibtex:
            ref_pattern = re.search(
                r'^##\s+(References|Bibliography|Works Cited|Literature Cited)\s*$',
                body_text, re.MULTILINE | re.IGNORECASE,
            )
            if ref_pattern:
                errors.append(
                    f'A "{ref_pattern.group(1)}" section was found in the body alongside a '
                    f'```bibtex block. The BibTeX block is used to render numbered references '
                    f'automatically — remove the manual "{ref_pattern.group(1)}" section from '
                    f'the body to avoid duplication.'
                )

        # ── Front matter ORCID validation ──
        # Check that authors in the front matter have valid ORCID format
        fm_authors_match = re.search(r'^authors:\s*$', fm_yaml, re.MULTILINE)
        if fm_authors_match:
            # Find all orcid: entries in the authors list
            for orc_match in re.finditer(r'^\s+-\s+orcid:\s*["\']?(.*?)["\']?\s*$', fm_yaml, re.MULTILINE):
                fm_orcid = orc_match.group(1).strip()
                if fm_orcid and not ORCID_PATTERN.match(fm_orcid):
                    errors.append(
                        f'Front matter author has malformed ORCID "{fm_orcid}" — '
                        f'ORCIDs must be in the format XXXX-XXXX-XXXX-XXX(X).'
                    )

    # ── Citation consistency: @citekeys vs BibTeX entries ──
    # Extract all @citekey references from the body, EXCLUDING:
    # - The BibTeX block itself (where @misc, @article etc. are entry types)
    # - Inline code spans (where `@citekey` is a literal example, not a citation)
    body_without_bibtex = re.sub(r'```bibtex\n.*?```', '', body_text, flags=re.DOTALL)
    body_without_code = re.sub(r'`[^`]*`', '', body_without_bibtex)
    citekeys_used = set(re.findall(r'@(\w[\w-]*)', body_without_code))

    # Extract all BibTeX entry keys from ```bibtex blocks
    bibtex_keys = set()
    bibtex_blocks = re.findall(r'```bibtex\n(.*?)```', md_text, re.DOTALL)
    for block in bibtex_blocks:
        for key_match in re.finditer(r'@\w+\s*\{\s*([^,\s]+)\s*,', block):
            bibtex_keys.add(key_match.group(1))

    if citekeys_used and bibtex_keys:
        undefined = citekeys_used - bibtex_keys
        if undefined:
            for ck in sorted(undefined):
                errors.append(
                    f'Citation @{ck} is used in the body but not defined in the BibTeX block. '
                    f'Add an entry for @{ck} or remove the citation.'
                )

        unused = bibtex_keys - citekeys_used
        for ck in sorted(unused):
            hints.append(
                f'BibTeX entry @{ck} is defined but never cited in the body. '
                f'Consider removing it if it is not needed.'
            )

    # ── Empty sections: ## heading with no content before next heading ──
    # Match headings and check if there's content between them
    heading_positions = []
    for m in re.finditer(r'^(#{1,6})\s+(.+?)\s*$', body_text, re.MULTILINE):
        heading_positions.append((m.start(), m.end(), len(m.group(1)), m.group(2)))

    for i, (start, end, level, heading_text) in enumerate(heading_positions):
        # Get text between this heading and the next
        if i + 1 < len(heading_positions):
            section_text = body_text[end:heading_positions[i + 1][0]]
        else:
            section_text = body_text[end:]

        # Strip whitespace and check if empty
        if not section_text.strip():
            errors.append(
                f'Section "{heading_text}" ({"#" * level}) is empty — '
                f'add content or remove the heading.'
            )

    # ── Heading hierarchy: skipped levels ──
    prev_level = 0
    for _, _, level, heading_text in heading_positions:
        if prev_level > 0 and level > prev_level + 1:
            hints.append(
                f'Heading "{heading_text}" ({"#" * level}) skips a level after '
                f'a level-{prev_level} heading. Consider using {"#" * (prev_level + 1)} instead.'
            )
        prev_level = level

    # ── Minimum content length ──
    # Count words in the body (excluding front matter, code blocks, and headings)
    body_for_count = re.sub(r'```[\s\S]*?```', '', body_text)  # Remove code blocks
    body_for_count = re.sub(r'^#{1,6}\s+.*$', '', body_for_count, flags=re.MULTILINE)  # Remove headings
    word_count = len(body_for_count.split())
    if word_count < 200:
        errors.append(
            f'Body content is only {word_count} words — submissions should have '
            f'at least 200 words of substantive content.'
        )

    return errors, hints


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


def validate_orcid(orcid: str) -> str:
    """Validate ORCID iD format (0000-0000-0000-000X)."""
    orcid = orcid.strip()
    if not ORCID_PATTERN.match(orcid):
        raise HTTPException(400, f"Invalid ORCID format: {orcid}")
    return orcid


def validate_title(title: str) -> str:
    """Validate article title."""
    title = title.strip()
    if not title:
        raise HTTPException(400, "Title is required")
    if len(title) > MAX_TITLE_LENGTH:
        raise HTTPException(400, f"Title too long (max {MAX_TITLE_LENGTH} chars)")
    return title


# ─── BibTeX extraction ──────────────────────────────────────────────────────

_BIBTEX_BLOCK_RE = re.compile(r"```bibtex\n(.*?)```", re.DOTALL)


def extract_bibtex(markdown: str) -> str | None:
    """Extract BibTeX content from a ```bibtex fenced code block in Markdown.

    Returns the raw BibTeX text, or None if no block is found.
    """
    match = _BIBTEX_BLOCK_RE.search(markdown)
    if not match:
        return None
    return match.group(1).strip()


def parse_bibtex_entries(bibtex: str) -> list[dict]:
    """Parse BibTeX entries into a list of dicts with key fields.

    This is a lightweight parser — it extracts entry type, key, author,
    title, year, journal/publisher, and volume/pages. It does not
    implement the full BibTeX spec.
    """
    entries = []
    # Match @type{key, ... }
    for m in re.finditer(r"@(\w+)\s*\{([^,]+),\s*(.*?)\n\}", bibtex, re.DOTALL):
        entry_type = m.group(1).lower()
        key = m.group(2).strip()
        body = m.group(3)
        entry = {"type": entry_type, "key": key}

        for field_match in re.finditer(r'(\w+)\s*=\s*[\{"]([^}"]*)[}"]', body):
            field = field_match.group(1).lower()
            value = field_match.group(2).strip()
            if field in ("author", "title", "year", "journal",
                         "publisher", "volume", "pages", "booktitle",
                         "doi", "url"):
                entry[field] = value

        entries.append(entry)
    return entries


def validate_subjects(subjects: list[str]) -> list[str]:
    """Validate subject classification list."""
    if len(subjects) > MAX_SUBJECTS:
        raise HTTPException(400, f"Too many subjects (max {MAX_SUBJECTS})")
    cleaned = []
    for subj in subjects:
        subj = subj.strip()
        if not subj:
            continue
        if len(subj) > MAX_SUBJECT_LENGTH:
            raise HTTPException(400, f"Subject too long (max {MAX_SUBJECT_LENGTH} chars): {subj[:50]}")
        cleaned.append(subj)
    return cleaned


def _get_all_fos_strings() -> set[str]:
    """Get all valid FOS classification strings from the taxonomy."""
    from web import OECD_FOS
    fos = set()
    for domain, subdomains in OECD_FOS.items():
        for sub in subdomains:
            fos.add(f"{domain} > {sub}")
    return fos


def parse_subjects_string(subjects_str: str) -> list[str]:
    """Parse a subjects string into a list, handling FOS names with commas.

    FOS names like "Engineering and technology > Electrical, electronic, information engineering"
    contain commas, so simple comma-splitting breaks them. This function tries
    matching against the known FOS taxonomy first, then falls back to comma-splitting.
    """
    if not subjects_str:
        return []
    subjects_str = subjects_str.strip()

    # Try matching against known FOS strings
    all_fos = _get_all_fos_strings()
    if all_fos:
        found = []
        remaining = subjects_str
        # Sort by length descending so longer matches are found first
        for fos in sorted(all_fos, key=len, reverse=True):
            if fos in remaining:
                found.append(fos)
                remaining = remaining.replace(fos, "", 1).strip(" ,")
        if found:
            return found

    # Fallback: split by comma
    return [s.strip() for s in subjects_str.split(",") if s.strip()]


def validate_license(license: str, license_url: str) -> tuple[str, str]:
    """Validate license and return (license, license_url)."""
    if license not in ALLOWED_LICENSES:
        raise HTTPException(400, f"Unsupported license: {license}. Allowed: {', '.join(ALLOWED_LICENSES)}")
    url = license_url or ALLOWED_LICENSES[license]
    if url != ALLOWED_LICENSES[license]:
        raise HTTPException(400, f"License URL does not match license {license}")
    return license, url


def assign_ark(article_id: int) -> str:
    """Assign a year-based ARK to an article.

    Format: ark:NAAN/genrxiv-YYYY-NNNNN
    Where YYYY is the publication year and NNNNN is a zero-padded sequential
    article ID (5 digits, allowing up to 99,999 articles per year).

    The base name uses dashes (not dots) so that ARK variant syntax
    (.v3, .pdf, .v3.pdf) works without ambiguity.
    """
    from datetime import datetime
    year = datetime.now().year
    return f"ark:{config.ark_naan}/genrxiv-{year}-{article_id:05d}"


def normalize_ark(ark: str) -> str:
    """Normalize an ARK by stripping the extra slash after 'ark:'.

    Accepts both 'ark:/NAAN/...' (legacy) and 'ark:NAAN/...' (standard/N2T)
    and returns the canonical 'ark:NAAN/...' form.
    """
    if ark.startswith("ark:/"):
        return "ark:" + ark[5:]
    return ark


# Format variants and their media types.
FORMAT_VARIANTS = {
    "pdf": "application/pdf",
    "md": "text/markdown",
    "jsonld": "application/json",
    "bib": "text/plain",
    "html": "text/html",
}


def parse_ark_variant(ark: str) -> tuple[str, int | None, str | None]:
    """Parse an ARK into its base form, optional version, and optional format.

    GenRxiv base names (e.g. 'genrxiv-2026-00001') contain no dots, so the first
    dot in the ARK marks the start of the variant portion. Variants follow
    the ARK convention of dot-separated components:

        'ark:99999/genrxiv-2026-00001'         -> (base, None,  None)
        'ark:99999/genrxiv-2026-00001.v3'      -> (base, 3,     None)
        'ark:99999/genrxiv-2026-00001.pdf'     -> (base, None,  'pdf')
        'ark:99999/genrxiv-2026-00001.v3.pdf'  -> (base, 3,     'pdf')

    Also handles legacy slash-separated suffixes for backwards compatibility:

        'ark:99999/genrxiv-2026-00001/1'       -> (base, 1,     None)
        'ark:99999/genrxiv-2026-00001/pdf'     -> (base, None,  'pdf')
        'ark:99999/genrxiv-2026-00001/1/pdf'   -> (base, 1,     'pdf')
    """
    ark = normalize_ark(ark)
    version: int | None = None
    fmt: str | None = None

    # Handle legacy slash-separated version suffix: /N
    parts = ark.rsplit("/", 1)
    if len(parts) == 2 and parts[1].isdigit():
        ark = parts[0]
        version = int(parts[1])
        # Check for a trailing format after the version: /N/pdf
        parts2 = ark.rsplit("/", 1)
        if len(parts2) == 2 and parts2[1] in FORMAT_VARIANTS:
            ark = parts2[0]
            fmt = parts2[1]
        return ark, version, fmt

    # Handle legacy slash-separated format suffix: /pdf
    parts = ark.rsplit("/", 1)
    if len(parts) == 2 and parts[1] in FORMAT_VARIANTS:
        ark = parts[0]
        fmt = parts[1]
        return ark, version, fmt

    # Handle dot-separated variants: .vN, .pdf, .vN.pdf
    if "." not in ark:
        return ark, version, fmt

    base, variant_str = ark.split(".", 1)
    for part in variant_str.split("."):
        if part.startswith("v") and part[1:].isdigit():
            version = int(part[1:])
        elif part in FORMAT_VARIANTS:
            fmt = part

    return base, version, fmt


def render_html(markdown: str) -> str:
    """Call conversion service to render Markdown → HTML.

    The conversion service parses YAML front matter (title, authors,
    abstract) from the Markdown and renders it as a header block.
    """
    with httpx.Client(timeout=120) as client:
        r = client.post(
            f"{config.convert_service_url}/render/html",
            files={"file": ("input.md", markdown.encode("utf-8"), "text/markdown")},
        )
        r.raise_for_status()
        return r.text


def render_pdf(markdown: str) -> bytes:
    """Call conversion service to render Markdown → PDF.

    The conversion service parses YAML front matter (title, authors,
    abstract) from the Markdown and renders it as a header block.
    """
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


def safe_resolve_file(relative_path: str) -> Path | None:
    """Safely resolve a file path under the files directory.
    Prevents path traversal (../../etc/passwd)."""
    files_dir = Path(config.files_dir).resolve()
    try:
        target = (files_dir / relative_path).resolve()
    except (ValueError, RuntimeError):
        return None
    # Ensure the resolved path is under files_dir
    if not str(target).startswith(str(files_dir)):
        return None
    if not target.exists() or not target.is_file():
        return None
    return target


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
            """SELECT a.id, a.orcid, a.name, a.affiliation, a.orcid_works_count
               FROM authors a
               JOIN article_authors aa ON a.id = aa.author_id
               WHERE aa.article_id = %s
               ORDER BY aa."order\"""",
            (article_id,),
        ).fetchall()
    return rows


def get_article_by_id_for_author(article_id: int, author_id: int) -> dict | None:
    """Fetch an article by id, but only if the given author submitted it.

    Unlike ``get_article_by_ark`` this does not filter on status, so it returns
    pending/rejected articles too — used for the author's own preview and
    delete flows on the My Submissions dashboard.
    """
    with get_conn().connection() as conn:
        row = conn.execute(
            """SELECT a.*, array_agg(aa.author_id ORDER BY aa."order") AS author_ids
               FROM articles a
               LEFT JOIN article_authors aa ON a.id = aa.article_id
               WHERE a.id = %s AND a.submitted_by = %s
               GROUP BY a.id""",
            (article_id, author_id),
        ).fetchone()
    return row


# Statuses an author is allowed to delete their own submission in.
# Published articles carry a persistent ARK and may be cited externally, so
# they cannot be removed by the author (a withdrawal/tombstone flow would be
# used instead, which is out of scope here).
DELETABLE_STATUSES = ("pending", "rejected")


def delete_article(article_id: int, author_id: int) -> dict:
    """Delete an author's own submission.

    Only allowed when the article was submitted by ``author_id`` and its status
    is one of ``DELETABLE_STATUSES`` (pending or rejected). Removes the article
    row (cascading to article_authors and downloads) and any rendered files on
    disk. Returns a descriptor of what was removed.
    """
    with get_conn().connection() as conn:
        row = conn.execute(
            "SELECT id, title, status, submitted_by, html_path, pdf_path FROM articles WHERE id = %s",
            (article_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Article not found")
        if row["submitted_by"] != author_id:
            # Don't leak existence to non-owners — return 404 rather than 403.
            raise HTTPException(404, "Article not found")
        if row["status"] not in DELETABLE_STATUSES:
            raise HTTPException(
                400,
                f"Only {'/'.join(DELETABLE_STATUSES)} submissions can be deleted "
                f"(this one is {row['status']})",
            )

        # Remove rendered artefacts (html/pdf) from disk if present.
        for rel in (row.get("html_path"), row.get("pdf_path")):
            if rel:
                target = safe_resolve_file(rel)
                if target and target.exists():
                    try:
                        target.unlink()
                    except OSError:
                        pass
        # Best-effort: remove the per-article directory if now empty.
        article_dir = Path(config.files_dir) / str(article_id)
        if article_dir.is_dir():
            try:
                article_dir.rmdir()
            except OSError:
                pass

        conn.execute("DELETE FROM articles WHERE id = %s", (article_id,))
        conn.commit()

    return {"id": article_id, "title": row["title"], "status": row["status"]}


def get_article_by_ark_including_withdrawn(ark: str) -> dict | None:
    """Like ``get_article_by_ark`` but also returns withdrawn articles.

    Used by the public article HTML route so a withdrawn article's ARK still
    resolves (to a tombstone page) instead of 404ing. Download endpoints
    (pdf/markdown/jsonld/bibtex) keep using ``get_article_by_ark`` so they
    do not serve withdrawn content.
    """
    with get_conn().connection() as conn:
        row = conn.execute(
            """SELECT a.*, array_agg(aa.author_id ORDER BY aa."order") AS author_ids
               FROM articles a
               LEFT JOIN article_authors aa ON a.id = aa.article_id
               WHERE a.ark = %s AND a.status IN ('published', 'withdrawn')
               GROUP BY a.id""",
            (ark,),
        ).fetchone()
    return row


def get_article_version(base_ark: str, version: int, include_withdrawn: bool = False) -> dict | None:
    """Get a specific version of an article by its base ARK and version number.

    The ARK is stored only on the current (published) version; earlier versions
    have ``ark = NULL``. This function finds the current version by base ARK,
    then locates the requested version in the version chain.
    """
    status_filter = ("published", "withdrawn") if include_withdrawn else ("published",)
    with get_conn().connection() as conn:
        # Find the current version (which holds the ARK) to get the root id
        current = conn.execute(
            "SELECT id, supersedes_id FROM articles WHERE ark = %s",
            (base_ark,),
        ).fetchone()
        if not current:
            return None
        root_id = current["supersedes_id"] or current["id"]
        placeholders = ",".join(["%s"] * len(status_filter))
        row = conn.execute(
            f"""SELECT a.*, array_agg(aa.author_id ORDER BY aa."order") AS author_ids
               FROM articles a
               LEFT JOIN article_authors aa ON a.id = aa.article_id
               WHERE (a.id = %s OR a.supersedes_id = %s) AND a.version = %s
                 AND a.status IN ({placeholders})
               GROUP BY a.id""",
            (root_id, root_id, version, *status_filter),
        ).fetchone()
    return row


def _build_retraction_markdown(original: dict, authors: list[dict], reason: str) -> str:
    """Build the Markdown body for a one-click author retraction notice.

    The front matter is merged in by the caller via ``_merge_front_matter``;
    this returns just the body (the retraction notice itself).
    """
    from datetime import datetime, timezone
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    original_title = original["title"]
    ark = original.get("ark") or ""
    reason_escaped = (reason or "").strip() or "No reason provided."
    ark_line = f" The original article was available at `{ark}`." if ark else ""
    body = f"""# Retraction Notice

This article, "{original_title}", has been **retracted by the author** on {date_str}.{ark_line}

## Reason

{reason_escaped}

## Note

This retraction notice is the current version of record. The original
version is preserved in the version history. Readers who encounter the
original content should treat it as retracted.
"""
    return body


def create_retraction(article_id: int, reason: str, author: dict) -> dict:
    """Create a retraction version of an author's own published article.

    The retraction is a new article row with ``supersedes_id`` set to the
    original, ``is_retraction = True``, and ``status = 'pending'`` so it goes
    through the normal moderation pipeline. On approval the ARK transfers to
    the retraction version and the original is marked superseded (existing
    ``moderate_article`` logic handles this).

    Returns a descriptor of the new pending retraction submission.
    """
    reason = (reason or "").strip()[:2000]
    with get_conn().connection() as conn:
        # Load the original article and verify the caller is one of its authors.
        original = conn.execute(
            "SELECT id, ark, title, abstract, subjects, version, status, source_markdown "
            "FROM articles WHERE id = %s",
            (article_id,),
        ).fetchone()
        if not original:
            raise HTTPException(404, "Article not found")
        is_author = conn.execute(
            "SELECT 1 FROM article_authors WHERE article_id = %s AND author_id = %s",
            (article_id, author["id"]),
        ).fetchone()
        if not is_author:
            raise HTTPException(403, "You can only retract your own articles")
        if original["status"] not in ("published", "superseded"):
            raise HTTPException(
                400,
                f"Only published articles can be retracted (this one is {original['status']})",
            )

        # Find the latest version in the chain (the root may be the original
        # or an earlier version; supersedes_id always points at the root).
        root_id = article_id
        latest = conn.execute(
            "SELECT version FROM articles WHERE id = %s OR supersedes_id = %s "
            "ORDER BY version DESC LIMIT 1",
            (root_id, root_id),
        ).fetchone()
        version = (latest["version"] + 1) if latest else original["version"] + 1

        # Authors of the original (preserved on the retraction notice).
        author_rows = conn.execute(
            """SELECT a.orcid, a.name, a.affiliation
               FROM authors a
               JOIN article_authors aa ON a.id = aa.author_id
               WHERE aa.article_id = %s
               ORDER BY aa."order\"""",
            (article_id,),
        ).fetchall()
        author_list = [
            {"orcid": r["orcid"], "name": r["name"], "affiliation": r.get("affiliation")}
            for r in author_rows
        ]
        if not author_list:
            # Fallback: at least the submitter
            author_list = [{"orcid": author["orcid"], "name": author["name"]}]

        retraction_title = f"Retraction: {original['title']}"
        retraction_abstract = (
            f'This article has been retracted by the author. Reason: {reason or "No reason provided."}'
        )
        subjects = list(original["subjects"] or [])

        body = _build_retraction_markdown(original, author_list, reason)
        md_text = _merge_front_matter(
            body, retraction_title, author_list, retraction_abstract, subjects
        )

        row = conn.execute(
            """INSERT INTO articles
                   (title, abstract, license, license_url, subjects,
                    source_markdown, submitted_by, status, version,
                    supersedes_id, is_retraction)
               VALUES (%s, %s, 'CC0',
                       'https://creativecommons.org/publicdomain/zero/1.0/',
                       %s, %s, %s, 'pending', %s, %s, TRUE)
               RETURNING id, submitted_at""",
            (
                retraction_title,
                retraction_abstract,
                subjects,
                md_text,
                author["id"],
                version,
                root_id,
            ),
        ).fetchone()
        new_id = row["id"]

        # Link the same authors to the retraction version.
        for i, a in enumerate(author_list):
            existing = conn.execute(
                "SELECT id FROM authors WHERE orcid = %s", (a["orcid"],)
            ).fetchone()
            if existing:
                conn.execute(
                    "INSERT INTO article_authors (article_id, author_id, \"order\") "
                    "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (new_id, existing["id"], i),
                )
        conn.commit()

    return {
        "id": new_id,
        "retraction_of": article_id,
        "status": "pending",
        "version": version,
        "title": retraction_title,
    }


def withdraw_article(article_id: int, reason: str, admin: dict) -> dict:
    """Withdraw a published article (admin only).

    Sets status to 'withdrawn', records the reason and timestamp. The ARK is
    preserved so it resolves to a tombstone page; the content is no longer
    served. Used for DMCA/DSA takedowns and research-integrity findings.
    """
    reason = (reason or "").strip()[:2000]
    if not reason:
        raise HTTPException(400, "A withdrawal reason is required (for the audit trail)")
    with get_conn().connection() as conn:
        row = conn.execute(
            "SELECT id, title, ark, status FROM articles WHERE id = %s",
            (article_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Article not found")
        if row["status"] != "published":
            raise HTTPException(
                400,
                f"Only published articles can be withdrawn (this one is {row['status']})",
            )
        conn.execute(
            """UPDATE articles
               SET status = 'withdrawn',
                   withdrawn_at = now(),
                   withdrawal_reason = %s,
                   moderated_by = %s,
                   moderated_at = now()
               WHERE id = %s""",
            (reason, admin["id"], article_id),
        )
        conn.commit()
    return {
        "id": article_id,
        "title": row["title"],
        "ark": row["ark"],
        "status": "withdrawn",
        "reason": reason,
    }


def build_jsonld(article: dict, authors: list[dict], display_ark: str | None = None, version: int | None = None) -> dict:
    """Build Schema.org ScholarArticle JSON-LD."""
    base = config.base_url
    ark = display_ark or article["ark"]
    jsonld = {
        "@context": "https://schema.org",
        "@type": "ScholarlyArticle",
        "@id": ark,
        "identifier": ark,
        "url": f"{base}/article/{ark}",
        "headline": article["title"],
    }
    if version is not None:
        jsonld["version"] = version
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
    if article.get("subjects"):
        jsonld["keywords"] = ", ".join(article["subjects"])
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


@router.post("/api/validate")
@limiter.limit("20 per minute")
async def validate_submission(
    request: Request,
    markdown: UploadFile = File(...),
    title: str = Form(""),
    authors: str = Form(""),
    abstract: str = Form(""),
    license: str = Form("CC0"),
    license_url: str = Form("https://creativecommons.org/publicdomain/zero/1.0/"),
    subjects: str = Form(""),
):
    """Validate a submission without creating it. Returns errors, hints, and a preview.

    No authentication required — agents can lint documents at any time.
    The submitter-in-author-list check is not performed here (it
    requires a session cookie from ORCID login, which agents never
    have). That check runs only on /api/submit.
    """
    errors = []
    hints = []

    # Read and validate file
    content = await markdown.read()
    if len(content) > MAX_MARKDOWN_SIZE:
        errors.append(f"File too large (max {MAX_MARKDOWN_SIZE // 1024 // 1024}MB)")
    if not content:
        errors.append("Markdown file is empty")
    else:
        ext = Path(markdown.filename or "").suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            errors.append(f"File must be .md or .markdown, got: {ext or 'no extension'}")

    # Validate title
    try:
        title = validate_title(title) if title else ""
    except HTTPException as e:
        errors.append(e.detail)
    if not title:
        errors.append("Title is required")

    # Validate abstract
    abstract = abstract.strip()
    if not abstract:
        errors.append("Abstract is required")
    elif len(abstract) > MAX_ABSTRACT_LENGTH:
        errors.append(f"Abstract too long (max {MAX_ABSTRACT_LENGTH} chars)")

    # Validate authors
    author_list = []
    try:
        author_list = json.loads(authors)
        if not isinstance(author_list, list) or not author_list:
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        errors.append("Authors must be a JSON array of {orcid, name} objects")
    else:
        if len(author_list) > MAX_AUTHORS:
            errors.append(f"Too many authors (max {MAX_AUTHORS})")
        for a in author_list:
            if not isinstance(a, dict) or "orcid" not in a or "name" not in a:
                errors.append("Each author must have orcid and name")
                break
            try:
                a["orcid"] = validate_orcid(a["orcid"])
            except HTTPException:
                errors.append(f"Invalid ORCID format: {a.get('orcid', '?')}")
                break
            a["name"] = a["name"].strip()[:200]
            if not a["name"]:
                errors.append("Author name cannot be empty")
                break

        # Note: submitter-in-author-list check is not performed here.
        # It requires a session cookie from ORCID login, which agents
        # never have. That check runs only on /api/submit.

    # Validate license
    try:
        validate_license(license, license_url)
    except HTTPException as e:
        errors.append(e.detail)

    # Validate subjects
    subj_list = []
    try:
        subj_list = validate_subjects(parse_subjects_string(subjects))
    except HTTPException as e:
        errors.append(e.detail)
    if len(subj_list) != 3:
        errors.append(f"Exactly 3 subject classifications are required (got {len(subj_list)})")

    # Hints: check Markdown content for common issues
    parsed_metadata = None
    if content:
        md_text = content.decode("utf-8", errors="replace")
        # Extract front matter for the response so the web form can
        # auto-fill fields using the same parser as the API (PyYAML)
        parsed_metadata = _extract_front_matter(md_text)
        if not md_text.strip():
            hints.append("Markdown content is empty")
        if "```bibtex" in md_text:
            # Check for unclosed BibTeX block
            bibtex_count = md_text.count("```bibtex")
            closing_after = md_text.count("```", md_text.index("```bibtex") + len("```bibtex"))
            if closing_after < bibtex_count:
                hints.append("BibTeX block may be unclosed — check that each ```bibtex block has a closing ```")
        if md_text.startswith("---"):
            # Has front matter — check it closes
            if "\n---\n" not in md_text[3:]:
                hints.append("YAML front matter appears to be unclosed — add a closing --- line")

        # Check for content issues: duplicates, citations, empty sections,
        # heading hierarchy, ORCID format, minimum length
        content_errors, content_hints = _check_content_issues(md_text, title, abstract)
        errors.extend(content_errors)
        hints.extend(content_hints)

        # Check for duplicate submissions in the database (hint only)
        if title:
            try:
                duplicates = check_duplicate_submission(title, md_text, author_id=0)
                if duplicates:
                    content_dups = [d for d in duplicates if d["match_type"] == "content"]
                    if content_dups:
                        hints.append(
                            f"Note: This paper appears to be a duplicate of an existing "
                            f"submission (id={content_dups[0]['id']}, "
                            f"status={content_dups[0]['status']}). "
                            f"Submitting it will be rejected unless it is a new version."
                        )
                    else:
                        hints.append(
                            f"Note: A submission with the same title already exists "
                            f"(id={duplicates[0]['id']}, "
                            f"status={duplicates[0]['status']}). "
                            f"If this is a different paper, consider using a more specific title."
                        )
            except Exception:
                pass  # Don't let duplicate check failure block validation

        if "$" in md_text:
            dollar_count = md_text.count("$")
            if dollar_count % 2 != 0:
                hints.append("Odd number of $ signs — some math expressions may be unclosed")
        if "<html" in md_text.lower() or "<body" in md_text.lower():
            hints.append("Raw HTML tags detected — GenRxiv renders Markdown only, HTML tags will be stripped")

    # Build preview if no blocking errors
    preview_html = None
    if not errors and content:
        try:
            # Merge form metadata into front matter before rendering
            merged_md = _merge_front_matter(md_text, title, author_list, abstract, subj_list)
            preview_html = render_html(merged_md)
        except Exception as e:
            hints.append(f"Preview rendering failed: {str(e)}")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "hints": hints,
        "preview": preview_html,
        "parsed_metadata": parsed_metadata,
    }


@router.post("/api/submit", include_in_schema=False)
@limiter.limit("5 per minute")
async def submit(
    request: Request,
    markdown: UploadFile = File(...),
    title: str = Form(...),
    authors: str = Form(...),
    abstract: str = Form(""),
    license: str = Form("CC0"),
    license_url: str = Form("https://creativecommons.org/publicdomain/zero/1.0/"),
    subjects: str = Form(""),
    reviewed_agree: str = Form(""),
    cc0_agree: str = Form(""),
    coc_agree: str = Form(""),
    supersedes_id: int | None = Form(None),
    _author: dict = Depends(require_author),
):
    """Submit a Markdown paper."""
    # Check account status — suspended/banned authors cannot submit
    status = _author.get("account_status", "active")
    if status in ("suspended", "banned"):
        action = "suspended" if status == "suspended" else "banned"
        raise HTTPException(
            403,
            f"Your account has been {action}. You cannot submit new papers. "
            "Contact the GenRxiv administrators if you believe this is an error.",
        )

    # GitHub-only users (no ORCID) cannot submit — submission requires an ORCID
    # to be listed in the paper's author list
    if not _author.get("orcid"):
        raise HTTPException(
            403,
            "Submission requires an ORCID iD. Please sign in with ORCID to submit a paper. "
            "GitHub login is for moderation only.",
        )

    # Validate agreements
    if not reviewed_agree:
        raise HTTPException(400, "You must confirm that you have reviewed the work for accuracy and integrity.")
    if not cc0_agree:
        raise HTTPException(400, "You must agree to the CC0 public domain dedication.")
    if not coc_agree:
        raise HTTPException(400, "You must agree to the Code of Conduct.")

    # Validate file
    content = await markdown.read()
    if len(content) > MAX_MARKDOWN_SIZE:
        raise HTTPException(413, f"File too large ({MAX_MARKDOWN_SIZE // (1024*1024)}MB max)")
    if not content:
        raise HTTPException(400, "Empty file")
    ext = Path(markdown.filename or "input.md").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"GenRxiv accepts Markdown only ({', '.join(ALLOWED_EXTENSIONS)})")

    md_text = content.decode("utf-8", errors="replace")

    # Validate fields
    title = validate_title(title)
    abstract = abstract.strip()
    if not abstract:
        raise HTTPException(400, "Abstract is required")
    if len(abstract) > MAX_ABSTRACT_LENGTH:
        raise HTTPException(400, f"Abstract too long (max {MAX_ABSTRACT_LENGTH} chars)")
    license, license_url = validate_license(license, license_url)

    # Parse authors JSON
    try:
        author_list = json.loads(authors)
        if not isinstance(author_list, list) or not author_list:
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(400, "authors must be a JSON array of {orcid, name} objects")

    if len(author_list) > MAX_AUTHORS:
        raise HTTPException(400, f"Too many authors (max {MAX_AUTHORS})")

    # Validate each author
    for a in author_list:
        if not isinstance(a, dict) or "orcid" not in a or "name" not in a:
            raise HTTPException(400, "Each author must have orcid and name")
        a["orcid"] = validate_orcid(a["orcid"])
        a["name"] = a["name"].strip()[:200]
        if not a["name"]:
            raise HTTPException(400, "Author name cannot be empty")
        if a.get("affiliation"):
            a["affiliation"] = a["affiliation"].strip()[:300]

    # The submitter must be one of the authors
    submitter_orcids = [a["orcid"] for a in author_list]
    if _author["orcid"] not in submitter_orcids:
        raise HTTPException(
            400,
            "The submitting author must be listed as one of the authors. "
            "You cannot submit on behalf of others without being an author yourself."
        )

    # Parse and validate subjects (exactly 3 OECD FOS classifications required)
    subj_list = validate_subjects(parse_subjects_string(subjects))
    if len(subj_list) != 3:
        raise HTTPException(400, "Exactly 3 subject classifications are required")

    # Check for duplicate title/abstract/references in front matter and body
    dup_errors = _check_duplicate_content(md_text, title, abstract)
    if dup_errors:
        raise HTTPException(400, "; ".join(dup_errors))

    # Check for duplicate submissions already in the database.
    # An exact content match is blocked; a title-only match is allowed
    # but the user is informed (they may be submitting a related paper).
    duplicates = check_duplicate_submission(
        title, md_text, _author["id"], exclude_id=supersedes_id,
    )
    content_dups = [d for d in duplicates if d["match_type"] == "content"]
    if content_dups and not supersedes_id:
        dup_info = "; ".join(
            f'"{d["title"]}" (id={d["id"]}, status={d["status"]})'
            for d in content_dups
        )
        raise HTTPException(
            409,
            f"This paper appears to be a duplicate of an existing submission: {dup_info}. "
            f"If you meant to submit a new version, use the 'Submit new version' button "
            f"on your My Submissions page. If the existing submission is pending or rejected, "
            f"you can delete it and resubmit."
        )

    # Merge form metadata into the Markdown as YAML front matter.
    # The stored file is the complete document — front matter + body.
    md_text = _merge_front_matter(md_text, title, author_list, abstract, subj_list)

    # Insert article
    with get_conn().connection() as conn:
        # If this is a new version of an existing article, compute the version number
        version = 1
        if supersedes_id:
            # Verify the original article exists and the submitter is an author of it
            original = conn.execute(
                """SELECT a.id, a.version, a.status
                   FROM articles a
                   JOIN article_authors aa ON a.id = aa.article_id
                   WHERE a.id = %s AND aa.author_id = %s""",
                (supersedes_id, _author["id"]),
            ).fetchone()
            if not original:
                raise HTTPException(403, "You can only submit new versions of your own articles")
            # Find the latest version in the chain
            latest = conn.execute(
                "SELECT version FROM articles WHERE id = %s OR supersedes_id = %s ORDER BY version DESC LIMIT 1",
                (supersedes_id, supersedes_id),
            ).fetchone()
            if latest:
                version = latest["version"] + 1

        row = conn.execute(
            """INSERT INTO articles (title, abstract, license, license_url, subjects, source_markdown, submitted_by, status, version, supersedes_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', %s, %s)
               RETURNING id, ark, status, submitted_at""",
            (title, abstract or None, license, license_url, subj_list, md_text, _author["id"], version, supersedes_id),
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

    # Refresh cached ORCID works count for all authors on this submission
    try:
        from orcid_client import cache_orcid_record
        from db import get_conn as _get_conn
        with _get_conn().connection() as conn:
            author_rows = conn.execute(
                """SELECT a.id, a.orcid FROM authors a
                   JOIN article_authors aa ON a.id = aa.author_id
                   WHERE aa.article_id = %s""",
                (article_id,),
            ).fetchall()
        for ar in author_rows:
            cache_orcid_record(ar["id"], ar["orcid"])
    except Exception:
        pass  # Don't let ORCID API failure block submission

    # ── Automated screening ──────────────────────────────────────────────
    # Run the screening model on the submission. If it comes back clean,
    # auto-publish immediately. If flagged (or if screening fails), the
    # submission stays pending for human review. The model never auto-rejects.
    screening_verdict = "screening_disabled"
    submitted_at_iso = row["submitted_at"].isoformat()
    try:
        from screening import screen_submission, save_screening_report
        result = screen_submission(title, abstract, md_text)
        screening_verdict = result["verdict"]
        save_screening_report(article_id, result)
    except Exception as e:
        logger.error("Screening failed for article %s: %s", article_id, e)
        screening_verdict = "screening_error"

    if screening_verdict == "auto_approve":
        try:
            # Auto-publish: replicate the admin approve flow
            with get_conn().connection() as conn:
                approve_row = conn.execute(
                    "SELECT id, title, abstract, status, source_markdown, version, submitted_at FROM articles WHERE id = %s",
                    (article_id,),
                ).fetchone()
                ark, version = _approve_article(
                    conn, article_id, approve_row,
                    moderator_id=_author["id"],
                    note="Auto-approved by automated screening",
                )
                conn.commit()
            notify_approved(article_id, ark, approve_row["title"], "Auto-approved by automated screening")
            return {
                "id": article_id,
                "ark": ark,
                "status": "published",
                "version": version,
                "submitted_at": approve_row["submitted_at"].isoformat(),
                "screening": screening_verdict,
            }
        except Exception as e:
            logger.error("Auto-approval failed for article %s (screening said auto_approve): %s", article_id, e)
            # Fall through to pending — the submission stays for human review

    return {
        "id": article_id,
        "ark": assign_ark(article_id),
        "status": "pending",
        "version": version,
        "submitted_at": submitted_at_iso,
        "screening": screening_verdict,
    }


# ─── Author's own submissions ──────────────────────────────────────────────

@router.get("/api/submissions", include_in_schema=False)
def my_submissions(_author: dict = Depends(require_author)):
    """List the current author's submissions."""
    with get_conn().connection() as conn:
        rows = conn.execute(
            """SELECT id, ark, title, status, submitted_at, published_at
               FROM articles WHERE submitted_by = %s ORDER BY submitted_at DESC""",
            (_author["id"],),
        ).fetchall()
    return {"items": rows}


@router.delete("/api/submissions/{article_id}", include_in_schema=False)
def delete_submission(article_id: int, _author: dict = Depends(require_author)):
    """Delete the author's own pending or rejected submission.

    Published articles cannot be deleted (they carry a persistent ARK
    and may be cited externally). Only the submitter can delete their
    own submission.
    """
    result = delete_article(article_id, _author["id"])
    return result


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
                """SELECT id, ark, title, abstract, subjects, published_at, license
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
                """SELECT id, ark, title, abstract, subjects, published_at, license
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
                "subjects": r["subjects"],
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
        "license": row["license"],
        "license_url": row["license_url"],
        "subjects": row["subjects"],
        "version": row["version"],
        "authors": authors,
        "published_at": row["published_at"].isoformat() if row["published_at"] else None,
    }


@router.get("/api/articles/{article_id}/versions")
def article_versions(article_id: int):
    """Get version history for an article."""
    with get_conn().connection() as conn:
        # Find the root article (the one with no supersedes_id in the chain)
        row = conn.execute(
            "SELECT id, ark, supersedes_id FROM articles WHERE id = %s", (article_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Article not found")

        # Find the root of the version chain
        root_id = row["supersedes_id"] or article_id
        ark = row["ark"]

        # Get all versions in the chain
        versions = conn.execute(
            """SELECT id, version, title, status, published_at, submitted_at,
                      supersedes_id
               FROM articles
               WHERE id = %s OR supersedes_id = %s
               ORDER BY version DESC""",
            (root_id, root_id),
        ).fetchall()

    return {
        "ark": ark,
        "versions": [
            {
                "id": v["id"],
                "version": v["version"],
                "title": v["title"],
                "status": v["status"],
                "published_at": v["published_at"].isoformat() if v["published_at"] else None,
                "submitted_at": v["submitted_at"].isoformat() if v["submitted_at"] else None,
                "is_current": v["status"] == "published",
            }
            for v in versions
        ],
    }


# ─── Article viewing (HTML/PDF/Markdown/JSON-LD) ───────────────────────────
# NOTE: Specific routes (with suffixes) must be registered BEFORE the
# catch-all {ark:path} route, otherwise FastAPI matches the catch-all first.

def _lookup_article(base_ark: str, version: int | None, include_withdrawn: bool = False) -> dict | None:
    """Look up an article by base ARK, optionally a specific version."""
    if version is not None:
        return get_article_version(base_ark, version, include_withdrawn=include_withdrawn)
    if include_withdrawn:
        return get_article_by_ark_including_withdrawn(base_ark)
    return get_article_by_ark(base_ark)


def _withdrawn_gone(base_ark: str, version: int | None):
    """Raise 410 Gone if the article exists but is withdrawn."""
    article = _lookup_article(base_ark, version, include_withdrawn=True)
    if article and article["status"] == "withdrawn":
        raise HTTPException(410, "This article has been withdrawn and is no longer available")


def _serve_pdf(article: dict, base_ark: str, version: int | None, request: Request):
    """Serve an article as PDF."""
    track_download(article["id"], "pdf", request)
    display = f"{base_ark}.v{version}" if version is not None else base_ark
    if article["pdf_path"]:
        filepath = safe_resolve_file(article["pdf_path"])
        if filepath:
            return FileResponse(filepath, media_type="application/pdf", filename=f"{display.replace('/', '_')}.pdf")
    pdf_bytes = render_pdf(article["source_markdown"])
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{display.replace("/", "_")}.pdf"'},
    )


def _serve_markdown(article: dict, base_ark: str, version: int | None, request: Request):
    """Serve an article's Markdown source."""
    track_download(article["id"], "markdown", request)
    display = f"{base_ark}.v{version}" if version is not None else base_ark
    return Response(
        content=article["source_markdown"].encode("utf-8"),
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{display.replace("/", "_")}.md"'},
    )


def _serve_jsonld(article: dict, base_ark: str, version: int | None):
    """Serve an article as JSON-LD."""
    authors = get_article_authors(article["id"])
    display_ark = f"{base_ark}.v{version}" if version is not None else base_ark
    return build_jsonld(article, authors, display_ark=display_ark, version=version)


def _serve_bibtex(article: dict, base_ark: str, version: int | None):
    """Serve an article's BibTeX references."""
    bibtex = extract_bibtex(article["source_markdown"])
    if not bibtex:
        raise HTTPException(404, "No BibTeX references found for this article")
    display = f"{base_ark}.v{version}" if version is not None else base_ark
    return Response(content=bibtex, media_type="text/plain",
                    headers={"Content-Disposition": f"inline; filename={display}.bib"})


# ── Legacy slash-separated routes (backwards compatible) ──────────────────
# These keep old URLs like /article/ark:NAAN/genrxiv-2026-00001/pdf working.
# New URLs use dot-variants: /article/ark:NAAN/genrxiv-2026-00001.pdf

@router.get("/article/{ark:path}/pdf")
def download_pdf(ark: str, request: Request):
    """Download article as PDF (legacy slash route)."""
    base_ark, version, fmt = parse_ark_variant(unquote(ark))
    _withdrawn_gone(base_ark, version)
    article = _lookup_article(base_ark, version)
    if not article:
        raise HTTPException(404, "Article not found")
    return _serve_pdf(article, base_ark, version, request)


@router.get("/article/{ark:path}/markdown")
def download_markdown(ark: str, request: Request):
    """Download original Markdown source (legacy slash route)."""
    base_ark, version, fmt = parse_ark_variant(unquote(ark))
    _withdrawn_gone(base_ark, version)
    article = _lookup_article(base_ark, version)
    if not article:
        raise HTTPException(404, "Article not found")
    return _serve_markdown(article, base_ark, version, request)


@router.get("/article/{ark:path}/jsonld")
def article_jsonld(ark: str):
    """Get article as JSON-LD (legacy slash route)."""
    base_ark, version, fmt = parse_ark_variant(unquote(ark))
    _withdrawn_gone(base_ark, version)
    article = _lookup_article(base_ark, version)
    if not article:
        raise HTTPException(404, "Article not found")
    return _serve_jsonld(article, base_ark, version)


@router.get("/article/{ark:path}/bibtex")
def article_bibtex(ark: str):
    """Get article's BibTeX references (legacy slash route)."""
    base_ark, version, fmt = parse_ark_variant(unquote(ark))
    _withdrawn_gone(base_ark, version)
    article = _lookup_article(base_ark, version)
    if not article:
        raise HTTPException(404, "Article not found")
    return _serve_bibtex(article, base_ark, version)


@router.get("/api/articles/{ark:path}/references")
def article_references(ark: str):
    """Get article's references as structured JSON.

    Returns a list of parsed BibTeX entries with type, key, author,
    title, year, and other fields. Useful for agents and harvesting.
    """
    base_ark, version, fmt = parse_ark_variant(unquote(ark))
    _withdrawn_gone(base_ark, version)
    article = _lookup_article(base_ark, version)
    if not article:
        raise HTTPException(404, "Article not found")
    bibtex = extract_bibtex(article["source_markdown"])
    if not bibtex:
        return {"references": []}
    entries = parse_bibtex_entries(bibtex)
    return {"references": entries}


@router.get("/article/{ark:path}/versions", response_class=HTMLResponse)
def article_versions_page(ark: str, request: Request):
    """Version history page for an article."""
    from urllib.parse import unquote as _unquote
    from web import _page, _format_date
    base_ark, _, _ = parse_ark_variant(_unquote(ark))
    article = get_article_by_ark(base_ark)
    if not article:
        raise HTTPException(404, "Article not found")
    with get_conn().connection() as conn:
        root_id = article["supersedes_id"] or article["id"]
        versions = conn.execute(
            """SELECT id, version, title, status, ark, is_retraction, published_at, submitted_at
               FROM articles
               WHERE id = %s OR supersedes_id = %s
               ORDER BY version DESC""",
            (root_id, root_id),
        ).fetchall()
    from auth import get_current_author
    author = get_current_author(request)
    version_rows = []
    for v in versions:
        is_current = v["status"] == "published"
        status_class = f"status-{v['status']}"
        published = _format_date(v.get("published_at"))
        submitted = _format_date(v.get("submitted_at"))
        link = f'<a href="/article/{v["ark"]}">v{v["version"]}</a>' if v.get("ark") else f"v{v['version']}"
        retraction_badge = ' <span class="status-badge" style="background:#fdf0f0;color:#c0392b;border:1px solid #c0392b">retraction</span>' if v.get("is_retraction") else ""
        version_rows.append(f"""<tr>
<td><strong>{link}</strong>{' <span class="status-badge status-published">current</span>' if is_current else ''}{retraction_badge}</td>
<td>{v['title']}</td>
<td><span class="status-badge {status_class}">{v['status']}</span></td>
<td>{submitted}</td>
<td>{published}</td>
</tr>""")
    body = f"""
    <h1>Version History</h1>
    <div class="card" style="margin-bottom:1.5rem">
        <h2>{article['title']}</h2>
        <div class="meta">ARK: {base_ark} &middot; Current version: v{article['version']}</div>
    </div>
    <table style="width:100%;border-collapse:collapse;font-size:0.9rem">
        <thead>
            <tr style="border-bottom:2px solid var(--border);text-align:left">
                <th style="padding:0.5rem">Version</th>
                <th style="padding:0.5rem">Title</th>
                <th style="padding:0.5rem">Status</th>
                <th style="padding:0.5rem">Submitted</th>
                <th style="padding:0.5rem">Published</th>
            </tr>
        </thead>
        <tbody>
            {''.join(version_rows)}
        </tbody>
    </table>
    <div style="margin-top:1.5rem"><a href="/article/{base_ark}">&larr; Back to article</a></div>
    """
    return _page("Version History", body, author)


@router.get("/article/{ark:path}")
def view_article(ark: str, request: Request):
    """View article — dispatches based on ARK variant (format/version).

    Supports dot-separated variants per the ARK standard:
        ark:NAAN/genrxiv-2026-00001         → current version, HTML
        ark:NAAN/genrxiv-2026-00001.v3      → version 3, HTML
        ark:NAAN/genrxiv-2026-00001.pdf     → current version, PDF
        ark:NAAN/genrxiv-2026-00001.v3.pdf  → version 3, PDF
        ark:NAAN/genrxiv-2026-00001.md      → current version, Markdown
        ark:NAAN/genrxiv-2026-00001.jsonld  → current version, JSON-LD
        ark:NAAN/genrxiv-2026-00001.bib     → current version, BibTeX

    Also handles legacy slash-separated suffixes for backwards compatibility.
    """
    base_ark, version, fmt = parse_ark_variant(unquote(ark))

    # Dispatch non-HTML formats to their handlers.
    if fmt == "pdf":
        _withdrawn_gone(base_ark, version)
        article = _lookup_article(base_ark, version)
        if not article:
            raise HTTPException(404, "Article not found")
        return _serve_pdf(article, base_ark, version, request)
    if fmt == "md":
        _withdrawn_gone(base_ark, version)
        article = _lookup_article(base_ark, version)
        if not article:
            raise HTTPException(404, "Article not found")
        return _serve_markdown(article, base_ark, version, request)
    if fmt == "jsonld":
        _withdrawn_gone(base_ark, version)
        article = _lookup_article(base_ark, version)
        if not article:
            raise HTTPException(404, "Article not found")
        return _serve_jsonld(article, base_ark, version)
    if fmt == "bib":
        _withdrawn_gone(base_ark, version)
        article = _lookup_article(base_ark, version)
        if not article:
            raise HTTPException(404, "Article not found")
        return _serve_bibtex(article, base_ark, version)

    # HTML (default) — use including-withdrawn lookup so a withdrawn article's
    # ARK still resolves to a tombstone page rather than 404ing.
    article = _lookup_article(base_ark, version, include_withdrawn=True)
    if not article:
        raise HTTPException(404, "Article not found")

    # Withdrawn articles: render a tombstone page instead of the content.
    if article["status"] == "withdrawn":
        from web import _page, _format_date
        from auth import get_current_author
        withdrawn_at = _format_date(article.get("withdrawn_at"))
        reason = article.get("withdrawal_reason") or ""
        display_ark = f"{base_ark}.v{version}" if version is not None else base_ark
        body = f"""
        <div class="card" style="border-left:4px solid #c0392b;background:#fdf0f0">
            <h1 style="color:#c0392b">Article withdrawn</h1>
            <p>This article (<strong>{article['title']}</strong>) has been
            withdrawn from GenRxiv and is no longer available.</p>
            <p style="margin-top:0.5rem">
                <strong>ARK:</strong> {display_ark}<br>
                <strong>Withdrawn:</strong> {withdrawn_at}
            </p>
            {f'<div style="margin-top:1rem;padding:0.8rem;background:#fff;border:1px solid #e0d6d6;border-radius:4px"><strong>Reason:</strong> {reason}</div>' if reason else ''}
            <p style="margin-top:1rem;font-size:0.85rem;color:#666">
                The identifier ({display_ark}) remains valid and resolves to this
                notice. The full text is no longer served. For questions about
                this withdrawal, contact the GenRxiv moderators.
            </p>
        </div>
        """
        author = get_current_author(request)
        return _page("Article withdrawn", body, author)

    track_download(article["id"], "html", request)

    # Version banner: shown when viewing a specific (non-current) version.
    version_banner = ""
    if version is not None:
        current_article = get_article_by_ark(base_ark)
        if current_article and current_article["id"] != article["id"]:
            version_banner = (
                '<div style="background:#fff8e1;border-left:4px solid #f57c00;'
                'padding:1rem 1.5rem;margin:0 0 1.5rem 0;font-size:1.05rem">'
                f'<strong>Version {version}.</strong> This is not the current version. '
                f'<a href="/article/{base_ark}">View current version (v{current_article["version"]})</a>'
                f' &middot; <a href="/article/{base_ark}/versions">Version history</a>'
                '</div>'
            )

    # Retraction notice: prepend a prominent banner to the rendered HTML.
    retraction_banner = ""
    if article.get("is_retraction"):
        retraction_banner = (
            '<div style="background:#fdf0f0;border-left:4px solid #c0392b;'
            'padding:1rem 1.5rem;margin:0 0 1.5rem 0;font-size:1.05rem">'
            '<strong style="color:#c0392b">This article has been retracted.</strong> '
            "This page is the retraction notice and is the current version of record. "
            'See the <a href="/article/{ark}/versions">version history</a> for the original.</div>'
        ).replace("{ark}", base_ark)

    if article["html_path"]:
        filepath = safe_resolve_file(article["html_path"])
        if filepath:
            html = filepath.read_text(encoding="utf-8")
            html = _inject_meta_tags(html, article, base_ark, version)
            if version_banner:
                html = _inject_retraction_banner(html, version_banner)
            if retraction_banner:
                html = _inject_retraction_banner(html, retraction_banner)
            return HTMLResponse(html)
    # Fallback: render on the fly (front matter is in the stored markdown)
    html = render_html(article["source_markdown"])
    html = _inject_meta_tags(html, article, base_ark, version)
    if version_banner:
        html = _inject_retraction_banner(html, version_banner)
    if retraction_banner:
        html = _inject_retraction_banner(html, retraction_banner)
    return HTMLResponse(html)


def _inject_retraction_banner(html: str, banner: str) -> str:
    """Insert the retraction banner right after <body> in a rendered HTML doc."""
    import re as _re
    return _re.sub(r"(<body[^>]*>)", r"\1" + banner, html, count=1, flags=_re.IGNORECASE)


def _inject_meta_tags(html: str, article: dict, base_ark: str, version: int | None) -> str:
    """Inject title, meta description, Open Graph, Twitter Card, and JSON-LD
    tags into the <head> of a pre-rendered article HTML page.

    Also fixes the <title> tag to show the actual article title.
    """
    import re as _re
    import json as _json
    from html import escape

    title = escape(article.get("title") or "Untitled")
    abstract = escape(article.get("abstract") or "")
    ark_display = f"{base_ark}.v{version}" if version is not None else base_ark
    url = f"{config.base_url}/article/{ark_display}"
    authors = get_article_authors(article["id"])
    author_names = ", ".join(a["name"] for a in authors) if authors else ""
    published = article.get("published_at")
    published_str = published.strftime("%Y-%m-%d") if published else ""
    jsonld = _json.dumps(build_jsonld(article, authors, display_ark=ark_display, version=version))

    # Fix the <title> tag
    html = _re.sub(
        r"<title>[^<]*</title>",
        f"<title>{title} · GenRxiv</title>",
        html,
        count=1,
    )

    meta_tags = (
        f'<meta name="description" content="{abstract[:160]}">\n'
        f'<meta property="og:type" content="article">\n'
        f'<meta property="og:title" content="{title}">\n'
        f'<meta property="og:description" content="{abstract[:200]}">\n'
        f'<meta property="og:url" content="{url}">\n'
        f'<meta property="og:site_name" content="GenRxiv">\n'
        f'<meta name="twitter:card" content="summary">\n'
        f'<meta name="twitter:title" content="{title}">\n'
        f'<meta name="twitter:description" content="{abstract[:200]}">\n'
        f'<link rel="canonical" href="{url}">\n'
    )
    if author_names:
        meta_tags += f'<meta name="author" content="{escape(author_names)}">\n'
    if published_str:
        meta_tags += f'<meta property="article:published_time" content="{published_str}">\n'
    meta_tags += f'<script type="application/ld+json">{jsonld}</script>'

    # Insert meta tags right before </head> (use string replace, not regex,
    # to avoid backslash escaping issues in the JSON-LD content).
    html = html.replace("</head>", meta_tags + "\n</head>", 1)
    return html


# ─── Moderation (admin) ────────────────────────────────────────────────────

class ModerationAction(BaseModel):
    action: str  # "approve" or "reject"
    note: str = ""


@router.get("/admin/queue", include_in_schema=False)
def moderation_queue(_reviewer: dict = Depends(require_reviewer)):
    """List pending submissions."""
    with get_conn().connection() as conn:
        rows = conn.execute(
            """SELECT a.id, a.title, a.submitted_at,
                      a.submitted_by, au.name as submitter_name, au.orcid as submitter_orcid
               FROM articles a
               LEFT JOIN authors au ON a.submitted_by = au.id
               WHERE a.status = 'pending'
               ORDER BY a.submitted_at ASC""",
        ).fetchall()
    return {"items": rows}


@router.patch("/admin/articles/{article_id}", include_in_schema=False)
def moderate_article(
    article_id: int,
    action: ModerationAction,
    reviewer: dict = Depends(require_reviewer),
):
    """Approve or reject a submission."""
    with get_conn().connection() as conn:
        row = conn.execute(
            "SELECT id, title, abstract, status, source_markdown, version FROM articles WHERE id = %s", (article_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Article not found")
        if row["status"] != "pending":
            raise HTTPException(400, f"Article is already {row['status']}")

        if action.action == "approve":
            ark, version = _approve_article(conn, article_id, row, reviewer["id"], action.note)
            notify_approved(article_id, ark, row["title"], action.note)
            return {"id": article_id, "ark": ark, "status": "published", "version": version}

        elif action.action == "reject":
            conn.execute(
                """UPDATE articles
                   SET status = 'rejected', moderated_by = %s, moderated_at = now(),
                       moderation_note = %s
                   WHERE id = %s""",
                (reviewer["id"], action.note or None, article_id),
            )
            conn.commit()
            notify_rejected(article_id, row["title"], action.note)
            return {"id": article_id, "status": "rejected"}

        else:
            raise HTTPException(400, "action must be 'approve' or 'reject'")


def _approve_article(
    conn,
    article_id: int,
    row: dict,
    moderator_id: int,
    note: str = "",
) -> tuple[str, int]:
    """Approve a pending article: assign ARK, render HTML/PDF, mark published.

    Handles version transfer (if the article supersedes a previous version,
    the ARK moves from the old version to the new one).

    Returns (ark, version). Caller is responsible for committing the
    transaction and sending notifications.
    """
    # If this is a new version, transfer the ARK from the previous version
    existing = conn.execute(
        "SELECT ark, supersedes_id FROM articles WHERE id = %s", (article_id,)
    ).fetchone()
    if existing and existing["supersedes_id"]:
        prev = conn.execute(
            "SELECT ark FROM articles WHERE id = %s", (existing["supersedes_id"],)
        ).fetchone()
        if prev and prev["ark"]:
            ark = prev["ark"]
            conn.execute(
                "UPDATE articles SET status = 'superseded', ark = NULL WHERE id = %s",
                (existing["supersedes_id"],),
            )
        else:
            ark = assign_ark(article_id)
    else:
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
        (ark, html_path, pdf_path, moderator_id, note or None, article_id),
    )

    return ark, row["version"]


# ─── Stats ─────────────────────────────────────────────────────────────────

@router.get("/admin/stats", include_in_schema=False)
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


# ─── Author management (admin) ─────────────────────────────────────────────

class AuthorStatusAction(BaseModel):
    status: str  # "active", "suspended", or "banned"
    reason: str = ""


@router.get("/admin/authors/list", include_in_schema=False)
def list_authors(
    _admin: dict = Depends(require_admin),
    status: str = Query("", description="Filter by account_status"),
):
    """List all authors, optionally filtered by account status."""
    with get_conn().connection() as conn:
        if status:
            rows = conn.execute(
                """SELECT id, orcid, name, email, affiliation,
                          account_status, status_reason, status_changed_at,
                          created_at
                   FROM authors WHERE account_status = %s
                   ORDER BY status_changed_at DESC NULLS LAST, created_at DESC""",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, orcid, name, email, affiliation,
                          account_status, status_reason, status_changed_at,
                          created_at
                   FROM authors ORDER BY created_at DESC""",
            ).fetchall()
    return {"items": rows}


@router.patch("/admin/authors/{author_id}", include_in_schema=False)
def update_author_status(
    author_id: int,
    action: AuthorStatusAction,
    admin: dict = Depends(require_admin),
):
    """Suspend, ban, or reactivate an author account.

    - 'suspended': cannot submit new papers, existing papers stay published
    - 'banned': cannot log in, existing papers stay published
    - 'active': restores normal access
    """
    if action.status not in ("active", "suspended", "banned"):
        raise HTTPException(400, "status must be 'active', 'suspended', or 'banned'")

    with get_conn().connection() as conn:
        row = conn.execute(
            "SELECT id, orcid, github_id, name, account_status FROM authors WHERE id = %s",
            (author_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Author not found")

        # Prevent admins from suspending themselves or other admins (ORCID or GitHub)
        if (row["orcid"] and row["orcid"] in config.admin_orcids) or (row["github_id"] and row["github_id"] in config.admin_github_ids):
            raise HTTPException(400, "Cannot modify an admin account")

        conn.execute(
            """UPDATE authors
               SET account_status = %s, status_reason = %s,
                   status_changed_at = now(), status_changed_by = %s
               WHERE id = %s""",
            (action.status, action.reason or None, admin["id"], author_id),
        )

        # If banning or suspending, destroy all active sessions
        if action.status in ("suspended", "banned"):
            conn.execute("DELETE FROM sessions WHERE author_id = %s", (author_id,))

        conn.commit()

    return {
        "id": author_id,
        "account_status": action.status,
        "reason": action.reason or None,
    }


# ─── Role management (admin) ───────────────────────────────────────────────

class RoleAction(BaseModel):
    role: str  # "author", "reviewer", or "admin"


@router.get("/admin/roles/list", include_in_schema=False)
def list_roles(
    _admin: dict = Depends(require_admin),
):
    """List all authors with their roles, for the role management page."""
    with get_conn().connection() as conn:
        rows = conn.execute(
            """SELECT id, orcid, github_id, name, email, role,
                      account_status, created_at
               FROM authors ORDER BY
                 CASE WHEN role = 'admin' THEN 0
                      WHEN role = 'reviewer' THEN 1
                      ELSE 2 END,
                 created_at DESC""",
        ).fetchall()
    return {"items": rows}


@router.patch("/admin/roles/{author_id}", include_in_schema=False)
def update_author_role(
    author_id: int,
    action: RoleAction,
    admin: dict = Depends(require_admin),
):
    """Update an author's role (author, reviewer, or admin).

    - Only admins can change roles.
    - Cannot change the role of an env-var-configured admin (bootstrap protection).
    - Cannot change your own role (prevent self-lockout).
    """
    if action.role not in ("author", "reviewer", "admin"):
        raise HTTPException(400, "role must be 'author', 'reviewer', or 'admin'")

    with get_conn().connection() as conn:
        row = conn.execute(
            "SELECT id, orcid, github_id, name, role FROM authors WHERE id = %s",
            (author_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Author not found")

        # Prevent self-modification (avoid locking yourself out)
        if row["id"] == admin["id"]:
            raise HTTPException(400, "Cannot change your own role")

        # Prevent changing env-var-configured admins
        if (row["orcid"] and row["orcid"] in config.admin_orcids) or (row["github_id"] and row["github_id"] in config.admin_github_ids):
            raise HTTPException(400, "Cannot change the role of a configured admin (set via environment variable)")

        conn.execute(
            "UPDATE authors SET role = %s WHERE id = %s",
            (action.role, author_id),
        )
        conn.commit()

    return {
        "id": author_id,
        "name": row["name"],
        "role": action.role,
    }


class GitHubHandleUpdate(BaseModel):
    github_id: str | None = None


@router.patch("/admin/authors/{author_id}/github", include_in_schema=False)
def update_author_github(
    author_id: int,
    action: GitHubHandleUpdate,
    admin: dict = Depends(require_admin),
):
    """Add or update a GitHub handle for an author (admin only).

    This links the author's ORCID-based account to their GitHub identity,
    so they can sign in with either method. The GitHub handle must be
    unique across all authors.
    """
    github_id = action.github_id.strip() if action.github_id else None

    with get_conn().connection() as conn:
        row = conn.execute(
            "SELECT id, name, orcid, github_id FROM authors WHERE id = %s",
            (author_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Author not found")

        if github_id:
            # Check uniqueness (excluding this author)
            existing = conn.execute(
                "SELECT id FROM authors WHERE github_id = %s AND id != %s",
                (github_id, author_id),
            ).fetchone()
            if existing:
                raise HTTPException(400, f"GitHub handle '{github_id}' is already linked to another author")

        conn.execute(
            "UPDATE authors SET github_id = %s WHERE id = %s",
            (github_id, author_id),
        )
        conn.commit()

    return {
        "id": author_id,
        "name": row["name"],
        "github_id": github_id,
    }


# ─── Maintenance mode (admin) ──────────────────────────────────────────────

@router.get("/admin/maintenance", include_in_schema=False)
def get_maintenance_status(_admin: dict = Depends(require_admin)):
    """Get current maintenance mode status."""
    from db import is_maintenance_mode, get_setting
    return {
        "maintenance_mode": is_maintenance_mode(),
        "message": get_setting("maintenance_message", ""),
    }


@router.post("/admin/maintenance", include_in_schema=False)
def set_maintenance_status(
    enabled: bool = Form(...),
    message: str = Form(""),
    _admin: dict = Depends(require_admin),
):
    """Toggle maintenance mode on/off."""
    from db import set_setting
    set_setting("maintenance_mode", "true" if enabled else "false")
    if message:
        set_setting("maintenance_message", message)
    return {
        "maintenance_mode": enabled,
        "message": message if enabled else "",
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
            """SELECT a.id, a.ark, a.title, a.abstract, a.subjects, a.published_at
               FROM articles a
               JOIN article_authors aa ON a.id = aa.article_id
               WHERE aa.author_id = %s AND a.status = 'published'
               ORDER BY a.published_at DESC""",
            (author["id"],),
        ).fetchall()
    return {
        "author": author,
        "articles": articles,
    }


# ─── Subject browsing ──────────────────────────────────────────────────────

@router.get("/api/subjects")
def list_subjects():
    """List all subject classifications with article counts."""
    with get_conn().connection() as conn:
        rows = conn.execute(
            """SELECT subject, COUNT(*) as count
               FROM articles, unnest(subjects) AS subject
               WHERE status = 'published'
               GROUP BY subject
               ORDER BY count DESC, subject ASC""",
        ).fetchall()
    return {"subjects": rows}


@router.get("/api/subjects/{subject:path}/articles")
def articles_by_subject(subject: str, page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100)):
    """List published articles by subject classification."""
    from urllib.parse import unquote
    subject = unquote(subject)
    offset = (page - 1) * per_page
    with get_conn().connection() as conn:
        rows = conn.execute(
            """SELECT id, ark, title, abstract, subjects, published_at
               FROM articles
               WHERE status = 'published' AND %s = ANY(subjects)
               ORDER BY published_at DESC LIMIT %s OFFSET %s""",
            (subject, per_page, offset),
        ).fetchall()
        total = conn.execute(
            """SELECT COUNT(*) as c FROM articles
               WHERE status = 'published' AND %s = ANY(subjects)""",
            (subject,),
        ).fetchone()["c"]
    return {
        "subject": subject,
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
        total_authors = conn.execute("SELECT COUNT(*) as c FROM authors WHERE orcid IS NOT NULL").fetchone()["c"]
        total_downloads = conn.execute("SELECT COUNT(*) as c FROM downloads").fetchone()["c"]
        agent_downloads = conn.execute(
            "SELECT COUNT(*) as c FROM downloads WHERE is_agent = true"
        ).fetchone()["c"]
        human_downloads = conn.execute(
            "SELECT COUNT(*) as c FROM downloads WHERE is_agent = false"
        ).fetchone()["c"]
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
        "top_articles": top_articles,
    }
