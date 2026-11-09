-- Exceptions (deviations from a control / policy / hardening requirement) with
-- approval, history, comments, expiry reminders and links to sub-controls and risks.
-- The same tables are created automatically by tools/apply_schema_updates.py.
-- Safe to run more than once.
CREATE TABLE IF NOT EXISTS policy_exceptions (
  id                    VARCHAR PRIMARY KEY,
  title                 VARCHAR NOT NULL,
  description           VARCHAR,
  justification         VARCHAR,
  compensating_controls VARCHAR,
  affected_assets       VARCHAR,
  risk                  VARCHAR NOT NULL DEFAULT 'unknown',
  likelihood            INTEGER,
  impact                INTEGER,
  status                VARCHAR NOT NULL DEFAULT 'draft',
  ticket_number         VARCHAR,
  assignee              VARCHAR REFERENCES users(id),
  requested_by          VARCHAR REFERENCES users(id),
  submitted_date        DATE,
  decided_by            VARCHAR REFERENCES users(id),
  decided_date          DATE,
  decision_note         VARCHAR,
  valid_from            DATE,
  expiry_date           DATE,
  closed_date           DATE,
  project_id            VARCHAR REFERENCES projects(id),
  tenant_id             VARCHAR NOT NULL REFERENCES tenants(id),
  date_added            TIMESTAMP,
  date_updated          TIMESTAMP
);

CREATE TABLE IF NOT EXISTS exception_association (
  id           VARCHAR PRIMARY KEY,
  control_id   VARCHAR REFERENCES project_subcontrols(id) ON DELETE CASCADE,
  exception_id VARCHAR REFERENCES policy_exceptions(id) ON DELETE CASCADE,
  date_added   TIMESTAMP,
  date_updated TIMESTAMP
);

CREATE TABLE IF NOT EXISTS exception_risk_association (
  id           VARCHAR PRIMARY KEY,
  exception_id VARCHAR REFERENCES policy_exceptions(id) ON DELETE CASCADE,
  risk_id      VARCHAR REFERENCES risk_register(id) ON DELETE CASCADE,
  date_added   TIMESTAMP
);

CREATE TABLE IF NOT EXISTS exception_comments (
  id           VARCHAR PRIMARY KEY,
  message      VARCHAR,
  owner_id     VARCHAR NOT NULL REFERENCES users(id),
  exception_id VARCHAR NOT NULL REFERENCES policy_exceptions(id),
  tenant_id    VARCHAR NOT NULL REFERENCES tenants(id),
  date_added   TIMESTAMP,
  date_updated TIMESTAMP
);

CREATE TABLE IF NOT EXISTS exception_history (
  id           VARCHAR PRIMARY KEY,
  exception_id VARCHAR NOT NULL REFERENCES policy_exceptions(id) ON DELETE CASCADE,
  event        VARCHAR NOT NULL,
  changes      JSON,
  snapshot     JSON,
  note         VARCHAR,
  user_id      VARCHAR,
  user_email   VARCHAR,
  date_added   TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_exception_history_exception_id ON exception_history(exception_id);

CREATE TABLE IF NOT EXISTS exception_reminders (
  id           VARCHAR PRIMARY KEY,
  exception_id VARCHAR NOT NULL REFERENCES policy_exceptions(id) ON DELETE CASCADE,
  kind         VARCHAR NOT NULL,
  target_date  DATE NOT NULL,
  sent_on      DATE NOT NULL,
  recipients   VARCHAR,
  date_added   TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_exception_reminders_exception_id ON exception_reminders(exception_id);
