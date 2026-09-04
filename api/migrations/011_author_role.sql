-- Add role column to authors for DB-based role management.
--
-- Roles: 'author' (default), 'reviewer', 'admin'
-- The env vars (ADMIN_ORCIDS, REVIEWER_ORCIDS, ADMIN_GITHUB_IDS,
-- REVIEWER_GITHUB_IDS) still work as a bootstrap list — they grant the
-- corresponding role at runtime even if the DB role column says 'author'.
-- Admins can then promote other users via the UI, which sets the DB column.
-- This means env vars are the source of truth for bootstrap admins, and the
-- DB is the source of truth for everyone else.

ALTER TABLE authors ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'author';
