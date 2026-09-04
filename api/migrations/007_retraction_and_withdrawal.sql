-- Add support for author retractions and admin withdrawals.
--
-- is_retraction: marks a version as a retraction notice (a new version that
--   retracts a previously published article). Retractions go through the
--   normal moderation pipeline; on approval the ARK transfers to the
--   retraction version and the original is marked superseded.
--
-- withdrawn_at / withdrawal_reason: recorded when an admin withdraws a
--   published article (e.g. in response to a DMCA/DSA takedown notice or a
--   research-integrity finding). The ARK persists and resolves to a tombstone
--   page; the content is no longer served. The reason is kept for audit.
ALTER TABLE articles ADD COLUMN IF NOT EXISTS is_retraction BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE articles ADD COLUMN IF NOT EXISTS withdrawn_at TIMESTAMPTZ;
ALTER TABLE articles ADD COLUMN IF NOT EXISTS withdrawal_reason TEXT;
