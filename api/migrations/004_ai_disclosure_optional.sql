-- Make ai_disclosure optional (nullable)
-- AI involvement is the default on GenRxiv — a separate disclosure field
-- is redundant. The "AI Involvement" section in the paper body is where
-- the real disclosure lives.
-- Use DO block so this is idempotent: if the column doesn't exist (e.g.
-- fresh installs where the schema never included it), this is a no-op.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'articles' AND column_name = 'ai_disclosure'
    ) THEN
        ALTER TABLE articles ALTER COLUMN ai_disclosure DROP NOT NULL;
    END IF;
END $$;
