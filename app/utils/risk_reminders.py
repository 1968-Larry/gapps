"""
Email reminders for risks: next review date and due date.

Run once a day from outside the app (cron / systemd timer / docker exec):

    python3 tools/send_risk_reminders.py              # send
    python3 tools/send_risk_reminders.py --dry-run    # only show what would be sent

Rules (all configurable in .env, see .env.example):
  * A risk is reminded about its review date and its due date separately, as long as
    it is not closed (mitigated / accepted) and enabled.
  * The first reminder is sent when the date is RISK_REMINDER_DAYS_BEFORE days away
    (or less). If the date has passed, a reminder is repeated every
    RISK_REMINDER_OVERDUE_REPEAT_DAYS days (0 = never repeat).
  * One email per distinct To/Cc combination, listing every risk for that recipient.
  * Recipients come from RISK_REMINDER_TO / RISK_REMINDER_CC, using the tokens
    assignee, project_managers, tenant_owner, risk_managers or fixed email addresses.
    When To resolves to nobody for a risk, RISK_REMINDER_FALLBACK_TO is used.
  * Reminders that were sent are stored in risk_reminders, so nothing is sent twice.

Only standard library imports at module level so the rules can be tested alone.
"""
import html
import logging
from datetime import date, datetime
from urllib.parse import quote

log = logging.getLogger(__name__)

TOKENS = ("assignee", "project_managers", "tenant_owner", "risk_managers")
KIND_LABELS = {"review": "Review due", "due": "Due date"}


def parse_tokens(value):
    """"assignee, risk_managers, ops@example.com" -> ["assignee", "risk_managers", "ops@example.com"]"""
    items = []
    for item in str(value or "").split(","):
        item = item.strip()
        if not item:
            continue
        if item.lower() in TOKENS:
            item = item.lower()
        elif "@" not in item:
            log.warning("Ignoring unknown reminder recipient %r", item)
            continue
        if item not in items:
            items.append(item)
    return items


def reminder_state(target, today, days_before, repeat_days, last_sent):
    """
    "upcoming" / "overdue" when a reminder should go out now, otherwise None.
    last_sent is the date of the latest reminder for this exact target date (or None).
    """
    if target is None:
        return None
    days_left = (target - today).days
    if days_left > days_before:
        return None
    if last_sent is None:
        return "overdue" if days_left < 0 else "upcoming"
    if days_left < 0 and repeat_days > 0 and (today - last_sent).days >= repeat_days:
        return "overdue"
    return None


def group_key(to, cc):
    return tuple(sorted(to)), tuple(sorted(cc))


def render_message(items, base_url):
    """-> (subject, text body, html body) for a list of reminder items."""
    items = sorted(items, key=lambda i: (i["days_left"] >= 0, i["target"], i["title"]))
    overdue = sum(1 for i in items if i["days_left"] < 0)
    subject = "Risk reminder: %d risk%s need%s attention" % (
        len(items),
        "" if len(items) == 1 else "s",
        "s" if len(items) == 1 else "",
    )
    if overdue:
        subject += " (%d overdue)" % overdue

    def when(item):
        d = item["days_left"]
        if d < 0:
            return "%s - overdue by %d day%s" % (item["target"], -d, "" if d == -1 else "s")
        if d == 0:
            return "%s - today" % item["target"]
        return "%s - in %d day%s" % (item["target"], d, "" if d == 1 else "s")

    def link(item):
        return (base_url.rstrip("/") + item["path"]) if base_url and item.get("path") else None

    text = ["The following risks need your attention:", ""]
    rows = []
    for item in items:
        line = "- %s [%s]: %s, %s" % (
            item["title"], item["level"], KIND_LABELS[item["kind"]], when(item)
        )
        if item.get("where"):
            line += " (%s)" % item["where"]
        if link(item):
            line += "\n  " + link(item)
        text.append(line)
        title_html = html.escape(item["title"])
        if link(item):
            title_html = '<a href="%s">%s</a>' % (html.escape(link(item)), title_html)
        color = ' style="color:#b91c1c;font-weight:bold"' if item["days_left"] < 0 else ""
        rows.append(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td%s>%s</td><td>%s</td></tr>"
            % (
                title_html,
                html.escape(item["level"]),
                KIND_LABELS[item["kind"]],
                color,
                html.escape(when(item)),
                html.escape(item.get("where") or ""),
            )
        )
    html_body = (
        "<p>The following risks need your attention:</p>"
        '<table cellpadding="6" cellspacing="0" border="1" style="border-collapse:collapse">'
        "<tr><th>Risk</th><th>Level</th><th>What</th><th>Date</th><th>Where</th></tr>%s</table>"
        % "".join(rows)
    )
    return subject, "\n".join(text), html_body


