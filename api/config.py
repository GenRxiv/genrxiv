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

    # Admin ORCIDs (can moderate)
    admin_orcids: tuple = ()

    @classmethod
    def from_env(cls) -> "Config":
        admin_orcids = tuple(
            x.strip()
            for x in os.environ.get("ADMIN_ORCIDS", "").split(",")
            if x.strip()
        )
        return cls(
            database_url=os.environ["DATABASE_URL"],
            orcid_client_id=os.environ.get("ORCID_CLIENT_ID", ""),
            orcid_client_secret=os.environ.get("ORCID_CLIENT_SECRET", ""),
            session_secret=os.environ.get("SESSION_SECRET", "dev-secret-change-me"),
            ark_naan=os.environ.get("ARK_NAAN", "99999"),
            smtp_host=os.environ.get("SMTP_HOST", ""),
            smtp_port=int(os.environ.get("SMTP_PORT", "587")),
            smtp_username=os.environ.get("SMTP_USERNAME", ""),
            smtp_password=os.environ.get("SMTP_PASSWORD", ""),
            admin_orcids=admin_orcids,
        )


config = Config.from_env()
