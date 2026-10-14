-- Ticket number on sub-controls, hyperlink on evidence, risk <-> sub-control links.
-- Safe to run more than once.
ALTER TABLE project_subcontrols ADD COLUMN IF NOT EXISTS ticket_number VARCHAR;
ALTER TABLE project_evidence    ADD COLUMN IF NOT EXISTS link VARCHAR;

CREATE TABLE IF NOT EXISTS risk_association (
  id           VARCHAR PRIMARY KEY,
  control_id   VARCHAR REFERENCES project_subcontrols(id) ON DELETE CASCADE,
  risk_id      VARCHAR REFERENCES risk_register(id) ON DELETE CASCADE,
  date_added   TIMESTAMP,
  date_updated TIMESTAMP
);
