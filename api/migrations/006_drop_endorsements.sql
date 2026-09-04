-- Drop the endorsements table.
-- The endorsement system has been removed in favor of tracking
-- popularity via human and agent download counts.
DROP TABLE IF EXISTS endorsements CASCADE;
