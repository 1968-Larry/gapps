-- Reminder emails that have been sent for risk review / due dates.
-- Safe to run more than once.
CREATE TABLE IF NOT EXISTS risk_reminders (
  id          VARCHAR PRIMARY KEY,
  risk_id     VARCHAR NOT NULL REFERENCES risk_register(id) ON DELETE CASCADE,
  kind        VARCHAR NOT NULL,
  target_date DATE NOT NULL,
  sent_on     DATE NOT NULL,
  recipients  VARCHAR,
  date_added  TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_risk_reminders_risk_id ON risk_reminders(risk_id);
