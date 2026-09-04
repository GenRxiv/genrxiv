"""
Automated submission screening via Cloudflare Workers AI.

This module implements the screening layer that runs after a submission
passes structural validation but before it enters the moderation queue.

Design:
  - The model is asked to produce a strict JSON report about whether the
    submission looks like a legitimate research paper (format, scope,
    spam, structure). It is NOT asked to judge scientific quality.
  - If the report comes back clean (no flags, low spam likelihood, format
    OK, in scope), the submission is auto-published.
  - If the report has any flags, the submission stays pending for human
    review. The report is stored and surfaced to the admin.
  - The model never auto-rejects. A flagged submission waits for a human.

The screening is synchronous: it runs during the POST /api/submit request
and adds ~2-5 seconds of latency. This is intentional — the author gets an
immediate result ("published" or "pending review") rather than a deferred
email later.
"""
import json
import logging
import re
from typing import Any

import httpx2 as httpx

from config import config

logger = logging.getLogger(__name__)

# Cloudflare Workers AI REST API endpoint.
# https://developers.cloudflare.com/workers-ai/get-started/rest-api/
CF_AI_BASE = "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"

# How much of the markdown to send to the model. We send the abstract +
# a truncated body. The model doesn't need the full paper to judge
# "is this paper-shaped" — and truncating keeps us well within the free
# tier's neuron budget.
_MAX_INPUT_CHARS = 6000

# The screening prompt. The model is given the title, abstract, and a
# truncated body, and asked for a structured JSON report.
# The prompt is explicit that the model is NOT judging scientific quality.
_SCREENING_SYSTEM = """\
You are a submission screener for GenRxiv, a preprint archive for research papers.

Your job is to determine whether a submission LOOKS LIKE a legitimate research paper — not to judge its scientific quality, correctness, or novelty. You are a first-pass filter, not a peer reviewer.

Check for:
1. format_ok: Does it have the structure of a paper? (title, abstract, body text, and ideally sections/references)
2. in_scope: Is it a research-related document? (Not an advertisement, blog rant, resume, code dump, or non-research content)
3. spam_likelihood: Is this spam, promotional content, or nonsense? ("low", "medium", "high")
4. has_abstract: Does it have a meaningful abstract (not empty, not just a title)?
5. has_references: Does it cite any references or have a bibliography?
6. flags: List any specific concerns (e.g. ["no abstract", "appears to be an advertisement", "content is not in English and not a paper"]). Empty list if clean.

Do NOT assess:
- Whether the science is correct
- Whether the methodology is sound
- Whether the results are novel
- The quality of the writing

Respond with ONLY a JSON object, no markdown, no explanation:
{"format_ok": true/false, "in_scope": true/false, "spam_likelihood": "low"/"medium"/"high", "has_abstract": true/false, "has_references": true/false, "flags": ["..."], "summary": "one sentence summary"}"""


def _build_user_message(title: str, abstract: str, markdown: str) -> str:
    """Build the user message with the submission content."""
    # Truncate the markdown body to keep the input small
    body = markdown[:_MAX_INPUT_CHARS]
    if len(markdown) > _MAX_INPUT_CHARS:
        body += "\n\n[... truncated for screening ...]"

    return f"""Title: {title}

Abstract: {abstract}

Submission content (Markdown, may be truncated):
---
{body}
---"""


def _call_cloudflare(model: str, system: str, user: str) -> dict[str, Any] | None:
    """Call Cloudflare Workers AI and return the parsed response, or None on failure."""
    if not config.screening_cf_api_token or not config.screening_cf_account_id:
        logger.warning("Screening enabled but CF_API_TOKEN or CF_ACCOUNT_ID not set")
        return None

    url = CF_AI_BASE.format(
        account_id=config.screening_cf_account_id,
        model=model,  # Keep the @ prefix — the CF API expects it
    )

    headers = {
        "Authorization": f"Bearer {config.screening_cf_api_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        # Low temperature — we want consistent, structured output
        "temperature": 0.1,
        "max_tokens": 500,
    }

    try:
        with httpx.Client(timeout=30) as client:
            r = client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPStatusError as e:
        logger.error("Screening CF API error %s: %s", e.response.status_code, e.response.text[:500])
        return None
    except Exception as e:
        logger.error("Screening CF request failed: %s", e)
        return None

    # CF response: {"result": {"response": "..."}, "success": true, ...}
    # For text-generation models, result["response"] is a string.
    # For some models/configs, the response may already be parsed JSON.
    if not data.get("success"):
        logger.error("Screening CF returned success=false: %s", json.dumps(data)[:500])
        return None

    result = data.get("result", {})
    # The response text is in result["response"] for text-generation models
    text = result.get("response", "")
    if not text:
        logger.error("Screening CF returned empty response")
        return None

    # If the model returned a dict (some models return structured JSON
    # directly), pass it through as-is.
    if isinstance(text, dict):
        return {"text": text}

    return {"text": text}


