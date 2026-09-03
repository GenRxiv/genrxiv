"""
ORCID Public API client for fetching cached record summaries.

Uses client credentials (read-public scope) to fetch an author's
public works count. This is cached in the authors table and used
for prioritizing content from established authors.
"""
import httpx
from config import config
from db import get_conn


def _get_client_token() -> str | None:
    """Get a client credentials token with /read-public scope."""
    if not config.orcid_client_id or not config.orcid_client_secret:
        return None
    try:
        with httpx.Client(timeout=15) as client:
            r = client.post(
                config.orcid_token_url,
                data={
                    "client_id": config.orcid_client_id,
                    "client_secret": config.orcid_client_secret,
                    "grant_type": "client_credentials",
                    "scope": "/read-public",
                },
            )
            if r.status_code != 200:
                return None
            return r.json().get("access_token")
    except Exception:
        return None


def fetch_orcid_works_count(orcid: str) -> int:
    """Fetch the number of public works for an ORCID iD.

    Returns 0 if the API call fails or the record has no works.
    """
    token = _get_client_token()
    if not token:
        return 0
    try:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        with httpx.Client(timeout=15) as client:
            r = client.get(
                f"{config.orcid_api_url}/{orcid}/works",
                headers=headers,
            )
            if r.status_code != 200:
                return 0
            data = r.json()
            # The works endpoint returns a summary with group + work-summary
            groups = data.get("group", [])
            count = 0
            for group in groups:
                summaries = group.get("work-summary", [])
                count += len(summaries)
            return count
    except Exception:
        return 0


def cache_orcid_record(author_id: int, orcid: str) -> int:
    """Fetch and cache the ORCID works count for an author.

    Returns the works count (0 if fetch failed).
    """
    count = fetch_orcid_works_count(orcid)
    with get_conn().connection() as conn:
        conn.execute(
            """UPDATE authors
               SET orcid_works_count = %s,
                   orcid_record_fetched_at = now()
               WHERE id = %s""",
            (count, author_id),
        )
        conn.commit()
    return count
