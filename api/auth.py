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
            "SELECT id, orcid, name, email, affiliation, account_status, status_reason FROM authors WHERE orcid = %s",
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
                "INSERT INTO authors (orcid, name, email, affiliation) VALUES (%s, %s, %s, %s) RETURNING id, orcid, name, email, affiliation, account_status, status_reason",
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


# ─── GitHub OAuth (alternative login for admins/reviewers) ─────────────────

def _create_github_authorize_url(state: str) -> str:
    """Build the GitHub OAuth authorize URL."""
    params = {
        "client_id": config.github_client_id,
        "redirect_uri": config.github_redirect_url,
        "scope": "read:user user:email",
        "state": state,
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"https://github.com/login/oauth/authorize?{query}"


def _exchange_github_code(code: str) -> dict:
    """Exchange GitHub authorization code for access token."""
    data = {
        "client_id": config.github_client_id,
        "client_secret": config.github_client_secret,
        "code": code,
        "redirect_uri": config.github_redirect_url,
    }
    with httpx.Client() as client:
        r = client.post(
            "https://github.com/login/oauth/access_token",
            data=data,
            headers={"Accept": "application/json"},
        )
        if r.status_code != 200:
            raise HTTPException(400, "Failed to exchange GitHub code for token")
        return r.json()


def _fetch_github_user(access_token: str) -> dict:
    """Fetch the GitHub user profile."""
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    with httpx.Client() as client:
        r = client.get("https://api.github.com/user", headers=headers)
        if r.status_code != 200:
            raise HTTPException(400, "Failed to fetch GitHub user profile")
        return r.json()


def _fetch_github_email(access_token: str) -> str | None:
    """Fetch the primary email from GitHub."""
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    try:
        with httpx.Client() as client:
            r = client.get("https://api.github.com/user/emails", headers=headers)
            if r.status_code != 200:
                return None
            emails = r.json()
            for e in emails:
                if e.get("primary") and e.get("verified") and e.get("email"):
                    return e["email"]
            for e in emails:
                if e.get("email"):
                    return e["email"]
    except Exception:
        pass
    return None


def _upsert_github_author(github_id: str, name: str, email: str | None, affiliation: str | None = None) -> dict:
    """Create or update a GitHub-based author in DB, return author dict."""
    with get_conn().connection() as conn:
        row = conn.execute(
            "SELECT id, orcid, github_id, name, email, affiliation, account_status, status_reason FROM authors WHERE github_id = %s",
            (github_id,),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE authors SET name = %s, email = COALESCE(%s, email), affiliation = COALESCE(%s, affiliation) WHERE github_id = %s",
                (name, email, affiliation, github_id),
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
                "INSERT INTO authors (github_id, name, email, affiliation) VALUES (%s, %s, %s, %s) RETURNING id, orcid, github_id, name, email, affiliation, account_status, status_reason",
                (github_id, name, email, affiliation),
            ).fetchone()
            conn.commit()
            return row


def get_current_author(request: Request) -> dict | None:
    """Get the current logged-in author from session cookie, or None."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    with get_conn().connection() as conn:
        row = conn.execute(
            """SELECT a.id, a.orcid, a.github_id, a.name, a.email, a.affiliation,
                      a.role, a.account_status, s.expires_at
               FROM sessions s JOIN authors a ON s.author_id = a.id
               WHERE s.token = %s AND s.expires_at > now()""",
            (token,),
        ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "orcid": row["orcid"],
        "github_id": row["github_id"],
        "name": row["name"],
        "email": row["email"],
        "affiliation": row["affiliation"],
        "role": row["role"],
        "account_status": row["account_status"],
    }


def require_author(request: Request) -> dict:
    """Require authentication, raise 401 if not logged in."""
    author = get_current_author(request)
    if not author:
        raise HTTPException(401, "Not authenticated")
    return author


def _is_admin(author: dict) -> bool:
    """Check if author has admin role (via DB role, env var ORCID, or env var GitHub)."""
    if author.get("role") == "admin":
        return True
    orcid = author.get("orcid")
    if orcid and orcid in config.admin_orcids:
        return True
    github_id = author.get("github_id")
    if github_id and github_id in config.admin_github_ids:
        return True
    return False


def _is_reviewer(author: dict) -> bool:
    """Check if author has reviewer or admin role."""
    if author.get("role") in ("admin", "reviewer"):
        return True
    orcid = author.get("orcid")
    if orcid and (orcid in config.admin_orcids or orcid in config.reviewer_orcids):
        return True
    github_id = author.get("github_id")
    if github_id and (github_id in config.admin_github_ids or github_id in config.reviewer_github_ids):
        return True
    return False


def require_reviewer(request: Request) -> dict:
    """Require reviewer or admin privileges (can approve/reject submissions).

    Checks DB role, env var ORCID lists, and env var GitHub lists.
    """
    author = require_author(request)
    if _is_reviewer(author):
        return author
    raise HTTPException(403, "Reviewer access required")


def require_admin(request: Request) -> dict:
    """Require admin privileges (can withdraw, suspend, ban, manage roles).

    Checks DB role, env var ORCID lists, and env var GitHub lists.
    """
    author = require_author(request)
    if _is_admin(author):
        return author
    raise HTTPException(403, "Admin access required")


@router.get("/orcid", include_in_schema=False)
def orcid_login(request: Request, redirect: str = "/"):
    """Redirect to ORCID OAuth."""
    state = secrets.token_urlsafe(16)
    # Store redirect destination in state via cookie
    response = RedirectResponse(_create_orcid_authorize_url(state))
    response.set_cookie("orcid_state", state, max_age=600, httponly=True, samesite="lax")
    response.set_cookie("orcid_redirect", redirect, max_age=600, httponly=True, samesite="lax")
    return response


@router.get("/orcid/callback", include_in_schema=False)
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

    # Check account status — suspended/banned authors cannot log in
    account_status = author.get("account_status", "active")
    if account_status in ("suspended", "banned"):
        # Destroy any existing sessions for this author
        with get_conn().connection() as conn:
            conn.execute("DELETE FROM sessions WHERE author_id = %s", (author["id"],))
            conn.commit()
        reason = author.get("status_reason") or "No reason provided"
        action = "suspended" if account_status == "suspended" else "permanently banned"
        raise HTTPException(
            403,
            f"Your account has been {action}. Reason: {reason}. "
            "Contact the GenRxiv administrators if you believe this is an error.",
        )

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


@router.get("/github", include_in_schema=False)
def github_login(request: Request, redirect: str = "/"):
    """Redirect to GitHub OAuth."""
    if not config.github_client_id:
        raise HTTPException(404, "GitHub login is not configured")
    state = secrets.token_urlsafe(16)
    response = RedirectResponse(_create_github_authorize_url(state))
    response.set_cookie("github_state", state, max_age=600, httponly=True, samesite="lax")
    response.set_cookie("github_redirect", redirect, max_age=600, httponly=True, samesite="lax")
    return response


@router.get("/github/callback", include_in_schema=False)
@limiter.limit("10 per minute")
def github_callback(request: Request, code: str, state: str):
    """Handle GitHub OAuth callback."""
    expected_state = request.cookies.get("github_state")
    if not expected_state or expected_state != state:
        raise HTTPException(400, "Invalid OAuth state")

    token_data = _exchange_github_code(code)
    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(400, "No access token returned from GitHub")

    user = _fetch_github_user(access_token)
    github_login = user.get("login")
    github_name = user.get("name") or github_login or "GitHub User"
    github_company = user.get("company")
    if not github_login:
        raise HTTPException(400, "No GitHub username returned")

    email = _fetch_github_email(access_token)

    author = _upsert_github_author(github_login, github_name, email, github_company)

    # Check account status — suspended/banned authors cannot log in
    account_status = author.get("account_status", "active")
    if account_status in ("suspended", "banned"):
        with get_conn().connection() as conn:
            conn.execute("DELETE FROM sessions WHERE author_id = %s", (author["id"],))
            conn.commit()
        reason = author.get("status_reason") or "No reason provided"
        action = "suspended" if account_status == "suspended" else "permanently banned"
        raise HTTPException(
            403,
            f"Your account has been {action}. Reason: {reason}. "
            "Contact the GenRxiv administrators if you believe this is an error.",
        )

    session_token = _create_session(author["id"], access_token)

    redirect = request.cookies.get("github_redirect", "/")
    response = RedirectResponse(redirect)
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        max_age=int(SESSION_DURATION.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=True,
    )
    response.delete_cookie("github_state")
    response.delete_cookie("github_redirect")
    return response


@router.post("/logout", include_in_schema=False)
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


@router.get("/me", include_in_schema=False)
def me(request: Request):
    """Current user info."""
    author = get_current_author(request)
    if not author:
        return {"authenticated": False}
    is_admin = _is_admin(author)
    is_reviewer = _is_reviewer(author)
    return {
        "authenticated": True,
        "orcid": author.get("orcid"),
        "github_id": author.get("github_id"),
        "name": author["name"],
        "email": author.get("email"),
        "affiliation": author["affiliation"],
        "role": author.get("role", "author"),
        "is_admin": is_admin,
        "is_reviewer": is_reviewer,
        "account_status": author.get("account_status", "active"),
    }


class EmailUpdate(BaseModel):
    email: str | None = None


@router.post("/me/email", include_in_schema=False)
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