def _risk_path(risk):
    if risk.project_id:
        return "/projects/%s?tab=%s" % (risk.project_id, quote("risk register"))
    return "/tenants/%s/risk" % risk.tenant_id


def _emails_for_token(token, risk, models):
    """Resolve one recipient token for one risk -> list of email addresses."""
    if "@" in token:
        return [token]
    users = []
    if token == "assignee":
        if risk.assignee:
            users = [models.User.query.get(risk.assignee)]
    elif token == "project_managers":
        if risk.project_id:
            for member in models.ProjectMember.query.filter(
                models.ProjectMember.project_id == risk.project_id,
                models.ProjectMember.access_level == "manager",
            ).all():
                users.append(models.User.query.get(member.user_id))
    elif token == "tenant_owner":
        users = [models.User.query.get(risk.tenant.owner_id)]
    elif token == "risk_managers":
        for mapping in models.UserRole.get_mappings_for_role_in_tenant(
            "riskmanager", risk.tenant_id
        ):
            users.append(models.User.query.get(mapping.user_id))
    return [u.email for u in users if u and u.email and u.is_active]


def _excluded(email, domains):
    domain = email.rsplit("@", 1)[-1].lower()
    return any(domain == d or domain.endswith("." + d) for d in domains)


def resolve_recipients(tokens, risk, models, exclude_domains=()):
    """Email addresses for the tokens; addresses in exclude_domains (and their
    subdomains) are dropped, for example the fake users of the demo tenant."""
    emails = []
    for token in tokens:
        for email in _emails_for_token(token, risk, models):
            if _excluded(email, exclude_domains):
                continue
            if email.lower() not in [e.lower() for e in emails]:
                emails.append(email)
    return emails


