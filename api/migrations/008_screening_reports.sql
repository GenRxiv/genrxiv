-- Add screening_reports table for automated submission screening.
--
-- When a submission passes structural validation, it is sent to a small
-- language model (Cloudflare Workers AI) for a first-pass screening:
-- "does this look like a research paper?" The model produces a structured
-- JSON report. Clean submissions are auto-published; flagged submissions
-- stay pending for human review. The model never auto-rejects.
--
-- This table stores the screening result for audit and admin visibility.
CREATE TABLE IF NOT EXISTS screening_reports (
    id SERIAL PRIMARY KEY,
    article_id INTEGER REFERENCES articles(id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    verdict TEXT NOT NULL,
    report JSONB,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_screening_reports_article_id ON screening_reports(article_id);
