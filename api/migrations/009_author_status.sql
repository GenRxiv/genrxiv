-- Author account status for Code of Conduct enforcement.
--
-- Allows administrators to suspend or ban authors who violate the CoC.
-- Suspended authors cannot submit new papers but existing work is preserved.
-- Banned authors are blocked entirely (cannot log in).
--
-- Values: 'active' (default), 'suspended', 'banned'

ALTER TABLE authors ADD COLUMN IF NOT EXISTS account_status TEXT NOT NULL DEFAULT 'active';
ALTER TABLE authors ADD COLUMN IF NOT EXISTS status_reason TEXT;
ALTER TABLE authors ADD COLUMN IF NOT EXISTS status_changed_at TIMESTAMPTZ;
ALTER TABLE authors ADD COLUMN IF NOT EXISTS status_changed_by INTEGER REFERENCES authors(id);

-- Backfill existing authors
UPDATE authors SET account_status = 'active' WHERE account_status IS NULL OR account_status = '';
