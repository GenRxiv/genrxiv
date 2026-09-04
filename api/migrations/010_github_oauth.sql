-- Add GitHub OAuth support for admins/reviewers who don't have an ORCID iD.
--
-- The orcid column becomes nullable (was UNIQUE NOT NULL) so that GitHub-only
-- users can exist without an ORCID. A new github_id column stores the GitHub
-- username. Both columns have UNIQUE constraints so a user can link both
-- identities, but at least one must be present.

-- Make orcid nullable
ALTER TABLE authors ALTER COLUMN orcid DROP NOT NULL;

-- Add github_id column
ALTER TABLE authors ADD COLUMN IF NOT EXISTS github_id TEXT UNIQUE;
