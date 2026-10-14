-- Review / due / completed dates on risks and the change history table.
-- Safe to run more than once.
ALTER TABLE risk_register
  ADD COLUMN IF NOT EXISTS review_date   DATE,
  ADD COLUMN IF NOT EXISTS due_date      DATE,
  ADD COLUMN IF NOT EXISTS closed_date   DATE,
  ADD COLUMN IF NOT EXISTS last_reviewed DATE;

CREATE TABLE IF NOT EXISTS risk_history (
  id         VARCHAR PRIMARY KEY,
  risk_id    VARCHAR NOT NULL REFERENCES risk_register(id) ON DELETE CASCADE,
  event      VARCHAR NOT NULL,
  changes    JSON,
  snapshot   JSON,
  note       VARCHAR,
  user_id    VARCHAR,
  user_email VARCHAR,
  date_added TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_risk_history_risk_id ON risk_history(risk_id);
