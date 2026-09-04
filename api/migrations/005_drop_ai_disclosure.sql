-- Drop the ai_disclosure column entirely
-- AI involvement is the default on GenRxiv — there are no articles yet,
-- so we drop the column rather than keeping it for backward compat.
-- The submission form's "reviewed" checkbox is the confirmation;
-- every article page shows a standard AI-generated banner in the header.
ALTER TABLE articles DROP COLUMN IF EXISTS ai_disclosure;
