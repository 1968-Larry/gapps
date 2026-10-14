-- 4x4 risk assessment (likelihood x impact) and ticket number on risks.
-- Safe to run more than once.
ALTER TABLE risk_register
  ADD COLUMN IF NOT EXISTS likelihood    INTEGER,
  ADD COLUMN IF NOT EXISTS impact        INTEGER,
  ADD COLUMN IF NOT EXISTS ticket_number VARCHAR;
