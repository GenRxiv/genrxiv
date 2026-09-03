"""
GenRxiv API — ORCID OAuth authentication.

Flow:
1. User clicks "Sign in with ORCID" → redirect to ORCID authorize URL
2. ORCID redirects back to /auth/orcid/callback with code
3. Exchange code for access token
4. Fetch ORCID record (name, ORCID iD)
5. Create or update author in DB
6. Create session, set cookie
"""
import secrets
import time
from datetime import datetime, timezone, timedelta

import httpx2 as httpx
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel
from config import config
from db import get_conn
from ratelimit import limiter

router = APIRouter(prefix="/auth")

SESSION_COOKIE = "genrxiv_session"
SESSION_DURATION = timedelta(days=7)


def _create_orcid_authorize_url(state: str) -> str:
    params = {
        "client_id": config.orcid_client_id,
        "response_type": "code",
        "scope": config.orcid_scope,
        "redirect_uri": config.orcid_redirect_url,
        "state": state,
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{config.orcid_authorize_url}?{query}"


def _exchange_code_for_token(code: str) -> dict:
    """Exchange authorization code for ORCID access token."""
    data = {
        "client_id": config.orcid_client_id,
        "client_secret": config.orcid_client_secret,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.orcid_redirect_url,
    }
    with httpx.Client() as client:
        r = client.post(config.orcid_token_url, data=data)
        if r.status_code != 200:
            raise HTTPException(400, "Failed to exchange code for token")
        return r.json()


def _fetch_orcid_record(orcid: str, access_token: str) -> dict:
    """Fetch the ORCID record for name and affiliation."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }
    try:
        with httpx.Client() as client:
            r = client.get(f"{config.orcid_api_url}/{orcid}/record", headers=headers)
            if r.status_code != 200:
                return {}
            return r.json()
    except Exception:
        return {}


def _extract_name(record: dict) -> str:
    """Extract display name from ORCID record."""
    person = record.get("person", {})
    name_obj = person.get("name", {})
    given = name_obj.get("given-names", {}).get("value", "")
    family = name_obj.get("family-name", {}).get("value", "")
    if given and family:
        return f"{given} {family}"
    return given or family or "Unknown"


def _extract_affiliation(record: dict) -> str | None:
    """Extract primary affiliation from ORCID record."""
    employments = record.get("activities-summary", {}).get("employments", {}).get("affiliation-group", [])
    for group in employments:
        summaries = group.get("summaries", [])
        for s in summaries:
            org = s.get("employment-summary", {}).get("organization", {})
            name = org.get("name")
            if name:
                return name
    return None


def _extract_email(record: dict) -> str | None:
    """Extract primary email from ORCID record.

    Note: The /email scope is only available on the ORCID Member API.
    For Public API clients, this will always return None. Authors can
    add their email manually from the dashboard.
    """
    emails = record.get("person", {}).get("emails", {}).get("email", [])
    for e in emails:
        if e.get("primary") and e.get("email"):
            return e["email"]
    for e in emails:
        if e.get("email"):
            return e["email"]
    return None


def _upsert_author(orcid: str, name: str, affiliation: str | None, email: str | None = None) -> dict:
    """Create or update author in DB, return author dict."""
    with get_conn().connection() as conn:
        row = conn.execute(
            "SELECT id, orcid, name, email, affiliation FROM authors WHERE orcid = %s",
            (orcid,),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE authors SET name = %s, email = COALESCE(%s, email), affiliation = COALESCE(%s, affiliation) WHERE orcid = %s",
                (name, email, affiliation, orcid),
            )
            conn.commit()
            row["name"] = name
            if email:
                row["email"] = email
            if affiliation:
                row["affiliation"] = affiliation
            return row
        else:
            row = conn.execute(
                "INSERT INTO authors (orcid, name, email, affiliation) VALUES (%s, %s, %s, %s) RETURNING id, orcid, name, email, affiliation",
                (orcid, name, email, affiliation),
            ).fetchone()
            conn.commit()
            return row


def _create_session(author_id: int, orcid_access_token: str) -> str:
    """Create a session in the DB, return token."""
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + SESSION_DURATION
    with get_conn().connection() as conn:
        conn.execute(
            "INSERT INTO sessions (token, author_id, orcid_access_token, expires_at) VALUES (%s, %s, %s, %s)",
            (token, author_id, orcid_access_token, expires),
        )
        conn.commit()
    return token


def get_current_author(request: Request) -> dict | None:
    """Get the current logged-in author from session cookie, or None."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    with get_conn().connection() as conn:
        row = conn.execute(
            """SELECT a.id, a.orcid, a.name, a.email, a.affiliation, s.expires_at
               FROM sessions s JOIN authors a ON s.author_id = a.id
               WHERE s.token = %s AND s.expires_at > now()""",
            (token,),
        ).fetchone()
    if not row:
        return None
    return {"id": row["id"], "orcid": row["orcid"], "name": row["name"], "email": row["email"], "affiliation": row["affiliation"]}


def require_author(request: Request) -> dict:
    """Require authentication, raise 401 if not logged in."""
    author = get_current_author(request)
    if not author:
        raise HTTPException(401, "Not authenticated")
    return author


def require_admin(request: Request) -> dict:
    """Require admin privileges."""
    author = require_author(request)
    if author["orcid"] not in config.admin_orcids:
        raise HTTPException(403, "Admin access required")
    return author


@router.get("/orcid")
def orcid_login(request: Request, redirect: str = "/"):
    """Redirect to ORCID OAuth."""
    state = secrets.token_urlsafe(16)
    # Store redirect destination in state via cookie
    response = RedirectResponse(_create_orcid_authorize_url(state))
    response.set_cookie("orcid_state", state, max_age=600, httponly=True, samesite="lax")
    response.set_cookie("orcid_redirect", redirect, max_age=600, httponly=True, samesite="lax")
    return response


@router.get("/orcid/callback")
@limiter.limit("10 per minute")
def orcid_callback(request: Request, code: str, state: str):
    """Handle ORCID OAuth callback."""
    expected_state = request.cookies.get("orcid_state")
    if not expected_state or expected_state != state:
        raise HTTPException(400, "Invalid OAuth state")

    token_data = _exchange_code_for_token(code)
    orcid = token_data.get("orcid")
    access_token = token_data.get("access_token")
    if not orcid:
        raise HTTPException(400, "No ORCID iD returned")

    record = _fetch_orcid_record(orcid, access_token)
    name = _extract_name(record)
    affiliation = _extract_affiliation(record)
    email = _extract_email(record)

    author = _upsert_author(orcid, name, affiliation, email)
    session_token = _create_session(author["id"], access_token)

    # Fetch and cache the author's ORCID works count (non-blocking on failure)
    try:
        from orcid_client import cache_orcid_record
        cache_orcid_record(author["id"], orcid)
    except Exception:
        pass  # Don't let ORCID API failure block login

    redirect = request.cookies.get("orcid_redirect", "/")
    response = RedirectResponse(redirect)
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        max_age=int(SESSION_DURATION.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=True,
    )
    response.delete_cookie("orcid_state")
    response.delete_cookie("orcid_redirect")
    return response


@router.post("/logout")
def logout(request: Request):
    """Destroy session and redirect to homepage."""
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        with get_conn().connection() as conn:
            conn.execute("DELETE FROM sessions WHERE token = %s", (token,))
            conn.commit()
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


@router.get("/me")
def me(request: Request):
    """Current user info."""
    author = get_current_author(request)
    if not author:
        return {"authenticated": False}
    is_admin = author["orcid"] in config.admin_orcids
    return {
        "authenticated": True,
        "orcid": author["orcid"],
        "name": author["name"],
        "email": author.get("email"),
        "affiliation": author["affiliation"],
        "is_admin": is_admin,
    }


class EmailUpdate(BaseModel):
    email: str | None = None


@router.post("/me/email")
def update_email(request: Request, body: EmailUpdate):
    """Set or update the current author's email for notifications."""
    import re
    author = require_author(request)
    email = body.email.strip() if body.email else None
    if email:
        # Basic email validation
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            raise HTTPException(400, "Invalid email address")
    with get_conn().connection() as conn:
        conn.execute(
            "UPDATE authors SET email = %s WHERE id = %s",
            (email, author["id"]),
        )
        conn.commit()
    return {"status": "ok", "email": email}