def run(app, dry_run=False, today=None, out=print):
    """Collect due reminders, send them and record them. Returns (sent, failed)."""
    from app import db, models
    from app.email import send_email
    from app.utils.audit import log_event

    cfg = app.config
    today = today or datetime.utcnow().date()
    days_before = int(cfg.get("RISK_REMINDER_DAYS_BEFORE", 7))
    repeat_days = int(cfg.get("RISK_REMINDER_OVERDUE_REPEAT_DAYS", 7))
    to_tokens = parse_tokens(cfg.get("RISK_REMINDER_TO", "assignee"))
    cc_tokens = parse_tokens(cfg.get("RISK_REMINDER_CC", ""))
    fallback_tokens = parse_tokens(cfg.get("RISK_REMINDER_FALLBACK_TO", "risk_managers"))
    exclude_domains = [d.lower() for d in parse_tokens(cfg.get("RISK_REMINDER_EXCLUDE_DOMAINS", ""))]
    base_url = (cfg.get("APP_BASE_URL") or "").strip()
    if not base_url:
        out("[WARNING] APP_BASE_URL is not set - the emails will not contain links")

    R = models.RiskRegister
    closed = R.CLOSED_STATUSES
    risks = (
        R.query.filter(R.enabled.isnot(False))
        .filter(R.status.notin_(list(closed)))
        .filter((R.review_date.isnot(None)) | (R.due_date.isnot(None)))
        .all()
    )

    groups = {}  # (to, cc) -> {"to", "cc", "items": [...], "reminders": [(risk, kind, target)]}
    skipped_no_recipient = 0
    for risk in risks:
        for kind, target in (("review", risk.review_date), ("due", risk.due_date)):
            if target is None:
                continue
            last = (
                db.session.query(db.func.max(models.RiskReminder.sent_on))
                .filter(models.RiskReminder.risk_id == risk.id)
                .filter(models.RiskReminder.kind == kind)
                .filter(models.RiskReminder.target_date == target)
                .scalar()
            )
            state = reminder_state(target, today, days_before, repeat_days, last)
            if not state:
                continue
            to = resolve_recipients(to_tokens, risk, models, exclude_domains) or resolve_recipients(
                fallback_tokens, risk, models, exclude_domains
            )
            if not to:
                skipped_no_recipient += 1
                out("[WARNING] No recipient for risk %r (%s) - skipped" % (risk.title, kind))
                continue
            cc = [
                e for e in resolve_recipients(cc_tokens, risk, models, exclude_domains)
                if e.lower() not in [t.lower() for t in to]
            ]
            key = group_key(to, cc)
            group = groups.setdefault(
                key, {"to": to, "cc": cc, "items": [], "reminders": [], "tenant": risk.tenant_id}
            )
            where = None
            if risk.project_id:
                project = models.Project.query.get(risk.project_id)
                where = "Project: %s" % project.name if project else None
            group["items"].append(
                {
                    "title": risk.title,
                    "level": risk.risk,
                    "kind": kind,
                    "target": target.isoformat(),
                    "days_left": (target - today).days,
                    "path": _risk_path(risk),
                    "where": where,
                }
            )
            group["reminders"].append((risk, kind, target))

    sent = failed = 0
    for group in groups.values():
        subject, text_body, html_body = render_message(group["items"], base_url)
        label = "to %s%s" % (", ".join(group["to"]), (" cc " + ", ".join(group["cc"])) if group["cc"] else "")
        if dry_run:
            out("[DRY RUN] %s - %s (%d risk%s)" % (label, subject, len(group["items"]), "" if len(group["items"]) == 1 else "s"))
            for item in group["items"]:
                out("          - %s: %s %s (%+d days)" % (item["title"], KIND_LABELS[item["kind"]], item["target"], item["days_left"]))
            continue
        try:
            ok = send_email(
                subject, group["to"], text_body, html_body, async_send=False, cc=group["cc"] or None
            )
        except Exception as e:  # SMTP / network problems must not stop the other mails
            log.error("Sending risk reminder failed: %s", e)
            ok = False
        if not ok:
            failed += 1
            out("[ERROR] Could not send %s" % label)
            log_event(
                "risk_reminder_failed",
                result="failure",
                tenant=group["tenant"],
                metadata={"count": len(group["items"]), "label": label[:200]},
            )
            continue
        for risk, kind, target in group["reminders"]:
            db.session.add(
                models.RiskReminder(
                    risk_id=risk.id,
                    kind=kind,
                    target_date=target,
                    sent_on=today,
                    recipients=", ".join(group["to"] + group["cc"])[:500],
                )
            )
        db.session.commit()
        sent += 1
        out("[INFO] Sent %s (%d risk%s)" % (label, len(group["items"]), "" if len(group["items"]) == 1 else "s"))
        log_event(
            "risk_reminder_sent",
            tenant=group["tenant"],
            metadata={"count": len(group["items"]), "label": label[:200]},
        )

    out(
        "[INFO] Risk reminders: %d mail%s %s, %d failed, %d risk%s without recipient"
        % (
            len(groups) if dry_run else sent,
            "" if (len(groups) if dry_run else sent) == 1 else "s",
            "planned" if dry_run else "sent",
            failed,
            skipped_no_recipient,
            "" if skipped_no_recipient == 1 else "s",
        )
    )
    return sent, failed
