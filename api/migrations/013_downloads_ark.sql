-- Re-key downloads to the work's ARK so counts persist across versions.
-- downloads.article_id is kept for per-version attribution; downloads.ark
-- stores the base ARK of the work so stats aggregate over the whole
-- version chain.

ALTER TABLE downloads ADD COLUMN IF NOT EXISTS ark TEXT;

-- Backfill: resolve each download's article through the supersedes chain
-- to the row holding the work's ARK (superseded versions have ark = NULL).
WITH RECURSIVE chain AS (
    SELECT id AS start_id, id, ark, supersedes_id FROM articles
    UNION
    SELECT c.start_id, a.id, a.ark, a.supersedes_id
    FROM articles a
    JOIN chain c ON c.supersedes_id = a.id OR c.id = a.supersedes_id
)
UPDATE downloads d
SET ark = c.ark
FROM chain c
WHERE c.start_id = d.article_id AND c.ark IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_downloads_ark ON downloads(ark);