def _extract_json(text: str | dict) -> dict[str, Any] | None:
    """Extract a JSON object from the model's text response.

    The model is instructed to return only JSON, but small models sometimes
    wrap it in markdown fences or add stray text. We try to find the first
    valid JSON object. If the input is already a dict (some CF models
    return structured JSON directly), pass it through.
    """
    # If already a dict, return as-is
    if isinstance(text, dict):
        return text

    # Strip markdown code fences if present
    text = text.strip()
    if text.startswith("```"):
        # Remove ```json ... ``` or ``` ... ```
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Find the first { ... } block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def _normalize_report(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize the parsed report to ensure all fields exist with correct types."""
    def _bool(key: str) -> bool:
        v = raw.get(key)
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.lower() in ("true", "yes", "1")
        return False

    def _str(key: str, default: str = "low") -> str:
        v = raw.get(key)
        if isinstance(v, str) and v.lower() in ("low", "medium", "high"):
            return v.lower()
        return default

    flags = raw.get("flags", [])
    if not isinstance(flags, list):
        flags = []

    summary = raw.get("summary", "")
    if not isinstance(summary, str):
        summary = str(summary) if summary else ""

    return {
        "format_ok": _bool("format_ok"),
        "in_scope": _bool("in_scope"),
        "spam_likelihood": _str("spam_likelihood"),
        "has_abstract": _bool("has_abstract"),
        "has_references": _bool("has_references"),
        "flags": [str(f) for f in flags],
        "summary": summary,
    }


def is_auto_approvable(report: dict[str, Any]) -> bool:
    """Determine if a screening report is clean enough for auto-approval.

    A submission is auto-approved only if ALL of:
    - format_ok is True
    - in_scope is True
    - spam_likelihood is "low"
    - has_abstract is True
    - flags is empty

    has_references is NOT required for auto-approval — some legitimate
    short papers or notes may not have references.
    """
    return (
        report["format_ok"]
        and report["in_scope"]
        and report["spam_likelihood"] == "low"
        and report["has_abstract"]
        and len(report["flags"]) == 0
    )


def screen_submission(title: str, abstract: str, markdown: str) -> dict[str, Any]:
    """Screen a submission and return a structured report.

    Returns a dict with:
        - verdict: "auto_approve" | "flag_for_review" | "screening_failed"
        - report: the normalized model report (or None if screening failed)
        - model: the model name used
        - error: error message if screening failed

    This function never raises — if the screening API fails, it returns
    "flag_for_review" so the submission goes to the human queue (safe default).
    """
    if not config.screening_enabled:
        return {
            "verdict": "screening_disabled",
            "report": None,
            "model": config.screening_model,
            "error": "Screening not enabled",
        }

    user_msg = _build_user_message(title, abstract, markdown)
    response = _call_cloudflare(config.screening_model, _SCREENING_SYSTEM, user_msg)

    if response is None:
        # Screening failed — fall back to human review (safe default)
        return {
            "verdict": "flag_for_review",
            "report": None,
            "model": config.screening_model,
            "error": "Screening API call failed",
        }

    raw = _extract_json(response["text"])
    if raw is None:
        logger.error("Screening model returned unparseable JSON: %s", response["text"][:300])
        return {
            "verdict": "flag_for_review",
            "report": None,
            "model": config.screening_model,
            "error": "Model returned unparseable JSON",
        }

    report = _normalize_report(raw)
    verdict = "auto_approve" if is_auto_approvable(report) else "flag_for_review"

    return {
        "verdict": verdict,
        "report": report,
        "model": config.screening_model,
        "error": None,
    }


def save_screening_report(article_id: int, result: dict[str, Any]) -> None:
    """Save a screening report to the database."""
    from db import get_conn
    with get_conn().connection() as conn:
        conn.execute(
            """INSERT INTO screening_reports
                   (article_id, model, verdict, report, error)
               VALUES (%s, %s, %s, %s, %s)""",
            (
                article_id,
                result["model"],
                result["verdict"],
                # JSONB column — psycopg3 accepts dicts directly
                json.dumps(result["report"]) if result["report"] else None,
                result.get("error"),
            ),
        )
        conn.commit()


def get_screening_report(article_id: int) -> dict[str, Any] | None:
    """Get the screening report for an article, if one exists."""
    from db import get_conn
    with get_conn().connection() as conn:
        row = conn.execute(
            """SELECT id, article_id, model, verdict, report, error, created_at
               FROM screening_reports WHERE article_id = %s
               ORDER BY created_at DESC LIMIT 1""",
            (article_id,),
        ).fetchone()
    if not row:
        return None
    report = None
    if row["report"]:
        # JSONB columns come back as Python dicts from psycopg3;
        # if it's still a string, parse it.
        if isinstance(row["report"], dict):
            report = row["report"]
        elif isinstance(row["report"], str):
            try:
                report = json.loads(row["report"])
            except (json.JSONDecodeError, TypeError):
                report = None
    return {
        "id": row["id"],
        "article_id": row["article_id"],
        "model": row["model"],
        "verdict": row["verdict"],
        "report": report,
        "error": row["error"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }
