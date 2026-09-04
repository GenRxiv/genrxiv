"""
Reconcile pending submissions on startup.

When the server restarts, some pending submissions may need re-processing:

1. **Screening said auto_approve but approval failed** — e.g. the conversion
   service was temporarily unavailable when the submission came in. The
   screening report exists with verdict=auto_approve, but the article is
   still pending. These should be retried automatically.

2. **No screening report exists** — screening was disabled or the screening
   call failed before saving a report. If screening is now enabled, these
   should be re-screened.

3. **Screening said flag_for_review** — these are waiting for human review
   by design. They are NOT re-processed.

This module runs once on startup, after the DB pool and migrations are
initialized. It logs what it finds and what it does. It never blocks
startup — if reconciliation fails, the server still starts and the
submissions remain pending for manual admin review.
"""
import logging

logger = logging.getLogger(__name__)


def reconcile_pending_submissions() -> dict:
    """Scan pending submissions and re-process any that are stranded.

    Returns a summary dict with counts of what was found and what was done.
    Called from the FastAPI lifespan on startup.
    """
    from db import get_conn
    from screening import get_screening_report, screen_submission, save_screening_report

    summary = {
        "scanned": 0,
        "retried_approval": 0,
        "rescreened": 0,
        "still_pending": 0,
        "errors": 0,
    }

    try:
        with get_conn().connection() as conn:
            pending = conn.execute(
                """SELECT id, title, abstract, source_markdown, submitted_by
                   FROM articles WHERE status = 'pending'
                   ORDER BY submitted_at ASC""",
            ).fetchall()
    except Exception as e:
        logger.error("Reconciliation: failed to query pending submissions: %s", e)
        summary["errors"] += 1
        return summary

    summary["scanned"] = len(pending)
    if not pending:
        return summary

    logger.info("Reconciliation: scanning %d pending submission(s)", len(pending))

    for p in pending:
        article_id = p["id"]
        title = p["title"]
        abstract = p["abstract"] or ""
        markdown = p["source_markdown"] or ""
        submitter_id = p["submitted_by"]

        existing_report = get_screening_report(article_id)

        if existing_report and existing_report["verdict"] == "auto_approve":
            # Case 1: screening said auto_approve but approval failed.
            # Retry the approval now.
            logger.info(
                "Reconciliation: retrying auto-approval for article %d (%s)",
                article_id,
                title[:60],
            )
            try:
                _retry_approval(article_id, submitter_id)
                summary["retried_approval"] += 1
                logger.info(
                    "Reconciliation: article %d approved on retry", article_id
                )
            except Exception as e:
                logger.error(
                    "Reconciliation: auto-approval retry failed for article %d: %s",
                    article_id,
                    e,
                )
                summary["errors"] += 1
                summary["still_pending"] += 1

        elif existing_report is None or existing_report["verdict"] == "screening_disabled":
            # Case 2: no screening report, or screening was disabled at
            # submission time. Re-screen if screening is now enabled.
            from config import config
            if not config.screening_enabled:
                logger.info(
                    "Reconciliation: article %d has no/disabled screening report, "
                    "but screening is disabled — leaving pending",
                    article_id,
                )
                summary["still_pending"] += 1
                continue

            logger.info(
                "Reconciliation: re-screening article %d (%s)",
                article_id,
                title[:60],
            )
            try:
                result = screen_submission(title, abstract, markdown)
                save_screening_report(article_id, result)

                if result["verdict"] == "auto_approve":
                    _retry_approval(article_id, submitter_id)
                    summary["rescreened"] += 1
                    logger.info(
                        "Reconciliation: article %d re-screened and auto-approved",
                        article_id,
                    )
                else:
                    summary["rescreened"] += 1
                    summary["still_pending"] += 1
                    logger.info(
                        "Reconciliation: article %d re-screened as %s — pending",
                        article_id,
                        result["verdict"],
                    )
            except Exception as e:
                logger.error(
                    "Reconciliation: re-screening failed for article %d: %s",
                    article_id,
                    e,
                )
                summary["errors"] += 1
                summary["still_pending"] += 1

        else:
            # Case 3: screening said flag_for_review (or screening_error).
            # These are waiting for human review by design.
            summary["still_pending"] += 1
            logger.info(
                "Reconciliation: article %d has verdict=%s — leaving for human review",
                article_id,
                existing_report["verdict"],
            )

    logger.info(
        "Reconciliation complete: scanned=%d retried=%d rescreened=%d pending=%d errors=%d",
        summary["scanned"],
        summary["retried_approval"],
        summary["rescreened"],
        summary["still_pending"],
        summary["errors"],
    )
    return summary


def _retry_approval(article_id: int, submitter_id: int) -> None:
    """Retry the auto-approval flow for a pending article.

    Raises on failure — the caller handles the exception.
    """
    from db import get_conn
    from articles import _approve_article
    from notifications import notify_approved

    with get_conn().connection() as conn:
        row = conn.execute(
            """SELECT id, title, abstract, status, source_markdown,
                      version, submitted_at
               FROM articles WHERE id = %s""",
            (article_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"Article {article_id} not found")
        if row["status"] != "pending":
            raise ValueError(
                f"Article {article_id} is {row['status']}, not pending"
            )

        ark, version = _approve_article(
            conn,
            article_id,
            row,
            moderator_id=submitter_id,
            note="Auto-approved by automated screening (startup reconciliation)",
        )
        conn.commit()

    notify_approved(
        article_id, ark, row["title"],
        "Auto-approved by automated screening (startup reconciliation)",
    )
