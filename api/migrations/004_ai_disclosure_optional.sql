-- Make ai_disclosure optional (nullable)
-- AI involvement is the default on GenRxiv — a separate disclosure field
-- is redundant. The "AI Involvement" section in the paper body is where
-- the real disclosure lives.
ALTER TABLE articles ALTER COLUMN ai_disclosure DROP NOT NULL;
