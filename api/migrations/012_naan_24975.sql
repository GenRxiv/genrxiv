-- Transition from the placeholder NAAN (99999, reserved for examples/testing)
-- to the assigned NAAN (24975) issued by the ARK Alliance.
--
-- Existing ARKs are rewritten in place — the name portion is unchanged, so
-- ark:99999/genrxiv-2026-00001 becomes ark:24975/genrxiv-2026-00001. The API
-- redirects requests for the old placeholder NAAN to the canonical ARK.

UPDATE articles
SET ark = REPLACE(ark, 'ark:99999/', 'ark:24975/')
WHERE ark LIKE 'ark:99999/%';

-- Rendered HTML/PDF cache embeds the ARK in the document header. Clear the
-- cached paths so files are re-rendered lazily with the new ARK.
UPDATE articles SET html_path = NULL WHERE html_path IS NOT NULL;
UPDATE articles SET pdf_path = NULL WHERE pdf_path IS NOT NULL;
