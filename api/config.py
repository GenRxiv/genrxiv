"""
GenRxiv API — configuration and environment.
"""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    # Database
    database_url: str

    # ORCID OAuth
    orcid_client_id: str = ""
    orcid_client_secret: str = ""
    orcid_authorize_url: str = "https://orcid.org/oauth/authorize"
    orcid_token_url: str = "https://orcid.org/oauth/token"
    orcid_api_url: str = "https://pub.orcid.org/v3.0"
    orcid_redirect_url: str = "https://genrxiv.org/auth/orcid/callback"
    orcid_scope: str = "/authenticate"

    # GitHub OAuth (alternative login for admins/reviewers without ORCID)
    github_client_id: str = ""
    github_client_secret: str = ""
    github_redirect_url: str = "https://genrxiv.org/auth/github/callback"

    # Session
    session_secret: str = "dev-secret-change-me"

    # ARK
    ark_naan: str = "99999"

    # SMTP (Resend)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = "admin@genrxiv.org"

    # Files
    files_dir: str = "/app/files"

    # Conversion service
    convert_service_url: str = "http://convert:8000"

    # Site
    base_url: str = "https://genrxiv.org"
    site_name: str = "GenRxiv"

    # Admin ORCIDs (can moderate, withdraw, suspend/ban authors)
    admin_orcids: tuple = ()

    # Reviewer ORCIDs (can approve/reject submissions but not withdraw or suspend)
    reviewer_orcids: tuple = ()

    # Admin GitHub usernames (same powers as admin_orcids)
    admin_github_ids: tuple = ()

    # Reviewer GitHub usernames (same powers as reviewer_orcids)
    reviewer_github_ids: tuple = ()

    # Automated screening (Cloudflare Workers AI)
    screening_enabled: bool = False
    screening_cf_api_token: str = ""
    screening_cf_account_id: str = ""
    screening_model: str = "@cf/meta/llama-3.2-3b-instruct"

    # Analytics (Umami)
    umami_website_id: str = ""

    @classmethod
    def from_env(cls) -> "Config":
        admin_orcids = tuple(
            x.strip()
            for x in os.environ.get("ADMIN_ORCIDS", "").split(",")
            if x.strip()
        )
        reviewer_orcids = tuple(
            x.strip()
            for x in os.environ.get("REVIEWER_ORCIDS", "").split(",")
            if x.strip()
        )
        admin_github_ids = tuple(
            x.strip()
            for x in os.environ.get("ADMIN_GITHUB_IDS", "").split(",")
            if x.strip()
        )
        reviewer_github_ids = tuple(
            x.strip()
            for x in os.environ.get("REVIEWER_GITHUB_IDS", "").split(",")
            if x.strip()
        )
        return cls(
            database_url=os.environ["DATABASE_URL"],
            orcid_client_id=os.environ.get("ORCID_CLIENT_ID", ""),
            orcid_client_secret=os.environ.get("ORCID_CLIENT_SECRET", ""),
            github_client_id=os.environ.get("GITHUB_CLIENT_ID", ""),
            github_client_secret=os.environ.get("GITHUB_CLIENT_SECRET", ""),
            session_secret=os.environ.get("SESSION_SECRET", "dev-secret-change-me"),
            ark_naan=os.environ.get("ARK_NAAN", "99999"),
            smtp_host=os.environ.get("SMTP_HOST", ""),
            smtp_port=int(os.environ.get("SMTP_PORT", "587")),
            smtp_username=os.environ.get("SMTP_USERNAME", ""),
            smtp_password=os.environ.get("SMTP_PASSWORD", ""),
            admin_orcids=admin_orcids,
            reviewer_orcids=reviewer_orcids,
            admin_github_ids=admin_github_ids,
            reviewer_github_ids=reviewer_github_ids,
            screening_enabled=os.environ.get("SCREENING_ENABLED", "").lower() in ("1", "true", "yes"),
            screening_cf_api_token=os.environ.get("CF_AGENT_TOKEN", ""),
            screening_cf_account_id=os.environ.get("CF_ACCOUNT_ID", ""),
            screening_model=os.environ.get("SCREENING_MODEL", "@cf/meta/llama-3.2-3b-instruct"),
            umami_website_id=os.environ.get("UMAMI_WEBSITE_ID", ""),
        )


config = Config.from_env()
