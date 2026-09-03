-- Migration 003: Rename keywords column to subjects
-- The column stores OECD FOS subject classifications, not free-text keywords.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'articles' AND column_name = 'keywords')
       AND NOT EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'articles' AND column_name = 'subjects') THEN
        ALTER TABLE articles RENAME COLUMN keywords TO subjects;
    END IF;
END$$;
