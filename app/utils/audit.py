"""
Security audit logging.

Writes one compact JSON object per line (JSON Lines / NDJSON) to a dedicated
file on disk, separate from the application/debug log. The file is meant to be
picked up by a log shipper (Filebeat, Fluentd, Wazuh agent, ...) and analysed
outside the application - nothing is written to the database.

Design goals
------------
* Sparse: only events that answer "who did what, when, from where, result".
  No request bodies, no secrets, no field *contents* (only field names, plus
  old/new value for a short whitelist of non-sensitive fields such as role,
  status or access level). Updates that touch no tracked field are not logged.
* Truthful: database changes are buffered per transaction and written only
  after the transaction has COMMITTED. A rolled back change is never logged.
* Quiet on bulk work: seeding a framework (hundreds of controls) or a "set all"
  action in one transaction becomes ONE line with a count, not hundreds.
* Multi-worker safe: one file per UTC day (audit-YYYY-MM-DD.log), opened with
  O_APPEND. No renaming, so several gunicorn workers can write at the same time
  without losing lines (the stdlib TimedRotatingFileHandler can drop files when
  more than one process rotates).
* Never breaks the app: every public function swallows its own errors.

Line format (keys with no value are omitted)
--------------------------------------------
{"timestamp": "...Z", "event": "resource_updated", "email": "actor@example.com",
 "result": "success", "ip": "192.0.2.10", "tenant": "ab12cd34",
 "metadata": {"model": "ProjectSubControl", "id": "x1", "label": "AC-2 Account management",
              "project": "ISO 27001", "changed": ["implemented"],
              "values": {"implemented": [0, 1]}, "req": "PUT /api/v1/..."}}

`email` is always the ACTOR (the person/account performing the action). The
account being acted upon, if different, is in metadata ("target").
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone

from flask import has_request_context, request
from flask_login import current_user
from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session, object_session

AUDIT_LOGGER_NAME = "security_audit"

# Events that carry the user agent (authentication related). Resource events
# don't, to keep lines short.
_AUTH_EVENT_PREFIXES = ("login", "logout", "user_registered", "invite", "api_auth")

_state = {
    "models": {},
    "enabled": True,
    "trust_xff": True,
    "session_hooks": False,
    "gui": False,
    "gui_rules": None,
    "gui_retention_days": 90,
    "gui_last_prune": 0.0,
}
_registered = set()


# --------------------------------------------------------------------------- #
# File handler / formatter
# --------------------------------------------------------------------------- #
class JsonLineFormatter(logging.Formatter):
    def format(self, record):
        payload = record.msg if isinstance(record.msg, dict) else {"msg": record.getMessage()}
        return json.dumps(payload, default=str, ensure_ascii=False, separators=(",", ":"))


class DailyFileHandler(logging.Handler):
    """
    Appends to <stem>-YYYY-MM-DD<ext> (UTC date), switching file at midnight.
    Old files are deleted after `retention_days` (0 = keep forever and let the
    SOC/archive own retention). Safe with several processes writing at once.
    """

    def __init__(self, base_path, retention_days=0):
        super().__init__()
        directory, name = os.path.split(os.path.abspath(base_path))
        stem, ext = os.path.splitext(name)
        self._dir = directory
        self._stem = stem
        self._ext = ext or ".log"
        self._retention = int(retention_days or 0)
        self._day = None
        self._stream = None
        self._name_re = re.compile(
            r"^%s-(\d{4}-\d{2}-\d{2})%s$" % (re.escape(self._stem), re.escape(self._ext))
        )

    def path_for(self, day):
        return os.path.join(self._dir, "%s-%s%s" % (self._stem, day, self._ext))

    def emit(self, record):
        try:
            day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if day != self._day or self._stream is None:
                self._switch(day)
            self._stream.write(self.format(record) + "\n")
            self._stream.flush()
        except Exception:
            self.handleError(record)

    def _switch(self, day):
        if self._stream:
            try:
                self._stream.close()
            except Exception:
                pass
        fd = os.open(self.path_for(day), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o640)
        self._stream = os.fdopen(fd, "a", encoding="utf-8")
        self._day = day
        self._prune(day)

    def _prune(self, today):
        if self._retention <= 0:
            return
        cutoff = (
            datetime.strptime(today, "%Y-%m-%d") - timedelta(days=self._retention)
        ).strftime("%Y-%m-%d")
        try:
            for fname in os.listdir(self._dir):
                m = self._name_re.match(fname)
                if m and m.group(1) < cutoff:
                    try:
                        os.remove(os.path.join(self._dir, fname))
                    except OSError:
                        pass
        except OSError:
            pass

    def close(self):
        try:
            if self._stream:
                self._stream.close()
        finally:
            self._stream = None
            super().close()


def configure_audit_logger(app):
    """
    Call once from create_app() AFTER the models/extensions are configured.

    Config (all optional):
      AUDIT_LOG_ENABLED            default True
      AUDIT_LOG_PATH               default /var/log/app/audit.log  (becomes audit-<date>.log)
      AUDIT_LOG_RETENTION_DAYS     default 90, 0 = never delete locally
      AUDIT_TRUST_FORWARDED_FOR    default True - use first X-Forwarded-For hop as client ip
      AUDIT_GUI_ENABLED            default True - also show important events in the GUI Logs page
      AUDIT_GUI_EVENTS             comma list overriding DEFAULT_GUI_EVENTS ("event" or "event:Model")
      AUDIT_GUI_RETENTION_DAYS     default 90, 0 = never prune the GUI copy
    """
    _state["enabled"] = bool(app.config.get("AUDIT_LOG_ENABLED", True))
    _state["trust_xff"] = bool(app.config.get("AUDIT_TRUST_FORWARDED_FOR", True))
    _state["gui"] = bool(app.config.get("AUDIT_GUI_ENABLED", True))
    _state["gui_rules"] = _parse_gui_rules(app.config.get("AUDIT_GUI_EVENTS"))
    _state["gui_retention_days"] = int(app.config.get("AUDIT_GUI_RETENTION_DAYS", 90) or 0)
    if not _state["enabled"]:
        return

    log_path = app.config.get("AUDIT_LOG_PATH") or "/var/log/app/audit.log"
    retention = int(app.config.get("AUDIT_LOG_RETENTION_DAYS", 90) or 0)

    try:
        os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
        if not os.access(os.path.dirname(os.path.abspath(log_path)), os.W_OK):
            raise PermissionError(log_path)
    except OSError:
        fallback = os.path.join(os.path.dirname(app.root_path), "logs", "audit.log")
        app.logger.warning(
            "Audit log path %s is not writable - falling back to %s", log_path, fallback
        )
        log_path = fallback
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

    audit_logger = logging.getLogger(AUDIT_LOGGER_NAME)
    audit_logger.setLevel(logging.INFO)
    audit_logger.propagate = False  # never bleed into the app/stdout log

    # Idempotent: reloader / repeated create_app() must not duplicate handlers
    if not any(isinstance(h, DailyFileHandler) for h in audit_logger.handlers):
        handler = DailyFileHandler(log_path, retention_days=retention)
        handler.setFormatter(JsonLineFormatter())
        audit_logger.addHandler(handler)

    app.audit_logger = audit_logger

    _state["models"] = dict(getattr(app, "models", {}) or {})
    _install_session_hooks()
    register_models()


# --------------------------------------------------------------------------- #
# Direct event API
# --------------------------------------------------------------------------- #
def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _actor_email():
    """Who is acting. 'system' outside a request (CLI/seed), None if anonymous."""
    if not has_request_context():
        return "system"
    try:
        if current_user and current_user.is_authenticated:
            return current_user.email
    except Exception:
        pass
    return None


def current_actor(default=None):
    """Public helper: e-mail of the logged in user, else `default`."""
    actor = _actor_email()
    return actor if actor and actor != "system" else (default or actor)


def _client():
    """(ip, peer) - peer only when it differs from ip (i.e. behind a proxy)."""
    peer = request.remote_addr
    if _state["trust_xff"]:
        xff = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if xff and xff != peer:
            return xff, peer
    return peer, None


def _clean(d):
    return {k: v for k, v in d.items() if v not in (None, "", [], {})}


def _emit(payload):
    logger = logging.getLogger(AUDIT_LOGGER_NAME)
    if logger.handlers:
        logger.info(payload)


def log_event(
    event_name,
    email=None,
    provider=None,
    result="success",
    metadata=None,
    tenant=None,
):
    """
    Record one security relevant event.

    event_name  short machine name: login_success, login_failed, logout,
                user_registered, invite_accepted, password_changed, ...
    email       the actor. Defaults to the logged in user ("system" outside a request).
    provider    local | google | microsoft
    result      success | failure | error
    metadata    small dict of non-sensitive context. NEVER passwords/tokens/claims.
    tenant      tenant id, when relevant.
    """
    if not _state["enabled"]:
        return
    try:
        payload = {
            "timestamp": _now(),
            "event": event_name,
            "email": email or _actor_email(),
            "provider": provider,
            "result": result,
            "tenant": tenant,
        }
        if has_request_context():
            ip, peer = _client()
            payload["ip"] = ip
            payload["peer"] = peer
            if event_name.startswith(_AUTH_EVENT_PREFIXES):
                payload["user_agent"] = request.headers.get("User-Agent")
            elif metadata and "model" in metadata:
                metadata = dict(metadata)
                metadata["req"] = "%s %s" % (request.method, request.path)
        payload["metadata"] = _clean(metadata) if isinstance(metadata, dict) else metadata
        payload = _clean(payload)
        _emit(payload)
        _to_gui(payload)
    except Exception:
        # logging must never break a request
        logging.getLogger(__name__).debug("audit log_event failed", exc_info=True)


# --------------------------------------------------------------------------- #
# GUI copy - a small, important subset of events is also written to the `logs`
# table so it shows up on the Logs page. The JSON file stays the complete record;
# this copy is a convenience and is never allowed to break a request.
# --------------------------------------------------------------------------- #
DEFAULT_GUI_EVENTS = (
    "login_success,logout,login_failed,login_blocked,access_denied,api_auth_failed,invite_accept_failed,"
    "user_registered,invite_accepted,"
    "password_changed,password_reset_requested,password_reset_completed,password_reset_failed,"
    "member_roles_changed,project_member_removed,api_token_issued,frameworks_reloaded,"
    "risk_reminder_sent,risk_reminder_failed,"
    "resource_deleted:Project,resources_deleted:Project,"
    "resource_deleted:ProjectEvidence,resources_deleted:ProjectEvidence,"
    "resource_deleted:RiskRegister,resources_deleted:RiskRegister,"
    "resource_deleted:Tenant,resource_deleted:User,"
    "resource_deleted:Framework,resource_deleted:Policy"
)

_WARN_EVENTS = {"access_denied", "login_blocked", "login_failed", "api_auth_failed"}


def _parse_gui_rules(value):
    """-> (set of event names, set of (event, model)) or None when nothing is configured."""
    raw = value if value not in (None, "") else DEFAULT_GUI_EVENTS
    names, pairs = set(), set()
    for item in str(raw).split(","):
        item = item.strip()
        if not item:
            continue
        if ":" in item:
            ev, model = item.split(":", 1)
            pairs.add((ev.strip(), model.strip()))
        else:
            names.add(item)
    return names, pairs


def _gui_wanted(payload):
    rules = _state.get("gui_rules")
    if not _state.get("gui") or not rules:
        return False
    names, pairs = rules
    event_name = payload.get("event")
    if event_name in names:
        return True
    model = (payload.get("metadata") or {}).get("model")
    return (event_name, model) in pairs


def _gui_message(payload):
    meta = payload.get("metadata") or {}
    text = (payload.get("event") or "event").replace("_", " ")
    actor = payload.get("email")
    parts = [text]
    if meta.get("model"):
        parts.append(str(meta["model"]))
    if meta.get("count"):
        parts.append("x%s" % meta["count"])
    label = meta.get("label") or meta.get("example") or meta.get("target")
    if label:
        parts.append("'%s'" % label)
    for key in ("provider", "reason", "roles", "role", "changed"):
        if meta.get(key):
            parts.append("%s=%s" % (key, meta[key]))
    msg = " ".join(parts)
    if actor:
        msg += " (by %s)" % actor
    if payload.get("ip"):
        msg += " from %s" % payload["ip"]
    return msg[:500]


def _gui_prune(connection, table):
    """Drop GUI copies older than the retention period (at most once an hour per process)."""
    days = _state.get("gui_retention_days") or 0
    now = time.time()
    if not days or now - _state.get("gui_last_prune", 0.0) < 3600:
        return
    _state["gui_last_prune"] = now
    cutoff = datetime.utcnow() - timedelta(days=days)
    connection.execute(
        table.delete().where(table.c.namespace == "audit").where(table.c.date_added < cutoff)
    )


def _to_gui(payload):
    """Write one row to `logs` on its own connection (independent of the request session)."""
    try:
        if not _gui_wanted(payload):
            return
        from app import db  # late import: audit.py is imported by app/__init__

        Logs = _state["models"].get("Logs")
        User = _state["models"].get("User")
        Tenant = _state["models"].get("Tenant")
        if Logs is None:
            return
        failed = payload.get("result", "success") != "success"
        level = "WARNING" if failed or payload.get("event") in _WARN_EVENTS else "INFO"
        meta = {k: v for k, v in payload.items() if k not in ("timestamp",)}
        meta["time"] = payload.get("timestamp")
        with db.engine.begin() as conn:
            # Foreign keys must point at committed rows; otherwise leave them empty.
            user_id = tenant_id = None
            if User is not None and payload.get("email"):
                user_id = conn.execute(
                    _select([User.__table__.c.id]).where(
                        User.__table__.c.email == payload["email"]
                    )
                ).scalar()
            if Tenant is not None and payload.get("tenant"):
                tenant_id = conn.execute(
                    _select([Tenant.__table__.c.id]).where(
                        Tenant.__table__.c.id == payload["tenant"]
                    )
                ).scalar()
            conn.execute(
                Logs.__table__.insert().values(
                    namespace="audit",
                    level=level,
                    action="AUDIT",
                    message=_gui_message(payload),
                    success=not failed,
                    meta=json.loads(json.dumps(meta, default=str)),
                    user_id=user_id,
                    tenant_id=tenant_id,
                )
            )
            _gui_prune(conn, Logs.__table__)
    except Exception:
        logging.getLogger(__name__).debug("audit GUI copy failed", exc_info=True)


# --------------------------------------------------------------------------- #
# Label helpers - human readable names so a line is useful without a DB lookup
# --------------------------------------------------------------------------- #
def _select(columns):
    try:
        return select(columns)  # SQLAlchemy 1.3 / 1.4
    except Exception:
        return select(*columns)  # 2.x


def _row(connection, model_name, pk, *cols):
    """One row via the flush connection (never touches the ORM session)."""
    model = _state["models"].get(model_name)
    if not model or not pk:
        return None
    try:
        t = model.__table__
        return connection.execute(
            _select([t.c[c] for c in cols]).where(t.c.id == pk)
        ).first()
    except Exception:
        return None


def _text(connection, model_name, pk, *cols):
    row = _row(connection, model_name, pk, *cols)
    if not row:
        return None
    parts = [str(v) for v in row if v not in (None, "")]
    return " ".join(parts) or None


def _label_field(field):
    return lambda c, d: (d.get(field), {})


def _label_project_child(field, with_project=True):
    def fn(c, d):
        extra = {}
        if with_project and d.get("project_id"):
            extra["project"] = _text(c, "Project", d["project_id"], "name")
        return d.get(field), extra

    return fn


def _label_project_control(c, d):
    return (
        _text(c, "Control", d.get("control_id"), "ref_code", "name"),
        {"project": _text(c, "Project", d.get("project_id"), "name")},
    )


def _label_project_subcontrol(c, d):
    return (
        _text(c, "SubControl", d.get("subcontrol_id"), "ref_code", "name"),
        {"project": _text(c, "Project", d.get("project_id"), "name")},
    )


def _label_subcontrol(c, d):
    return " ".join(x for x in (d.get("ref_code"), d.get("name")) if x) or None, {}


def _label_project_member(c, d):
    return (
        _text(c, "User", d.get("user_id"), "email"),
        {
            "project": _text(c, "Project", d.get("project_id"), "name"),
            "access": d.get("access_level"),
        },
    )


def _label_tenant_member(c, d):
    return (
        _text(c, "User", d.get("user_id"), "email"),
        {"tenant": _text(c, "Tenant", d.get("tenant_id"), "name")},
    )


def _label_policy_version(c, d):
    name = _text(c, "ProjectPolicy", d.get("policy_id"), "name")
    return ("%s v%s" % (name, d.get("version")) if name else None), {}


def _subcontrol_via_project_subcontrol(c, psc_id):
    sid = _text(c, "ProjectSubControl", psc_id, "subcontrol_id")
    return _text(c, "SubControl", sid, "ref_code", "name")


def _label_evidence_link(c, d):
    ev = _text(c, "ProjectEvidence", d.get("evidence_id"), "name")
    sc = _subcontrol_via_project_subcontrol(c, d.get("control_id"))
    pid = _text(c, "ProjectSubControl", d.get("control_id"), "project_id")
    return "evidence '%s' <-> %s" % (ev, sc), {"project": _text(c, "Project", pid, "name")}


def _label_risk_link(c, d):
    risk = _text(c, "RiskRegister", d.get("risk_id"), "title")
    sc = _subcontrol_via_project_subcontrol(c, d.get("control_id"))
    pid = _text(c, "ProjectSubControl", d.get("control_id"), "project_id")
    return "risk '%s' <-> %s" % (risk, sc), {"project": _text(c, "Project", pid, "name")}


def _label_comment_project(c, d):
    return "comment on " + (_text(c, "Project", d.get("project_id"), "name") or "?"), {}


def _label_comment_risk(c, d):
    return "comment on " + (_text(c, "RiskRegister", d.get("risk_id"), "title") or "?"), {}


def _label_comment_control(c, d):
    cid = _text(c, "ProjectControl", d.get("control_id"), "control_id")
    return "comment on " + (_text(c, "Control", cid, "ref_code", "name") or "?"), {}


def _label_comment_subcontrol(c, d):
    sid = _text(c, "ProjectSubControl", d.get("subcontrol_id"), "subcontrol_id")
    return "comment on " + (_text(c, "SubControl", sid, "ref_code", "name") or "?"), {}


# Fields that hold a user id: show the e-mail address instead of the id
_USER_REF_FIELDS = {"owner_id", "operator_id", "assignee", "reviewer_id"}


# --------------------------------------------------------------------------- #
# What is audited
#   fields : changes to these are logged by NAME on update
#   values : subset of `fields` whose old -> new value is also logged. Only
#            non-sensitive, short fields belong here.
#   bulk   : many rows in one transaction collapse into one summary line
#   create / delete : log inserts / deletes (default True)
# --------------------------------------------------------------------------- #
AUDIT_SPECS = {
    "User": dict(
        label=_label_field("email"),
        fields=[
            "email", "first_name", "last_name", "username", "is_active", "super",
            "can_user_create_tenant", "tenant_limit", "license",
        ],
        values=["is_active", "super", "can_user_create_tenant", "tenant_limit", "license"],
    ),
    "Tenant": dict(
        label=_label_field("name"),
        fields=[
            "name", "contact_email", "license", "is_default", "approved_domains",
            "magic_link_login", "ai_enabled", "user_cap", "project_cap",
            "storage_cap", "owner_id",
        ],
        values=[
            "license", "is_default", "approved_domains", "magic_link_login",
            "ai_enabled", "user_cap", "project_cap", "owner_id",
        ],
    ),
    "TenantMember": dict(label=_label_tenant_member, fields=[], bulk=False),
    "Role": dict(label=_label_field("name"), fields=["name", "label"], values=["name"]),
    "ConfigStore": dict(label=_label_field("key"), fields=["value"]),
    "Project": dict(
        label=_label_field("name"),
        fields=[
            "name", "description", "notes", "target_level", "owner_id", "framework_id",
            "format", "auditor_enabled", "can_auditor_read_scratchpad",
            "can_auditor_write_scratchpad", "can_auditor_read_comments",
            "can_auditor_write_comments", "policies_require_cc",
        ],
        values=[
            "target_level", "owner_id", "auditor_enabled", "can_auditor_read_scratchpad",
            "can_auditor_write_scratchpad", "can_auditor_read_comments",
            "can_auditor_write_comments", "policies_require_cc",
        ],
    ),
    "ProjectMember": dict(
        label=_label_project_member, fields=["access_level"], values=["access_level"],
        bulk_delete=False,
    ),
    "Framework": dict(
        label=_label_field("name"), fields=["name", "description"], bulk=True
    ),
    "Control": dict(
        label=_label_subcontrol,
        fields=["name", "description", "ref_code", "visible", "level",
                "operational_capability", "control_type"],
        values=["visible", "level", "control_type"],
        bulk=True,
    ),
    "SubControl": dict(
        label=_label_subcontrol,
        fields=["name", "description", "ref_code", "mitigation"],
        bulk=True,
    ),
    "ProjectControl": dict(
        label=_label_project_control,
        fields=["review_status", "notes", "auditor_notes"],
        values=["review_status"],
        bulk=True,
    ),
    "ProjectSubControl": dict(
        label=_label_project_subcontrol,
        fields=[
            "implemented", "is_applicable", "process_maturity", "owner_id", "operator_id",
            "ticket_number", "context", "notes", "auditor_feedback",
        ],
        values=["implemented", "is_applicable", "process_maturity", "owner_id",
                "operator_id", "ticket_number"],
        bulk=True,
    ),
    "ProjectEvidence": dict(
        label=_label_project_child("name"),
        fields=["name", "description", "content", "link", "group", "file_name", "owner_id"],
        values=["link", "owner_id"],
        bulk=True,
    ),
    "RiskRegister": dict(
        label=_label_project_child("title"),
        fields=[
            "title", "description", "remediation", "enabled", "risk", "status",
            "priority", "assignee", "project_id", "vendor_id",
        ],
        values=["enabled", "risk", "status", "priority", "assignee"],
    ),
    "AuditorFeedback": dict(
        label=_label_field("title"), fields=["is_complete"], values=["is_complete"],
    ),
    "ProjectPolicy": dict(
        label=_label_project_child("name"),
        fields=["name", "description", "ref_code", "visible", "owner_id", "reviewer_id"],
        values=["visible", "owner_id", "reviewer_id"],
    ),
    "PolicyVersion": dict(
        label=_label_policy_version, fields=["status", "published"],
        values=["status", "published"], create=False, delete=False,
    ),
    "Policy": dict(label=_label_field("name"), fields=["name", "description", "ref_code"]),
    # Evidence / risk links on a sub-control (rows added/removed = linked/unlinked)
    "EvidenceAssociation": dict(label=_label_evidence_link, fields=[], bulk=True),
    "RiskAssociation": dict(label=_label_risk_link, fields=[], bulk=True),
    "ProjectComment": dict(label=_label_comment_project, fields=[]),
    "RiskComment": dict(label=_label_comment_risk, fields=[]),
    "ControlComment": dict(label=_label_comment_control, fields=[]),
    "SubControlComment": dict(label=_label_comment_subcontrol, fields=[]),
    "Vendor": dict(
        label=_label_field("name"),
        fields=["name", "status", "review_status", "criticality", "disabled"],
        values=["status", "review_status", "criticality", "disabled"],
    ),
    "VendorApp": dict(
        label=_label_field("name"),
        fields=["name", "status", "review_status", "criticality", "disabled"],
        values=["status", "review_status", "criticality", "disabled"],
    ),
    "Assessment": dict(
        label=_label_field("name"),
        fields=["name", "status", "review_status", "disabled", "reviewer_id"],
        values=["status", "review_status", "disabled", "reviewer_id"],
    ),
}
# Written explicitly where the change is made, because they go through a secondary
# table or a bulk Query.delete() that bypass ORM events (see models.py):
#   member_roles_changed      Tenant.patch_roles_for_member / add_ / remove_role_for_member
#   project_member_removed    Project.remove_member / Tenant.remove_user_from_projects


# --------------------------------------------------------------------------- #
# Transaction-aware ORM hooks
# --------------------------------------------------------------------------- #
def _snapshot(target):
    """Loaded column values without triggering any lazy load / SQL."""
    state = inspect(target)
    return {k: state.dict.get(k) for k in state.mapper.column_attrs.keys()}


def _short(value, field=None, connection=None):
    if field in _USER_REF_FIELDS and value and connection is not None:
        return _text(connection, "User", value, "email") or value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    value = str(value)
    return value if len(value) <= 100 else value[:97] + "..."


def _pending(session):
    return session.info.setdefault("_audit_pending", [])


def _queue(target, connection, spec, model_name, event_name, changed=None, values=None):
    session = object_session(target)
    snap = _snapshot(target)
    try:
        label, extra = spec["label"](connection, snap)
    except Exception:
        label, extra = snap.get("name") or snap.get("email") or snap.get("title"), {}

    meta = {"model": model_name, "id": snap.get("id"), "label": label}
    meta.update({k: v for k, v in (extra or {}).items() if v})
    if changed:
        meta["changed"] = changed
    if values:
        meta["values"] = values

    entry = {
        "event": event_name,
        "model": model_name,
        "actor": _actor_email(),
        "tenant": snap.get("tenant_id") or (snap.get("id") if model_name == "Tenant" else None),
        "meta": meta,
        "bulk": bool(spec.get("bulk")),
        "key": (event_name, model_name, snap.get("id"), tuple(changed or ())),
    }
    if session is None:  # detached - cannot wait for a commit
        _write_entries([entry])
        return
    pending = _pending(session)
    if any(p["key"] == entry["key"] and p["meta"].get("values") == entry["meta"].get("values")
           for p in pending):
        return  # same change flushed twice in one transaction
    pending.append(entry)


def _write_entries(entries):
    """Collapse bulk entries (one line + count), write the rest as they are."""
    groups = {}
    for e in entries:
        if not e["bulk"]:
            _log_resource(e)
            continue
        gkey = (e["event"], e["model"], e["actor"], tuple(e["meta"].get("changed", ())))
        groups.setdefault(gkey, []).append(e)
    for items in groups.values():
        if len(items) == 1:
            _log_resource(items[0])
            continue
        first = items[0]
        meta = {
            "model": first["model"],
            "count": len(items),
            "example": first["meta"].get("label"),
        }
        for k in ("project", "changed"):
            if first["meta"].get(k):
                meta[k] = first["meta"][k]
        # plural event name marks a collapsed line, e.g. resources_created
        log_event(
            first["event"].replace("resource_", "resources_"),
            email=first["actor"],
            tenant=first["tenant"],
            metadata=meta,
        )


def _log_resource(e):
    log_event(e["event"], email=e["actor"], tenant=e["tenant"], metadata=e["meta"])


def _on_commit(session):
    try:
        entries = session.info.pop("_audit_pending", None)
        if entries:
            _write_entries(entries)
    except Exception:
        logging.getLogger(__name__).debug("audit commit flush failed", exc_info=True)


def _on_rollback(session):
    session.info.pop("_audit_pending", None)


def _on_bulk_delete(ctx):
    """Query.delete() bypasses mapper events - catch it for registered models."""
    try:
        entity = ctx.query.column_descriptions[0]["entity"]
        name = getattr(entity, "__name__", None)
        spec = AUDIT_SPECS.get(name)
        if not spec or not spec.get("delete", True) or spec.get("bulk_delete") is False:
            return
        count = getattr(ctx.result, "rowcount", None)
        if not count:
            return
        _pending(ctx.session).append(
            {
                "event": "resource_deleted",
                "model": name,
                "actor": _actor_email(),
                "tenant": None,
                "meta": {"model": name, "count": count, "bulk_query": True},
                "bulk": False,
                "key": ("bulk_delete", name, id(ctx), ()),
            }
        )
    except Exception:
        logging.getLogger(__name__).debug("audit bulk delete hook failed", exc_info=True)


def _install_session_hooks():
    if _state["session_hooks"]:
        return
    event.listen(Session, "after_commit", _on_commit)
    event.listen(Session, "after_rollback", _on_rollback)
    event.listen(Session, "after_bulk_delete", _on_bulk_delete)
    _state["session_hooks"] = True


def register_audit_events(
    model,
    tracked_fields=None,
    label_field=None,
    spec=None,
):
    """
    Register one model. Normally you don't call this - add it to AUDIT_SPECS.
    Kept for backwards compatibility: register_audit_events(Model, tracked_fields=[...]).
    """
    if model in _registered:
        return
    _registered.add(model)
    name = model.__name__
    spec = dict(spec or {})
    spec.setdefault("fields", list(tracked_fields or []))
    spec.setdefault("values", [])
    spec.setdefault(
        "label", _label_field(label_field) if label_field else _label_field("name")
    )
    fields = spec["fields"]
    values = set(spec["values"])

    def after_insert(mapper, connection, target):
        try:
            _queue(target, connection, spec, name, "resource_created")
        except Exception:
            logging.getLogger(__name__).debug("audit insert hook failed", exc_info=True)

    def after_delete(mapper, connection, target):
        try:
            _queue(target, connection, spec, name, "resource_deleted")
        except Exception:
            logging.getLogger(__name__).debug("audit delete hook failed", exc_info=True)

    def after_update(mapper, connection, target):
        try:
            if not fields:
                return
            state = inspect(target)
            mapped = {c.key for c in state.mapper.column_attrs}
            changed, changed_values = [], {}
            for field in fields:
                if field not in mapped:
                    continue
                hist = state.attrs[field].history
                if not hist.has_changes():
                    continue
                changed.append(field)
                if field in values:
                    old = hist.deleted[0] if hist.deleted else None
                    new = hist.added[0] if hist.added else None
                    changed_values[field] = [
                        _short(old, field, connection),
                        _short(new, field, connection),
                    ]
            if not changed:
                return  # nothing we track changed - stay quiet
            _queue(target, connection, spec, name, "resource_updated",
                   changed=changed, values=changed_values)
        except Exception:
            logging.getLogger(__name__).debug("audit update hook failed", exc_info=True)

    if spec.get("create", True):
        event.listen(model, "after_insert", after_insert)
    if spec.get("delete", True):
        event.listen(model, "after_delete", after_delete)
    if fields:
        event.listen(model, "after_update", after_update)


def register_models():
    for name, spec in AUDIT_SPECS.items():
        model = _state["models"].get(name)
        if model is None:
            continue
        register_audit_events(model, spec=spec)
