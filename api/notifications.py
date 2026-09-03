"""
GenRxiv API — email notifications.

Sends email to authors when their submissions are approved or rejected.
Uses SMTP (configured via environment variables). If SMTP is not configured
or the author has no email on file, notifications are silently skipped.
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from config import config
from db import get_conn


def _get_submitter_email(article_id: int) -> str | None:
    """Get the email address of the user who submitted an article."""
    with get_conn().connection() as conn:
        row = conn.execute(
            """SELECT a.email
               FROM articles ar
               JOIN authors a ON ar.submitted_by = a.id
               WHERE ar.id = %s""",
            (article_id,),
        ).fetchone()
    return row["email"] if row else None


def _smtp_configured() -> bool:
    """Check if SMTP is configured."""
    return bool(config.smtp_host and config.smtp_username and config.smtp_password)


def _send_email(to: str, subject: str, body: str):
    """Send an email via SMTP. Silently fails if SMTP is not configured."""
    if not _smtp_configured():
        return

    msg = MIMEMultipart("alternative")
    msg["From"] = config.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(config.smtp_host, config.smtp_port) as server:
            server.starttls()
            server.login(config.smtp_username, config.smtp_password)
            server.sendmail(config.smtp_from, [to], msg.as_string())
    except Exception:
        pass


def notify_approved(article_id: int, ark: str, title: str, note: str = ""):
    """Notify the submitter that their article was approved."""
    if not _smtp_configured():
        return
    email = _get_submitter_email(article_id)
    if not email:
        return

    article_url = f"{config.base_url}/article/{ark}"
    body = f"""Your GenRxiv submission has been approved and is now published.

Title: {title}
ARK: {ark}
URL: {article_url}
"""
    if note:
        body += f"\nModerator note: {note}\n"

    _send_email(email, f"[GenRxiv] Published: {title}", body)


def notify_rejected(article_id: int, title: str, note: str = ""):
    """Notify the submitter that their article was rejected."""
    if not _smtp_configured():
        return
    email = _get_submitter_email(article_id)
    if not email:
        return

    body = f"""Your GenRxiv submission was not accepted for publication.

Title: {title}
"""
    if note:
        body += f"\nModerator note: {note}\n"

    _send_email(email, f"[GenRxiv] Submission not accepted: {title}", body)
