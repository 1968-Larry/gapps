"""
Create a demo tenant with fake users, 10 projects and pre-made data (subcontrol
status, evidence, risks with dates/history, exceptions in every state) so the
platform can be demonstrated.

Everything lives in ONE tenant (default name "demo") and all fake users use the
address domain demo.example.com. Real tenants and users are never touched.

    python3 tools/seed_demo.py                       # create the demo tenant
    python3 tools/seed_demo.py --reset               # delete it and create it again
    python3 tools/seed_demo.py --delete              # only delete it
    python3 tools/seed_demo.py --projects 10 --frameworks soc2,iso_27001_2022,nist_csf_v2.0
    python3 tools/seed_demo.py --seed 7              # other (but repeatable) random data
    python3 tools/seed_demo.py --deadlines           # only (re)set planned end dates on an
                                                     # existing demo tenant

In the docker setup:  docker exec app python3 tools/seed_demo.py

The framework json files must exist (FRAMEWORK_FOLDER). Importing them is the slow
part, expect a few minutes. Risk reminder mails are never sent to the demo domain
(RISK_REMINDER_EXCLUDE_DOMAINS).
"""
import argparse
import os
import random
import sys
from datetime import datetime, timedelta

# Make the app package importable when run as a script
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func
from app import create_app
import demo_data  # curated exceptions, topics and justifications (tools/demo_data.py)
from app.models import (
    db,
    Control,
    EvidenceAssociation,
    ExceptionComment,
    ExceptionHistory,
    Framework,
    Logs,
    PolicyException,
    Project,
    ProjectSubControl,
    RiskAssociation,
    RiskComment,
    RiskHistory,
    RiskRegister,
    Tenant,
    TenantMember,
    User,
)

DEMO_DOMAIN = "demo.example.com"

# (first, last, tenant roles)
USERS = [
    ("Anna", "Lindqvist", ["admin"]),
    ("Erik", "Johansson", ["riskmanager"]),
    ("Maria", "Svensson", ["riskmanager"]),
    ("Johan", "Karlsson", []),
    ("Sara", "Nilsson", []),
    ("Oskar", "Andersson", []),
    ("Linda", "Berg", []),
    ("Peter", "Holm", ["ciso"]),
]

# (name, description, maturity 0..1) - maturity decides how much is implemented
PROJECTS = [
    ("Customer Portal", "Public customer self-service portal", 0.80),
    ("Payments Platform", "Card payments and settlement services", 0.90),
    ("HR System", "Employee data, payroll and recruitment", 0.65),
    ("Data Warehouse", "Analytics platform and reporting", 0.50),
    ("Mobile App", "iOS and Android customer app", 0.70),
    ("Internal IT", "Workplace IT, identity and endpoints", 0.60),
    ("Supplier Portal", "Onboarding and follow-up of suppliers", 0.35),
    ("Public Website", "Marketing site and content platform", 0.75),
    ("Production Infrastructure", "Cloud hosting, network and platform services", 0.55),
    ("R&D Lab", "Experimental environment for product development", 0.20),
]

# (title, description, remediation)
RISK_TEMPLATES = [
    ("Unpatched critical vulnerabilities", "Systems run software with known critical vulnerabilities for longer than the patch policy allows.", "Introduce monthly patch windows and automatic scanning with SLA per severity."),
    ("Excessive administrator access", "Too many accounts have standing administrator privileges.", "Move to just-in-time admin access and review privileged accounts quarterly."),
    ("Missing multi-factor authentication", "Remote access and some admin interfaces only require a password.", "Enforce MFA for all remote and privileged access."),
    ("Backups not tested", "Backups are taken but restore has not been verified recently.", "Schedule quarterly restore tests and document the results."),
    ("Supplier without security assessment", "A critical supplier has not been assessed and has no security clauses in the contract.", "Run a supplier assessment and add security requirements to the agreement."),
    ("Insufficient logging and monitoring", "Security events are not centrally collected and nobody reviews alerts.", "Forward logs to a central platform and define alert handling."),
    ("Sensitive data stored unencrypted", "Some databases and file shares hold personal data without encryption at rest.", "Enable encryption at rest and key management."),
    ("No tested incident response plan", "The incident response plan exists but has never been exercised.", "Run a tabletop exercise twice per year."),
    ("Shadow IT and unapproved SaaS", "Teams use cloud services that are not registered or assessed.", "Introduce an approval process and discover usage via the proxy logs."),
    ("Weak password policy", "Legacy systems accept short passwords without lockout.", "Raise the policy and introduce a password manager."),
    ("Insecure software development", "Code is released without peer review or dependency scanning.", "Add mandatory reviews, SAST and dependency checks in the pipeline."),
    ("Lost or stolen devices", "Laptops and phones are not fully encrypted or remotely wipeable.", "Roll out disk encryption and mobile device management."),
    ("Business continuity not validated", "Recovery time objectives are not defined for key services.", "Define RTO/RPO and test failover for critical services."),
    ("Phishing awareness is low", "Simulated phishing shows a high click rate.", "Run recurring awareness training and phishing simulations."),
    ("Missing data retention rules", "Personal data is kept longer than needed.", "Define retention periods and automate deletion."),
    ("Network segmentation is flat", "Production, office and test networks are reachable from each other.", "Introduce segmentation and restrict east-west traffic."),
    ("Third-party library with end of life", "A framework in use no longer receives security updates.", "Upgrade or replace the component."),
    ("Insufficient physical access control", "Server rooms are accessed with shared keys.", "Introduce badge access with logging."),
    ("Unclear data ownership", "Several data sets have no named owner or classification.", "Appoint data owners and classify the data."),
    ("Insecure API exposure", "Internal APIs are reachable without authentication from partner networks.", "Add authentication and rate limiting to all APIs."),
    ("Leavers keep access", "Accounts of former employees and consultants stay active.", "Automate de-provisioning from the HR system."),
    ("Configuration drift in cloud", "Cloud resources deviate from the hardened baseline.", "Use infrastructure as code and policy checks."),
]

EVIDENCE_TEMPLATES = [
    ("Access review report", "Quarterly review of user and administrator access."),
    ("Backup and restore test", "Result of the latest restore test."),
    ("Vulnerability scan summary", "Export from the vulnerability scanner."),
    ("Penetration test report", "External penetration test, executive summary."),
    ("Security awareness training log", "Attendance list from the annual training."),
    ("Incident response exercise notes", "Notes and actions from the tabletop exercise."),
    ("Change management records", "Sample of approved changes."),
    ("Network diagram", "Current network and segmentation diagram."),
    ("Supplier assessment", "Completed supplier security questionnaire."),
    ("Policy approval record", "Management approval of the security policies."),
    ("Encryption configuration", "Screenshots of encryption settings."),
    ("Monitoring dashboard export", "Alerting rules and last month's alerts."),
]

IMPLEMENTED_CONTEXT = [
    "Implemented and documented in the ISMS. Reviewed yearly.",
    "Covered by the standard operating procedure and enforced technically.",
    "Operated by the IT team, evidence is collected quarterly.",
    "Handled by a managed service, see supplier agreement.",
]

COMMENTS = [
    "Discussed in the risk meeting, waiting for budget decision.",
    "Mitigation started, first milestone is next sprint.",
    "Accepted by management for now, will be revisited at next review.",
    "Needs input from the supplier before we can proceed.",
    "Ticket created and prioritised with the platform team.",
]


def log(message):
    print(message, flush=True)


def demo_email(first, last):
    return f"{first.lower()}.{last.lower()}@{DEMO_DOMAIN}"


def find_tenant(name):
    return Tenant.query.filter(func.lower(Tenant.name) == name.lower()).first()


def delete_demo(name):
    from app.utils import audit

    tenant = find_tenant(name)
    if not tenant:
        log(f"No tenant named '{name}', nothing to delete")
        return
    users = [m.user for m in tenant.members.all()]
    foreign = [u.email for u in users if not u.email.lower().endswith("@" + DEMO_DOMAIN)]
    if foreign:
        sys.exit(
            f"Refusing to delete tenant '{name}': it has members outside @{DEMO_DOMAIN} "
            f"({', '.join(foreign)}). Only demo tenants can be deleted by this script."
        )
    tenant_id = tenant.id
    user_ids = [u.id for u in users]
    log(f"Deleting tenant '{name}' with all its data ...")

    # The audit trail writes rows to `logs` (on its own connection) that point at the
    # tenant and users, which blocks the delete. Pause it and clear the old rows first.
    saved = (audit._state.get("enabled"), audit._state.get("gui"))
    audit._state["enabled"] = False
    audit._state["gui"] = False
    try:
        Logs.query.filter(
            (Logs.tenant_id == tenant_id) | (Logs.user_id.in_(user_ids))
        ).delete(synchronize_session=False)
        db.session.commit()

        tenant = Tenant.query.get(tenant_id)
        tenant.delete()
        for user in User.query.filter(User.id.in_(user_ids)).all():
            try:
                if TenantMember.query.filter(TenantMember.user_id == user.id).count() == 0:
                    Logs.query.filter(Logs.user_id == user.id).delete(synchronize_session=False)
                    db.session.delete(user)
                    db.session.commit()
            except Exception as e:
                db.session.rollback()
                log(f"[WARNING] Could not delete user {user.email}: {e}")
    finally:
        audit._state["enabled"], audit._state["gui"] = saved
    log("Deleted")


def create_users(tenant, password):
    users = {}
    for first, last, roles in USERS:
        email = demo_email(first, last)
        user = User.find_by_email(email)
        if not user:
            user = User.add(
                email,
                password=password,
                first_name=first,
                last_name=last,
                confirmed=True,
                return_user_object=True,
            )
        if not tenant.has_member(user):
            tenant.add_member(user_or_email=user, attributes={"roles": list(roles)})
        users[email] = user
    return users


def pick_review_dates(rng, today, status):
    """(review_date, due_date): a mix of overdue, soon and later."""
    roll = rng.random()
    if roll < 0.20:
        review = today - timedelta(days=rng.randint(3, 45))
    elif roll < 0.40:
        review = today + timedelta(days=rng.randint(0, 7))
    else:
        review = today + timedelta(days=rng.randint(8, 200))
    due = None
    if status in ("new", "in_progress") and rng.random() < 0.7:
        roll = rng.random()
        if roll < 0.15:
            due = today - timedelta(days=rng.randint(2, 30))
        elif roll < 0.35:
            due = today + timedelta(days=rng.randint(0, 7))
        else:
            due = today + timedelta(days=rng.randint(8, 150))
    return review, due


def weighted(rng, weights):
    total = sum(weights.values())
    pick = rng.uniform(0, total)
    upto = 0
    for key, weight in weights.items():
        upto += weight
        if pick <= upto:
            return key
    return key


def build_project(rng, tenant, index, spec, frameworks, controls_by_fw, users, common_gaps, today):
    name, description, maturity = spec
    user_list = list(users.values())
    managers = [u for u in user_list if u.email.split("@")[0] in ("erik.johansson", "sara.nilsson", "johan.karlsson", "linda.berg")]
    owner = managers[index % len(managers)]

    # every project uses the first framework, about half also use a second one
    fw_names = [frameworks[0]]
    if len(frameworks) > 1 and index % 2 == 1:
        fw_names.append(frameworks[1 + (index // 2) % (len(frameworks) - 1)])
    primary = Framework.find_by_name(fw_names[0], tenant.id)

    project = tenant.create_project(
        name=name, owner_id=owner.id, framework_id=primary.id, description=description
    )

    # members
    project.add_member(owner, "manager")
    others = [u for u in user_list if u.id != owner.id]
    rng.shuffle(others)
    for u in others[:2]:
        project.add_member(u, "contributor")
    for u in others[2:4]:
        project.add_member(u, "viewer")
    members = [owner] + others[:2]

    # controls: a share of each framework, different per project but overlapping
    for fw in fw_names:
        controls = list(controls_by_fw[fw])
        rng.shuffle(controls)
        take = int(len(controls) * rng.uniform(0.55, 0.9))
        for control in controls[:take]:
            project.add_control(control, commit=False)
    db.session.commit()

    # evidence pool
    pool = []
    for title, desc in rng.sample(EVIDENCE_TEMPLATES, 9):
        pool.append(
            project.create_evidence(
                name=title,
                owner_id=rng.choice(members).id,
                description=desc,
                link=f"https://wiki.{DEMO_DOMAIN}/{project.name.lower().replace(' ', '-')}/{title.lower().replace(' ', '-')}",
                group=rng.choice(["policy", "technical", "process"]),
                collected_on=datetime.utcnow() - timedelta(days=rng.randint(5, 300)),
            )
        )

    # subcontrol status
    subs = []
    for pc in project.controls.all():
        subs.extend(pc.subcontrols.all())
    # not applicable controls get a justification - except one in the first
    # project, so the Statement of Applicability shows its warning
    leave_one_without = index == 0
    for psc in subs:
        if rng.random() < 0.04:
            psc.is_applicable = False
            psc.implemented = 0
            if leave_one_without:
                leave_one_without = False
            else:
                psc.notes = rng.choice(demo_data.NA_JUSTIFICATIONS)
            continue
        if psc.subcontrol_id in common_gaps and rng.random() < 0.75:
            roll = 2  # shared weak spot: mostly not implemented
        else:
            roll = rng.random()
        if roll < maturity * 0.85:
            psc.implemented = 100
        elif roll < maturity * 0.85 + (1 - maturity) * 0.45 and roll != 2:
            psc.implemented = 50
        else:
            psc.implemented = 0
        psc.owner_id = rng.choice(members).id
        if psc.implemented:
            psc.context = rng.choice(IMPLEMENTED_CONTEXT)
            if rng.random() < (0.85 if psc.implemented == 100 else 0.4):
                db.session.add(EvidenceAssociation(control_id=psc.id, evidence_id=rng.choice(pool).id))
        if rng.random() < 0.05:
            psc.ticket_number = f"CHG-{rng.randint(1000, 9999)}"
    db.session.commit()

    # risks
    open_subs = [s for s in subs if s.is_applicable and s.implemented < 100]
    created = 0
    # the risks the project's exceptions refer to (demo_data) are always there
    needed = {i.get("risk") for i in demo_data.PROJECT_EXCEPTIONS.get(name, [])} - {None}
    others = [t for t in RISK_TEMPLATES if t[0] not in needed]
    chosen = [t for t in RISK_TEMPLATES if t[0] in needed]
    chosen += rng.sample(others, max(0, rng.randint(6, 11) - len(chosen)))
    for title, desc, remediation in chosen:
        status = weighted(rng, {"new": 25, "in_progress": 40, "mitigated": 20, "accepted": 15})
        review, due = pick_review_dates(rng, today, status)
        risk = project.create_risk(
            title=f"{title} [{project.name}]",  # titles must be unique within a tenant
            description=desc,
            status=status,
            priority=rng.choice(["low", "moderate", "high"]),
            assignee=rng.choice(members).id,
            likelihood=weighted(rng, {1: 20, 2: 35, 3: 30, 4: 15}),
            impact=weighted(rng, {1: 15, 2: 35, 3: 30, 4: 20}),
            ticket_number=f"SEC-{rng.randint(100, 999)}" if rng.random() < 0.7 else None,
            review_date=review,
            due_date=due,
        )
        risk.remediation = remediation
        created += 1
        # link to the controls the risk is about (demo_data.RISK_TOPICS)
        topic_subs = []
        for topic in demo_data.RISK_TOPICS.get(title, []):
            topic_subs.extend(topic_subcontrols(project, topic))
        if not topic_subs:
            topic_subs = rng.sample(open_subs, min(len(open_subs), 1))
        for psc in topic_subs[:4]:
            RiskAssociation.add([psc.id], risk.id, commit=False)
        for _ in range(rng.choice([0, 0, 1, 2])):
            db.session.add(
                RiskComment(
                    message=rng.choice(COMMENTS),
                    owner_id=rng.choice(members).id,
                    risk_id=risk.id,
                    tenant_id=tenant.id,
                )
            )
        db.session.commit()

        # some history: a reassessment, and now and then a documented review
        if rng.random() < 0.3 and risk.impact and risk.impact > 1:
            risk.impact = risk.impact - 1
            db.session.commit()
        if status in ("new", "in_progress") and review > today and rng.random() < 0.2:
            risk.mark_reviewed("Reviewed in the monthly risk meeting, no change in assessment.")
    return project, created, len(subs)


# --------------------------------------------------------------------------- #
# Topics: find the sub-control(s) of a topic in a project
# --------------------------------------------------------------------------- #
def norm_ref(ref):
    return "".join(str(ref or "").split()).lower()


def backdate_risks(tenant):
    """
    Spread the risks over the last year instead of all being created today (the
    risk register filters on created date). History and comments follow along.
    """
    rng = random.Random(f"{tenant.id}-risk-dates")
    now = datetime.utcnow()
    for risk in RiskRegister.query.filter_by(tenant_id=tenant.id).order_by(RiskRegister.title).all():
        start = now - timedelta(days=rng.randint(12, 420), hours=rng.randint(0, 9))
        risk.date_added = start
        for i, entry in enumerate(risk.history.order_by(RiskHistory.date_added).all()):
            entry.date_added = start + timedelta(minutes=5 * i)
        for i, comment in enumerate(risk.comments.all()):
            comment.date_added = start + timedelta(days=rng.randint(1, max(1, (now - start).days - 1)), hours=i)
    db.session.commit()


def topic_subcontrols(project, topic, add_missing=True):
    """
    Project sub-controls for a topic (see demo_data.TOPIC_REFS), in every framework
    of the project. When the project did not pick the control that holds the
    sub-control, the control is added (a real project would have it).
    """
    refs = demo_data.TOPIC_REFS.get(topic, {})
    found = []
    for framework in {pc.control.framework for pc in project.controls.all()}:
        wanted = {norm_ref(r) for r in refs.get(framework.name, [])}
        if not wanted:
            continue
        subs = [
            psc
            for pc in project.controls.all()
            if pc.control.framework_id == framework.id
            for psc in pc.subcontrols.all()
            if norm_ref(psc.subcontrol.ref_code) in wanted
        ]
        if not subs and add_missing:
            for control in framework.controls.all():
                if any(norm_ref(sc.ref_code) in wanted for sc in control.subcontrols.all()):
                    project.add_control(control)
                    db.session.commit()
                    pc = project.has_control(control.id)
                    for psc in pc.subcontrols.all():
                        psc.implemented = 0
                    db.session.commit()
                    subs = [psc for psc in pc.subcontrols.all() if norm_ref(psc.subcontrol.ref_code) in wanted]
                    break
        found.extend(subs)
    return found


# --------------------------------------------------------------------------- #
# Exceptions: walk each one through the real workflow, then date its history
# back so it looks like it has been in use for a while
# --------------------------------------------------------------------------- #
def _date_back(exc, story, today):
    """Spread the history entries over the days of the story and fix the dates."""
    days = demo_data.STORIES[story]["days"]
    entries = exc.history.order_by(ExceptionHistory.date_added).all()
    stamps = {}
    for entry, ago in zip(entries, days):
        when = datetime.combine(today - timedelta(days=ago), datetime.min.time()) + timedelta(
            hours=8 + (ago * 7) % 9, minutes=(ago * 13) % 60
        )
        entry.date_added = when
        stamps.setdefault(entry.event, []).append(when.date())
    exc.date_added = entries[0].date_added if entries else exc.date_added
    if "submitted" in stamps or "resubmitted" in stamps:
        exc.submitted_date = max(stamps.get("submitted", []) + stamps.get("resubmitted", []))
    for event in ("approved", "rejected"):
        if event in stamps:
            exc.decided_date = max(stamps[event])
    if "approved" in stamps and story != "renewed":
        exc.valid_from = stamps["approved"][0]
    elif "approved" in stamps:
        exc.valid_from = stamps["approved"][-1]
    if "closed" in stamps:
        exc.closed_date = stamps["closed"][-1]
    exc.expiry_date = today + timedelta(days=demo_data.STORIES[story]["expiry"])
    exc._skip_history = True
    db.session.commit()


def _pick_approver(exc, not_this, turn=0):
    """
    Someone who may decide, with the lowest role that is enough for the level (a
    security manager decides a low exception, not the CISO); `turn` rotates
    between people with that role so the demo shows different approvers.
    """
    candidates = [u for u in exc.eligible_approvers() if u.id != not_this]
    if candidates:
        lowest = min(exc.approver_rank(u) for u in candidates)
        same = sorted((u for u in candidates if exc.approver_rank(u) == lowest), key=lambda u: u.email)
        return same[turn % len(same)].id
    # nobody else holds the role: an admin decides (the app allows that fallback)
    for user in exc.tenant.users_with_role("admin"):
        if user.id != not_this and exc.user_can_approve(user):
            return user.id
    return None


def run_story(exc, story, requester_id, note, today, turn=0):
    """Workflow steps for a story (see demo_data.STORIES)."""
    if story == "draft":
        return
    exc.submit(requester_id)
    if story == "awaiting":
        return
    approver = _pick_approver(exc, requester_id, turn)
    if not approver:
        return
    if story in ("rejected", "reworked"):
        exc.reject(approver, note or "Please describe the compensating controls in more detail.")
        if story == "reworked":
            exc.update({"compensating_controls": exc.compensating_controls + " Updated after review."})
            exc.submit(requester_id)
        return
    exc.approve(approver, note)
    if story == "renewed":
        # extended: back for approval, approved again (the expiry is set in _date_back)
        exc.update({"expiry_date": (today + timedelta(days=170)).isoformat()}, confirm_resubmit=True)
        exc.approve(approver, note)
    elif story == "closed":
        exc.close("The deviation is fixed.")


def _add_comments(exc, comments, people, today, tenant_id):
    entries = exc.history.order_by(ExceptionHistory.date_added).all()
    start = entries[0].date_added if entries else datetime.utcnow()
    for i, (who, text) in enumerate(comments or []):
        owner = people.get(who) or people.get("requester")
        if not owner:
            continue
        comment = ExceptionComment(
            message=text, owner_id=owner, exception_id=exc.id, tenant_id=tenant_id
        )
        db.session.add(comment)
        db.session.flush()
        comment.date_added = start + timedelta(days=1 + i, hours=2)
    db.session.commit()


def _link_risk(exc, project, template_title):
    if not template_title or not project:
        return
    for risk in project.risks.all():
        if risk.title.startswith(template_title):
            exc.associate_with_risk(risk.id)
            return


def _mark_deviation(subcontrols):
    """A control with an exception is not fully in place for every system."""
    for psc in subcontrols:
        if psc.implemented == 100:
            psc.implemented = 50
            psc.context = "Implemented, except for the systems covered by an approved exception."
    db.session.commit()


def add_demo_exceptions(tenant, today):
    """
    Curated exceptions (demo_data.PROJECT_EXCEPTIONS / ORG_EXCEPTIONS): each one on
    the control it deviates from, linked to the matching risk, with a history of
    submissions, decisions and comments in the past.
    """
    projects = {p.name: p for p in tenant.projects.all()}
    created = 0
    for name, items in demo_data.PROJECT_EXCEPTIONS.items():
        project = projects.get(name)
        if not project:
            continue
        members = {m.user_id: m.access_level for m in project.members.all()}
        # the CISO decides on exceptions, so he is not the one asking for them here
        ciso = {u.id for u in tenant.users_with_role("ciso")}
        editors = sorted(
            uid for uid, lvl in members.items() if lvl in ("contributor", "manager") and uid not in ciso
        )
        for i, item in enumerate(items):
            requester = editors[i % len(editors)]
            exc = project.create_exception(
                {
                    "title": item["title"],
                    "description": item["description"],
                    "justification": item["justification"],
                    "compensating_controls": item["compensating"],
                    "affected_assets": item["assets"],
                    "likelihood": item["likelihood"],
                    "impact": item["impact"],
                    "assignee": requester,
                    "expiry_date": (today + timedelta(days=150)).isoformat(),
                    "ticket_number": f"CHG-{4100 + created * 7}",
                },
                requested_by=requester,
            )
            created += 1
            subs = topic_subcontrols(project, item["topic"])
            for psc in subs:
                psc.associate_with_exception(exc.id)
            _link_risk(exc, project, item.get("risk"))
            run_story(exc, item["story"], requester, item.get("note"), today, turn=created)
            _date_back(exc, item["story"], today)
            if exc.state() in ("active", "expired", "submitted"):
                _mark_deviation(subs)
            _add_comments(
                exc, item.get("comments"),
                {"requester": requester, "owner": requester, "approver": exc.decided_by
                 or (_pick_approver(exc, requester))},
                today, tenant.id,
            )

    # organisation level: requested by the security manager, decided by the CISO
    requester = User.find_by_email(demo_email("Maria", "Svensson"))
    for item in demo_data.ORG_EXCEPTIONS:
        if not requester:
            break
        exc = tenant.create_exception(
            {
                "title": item["title"],
                "description": item["description"],
                "justification": item["justification"],
                "compensating_controls": item["compensating"],
                "affected_assets": item["assets"],
                "likelihood": item["likelihood"],
                "impact": item["impact"],
                "assignee": requester.id,
                "expiry_date": (today + timedelta(days=150)).isoformat(),
            },
            requested_by=requester.id,
        )
        created += 1
        linked = []
        for name in item["projects"]:
            if project := projects.get(name):
                subs = topic_subcontrols(project, item["topic"])
                for psc in subs:
                    psc.associate_with_exception(exc.id)
                linked.extend(subs)
        run_story(exc, item["story"], requester.id, item.get("note"), today, turn=created)
        _date_back(exc, item["story"], today)
        if exc.state() in ("active", "expired", "submitted"):
            _mark_deviation(linked)
        _add_comments(exc, item.get("comments"),
                      {"requester": requester.id, "owner": requester.id,
                       "approver": exc.decided_by or _pick_approver(exc, requester.id)},
                      today, tenant.id)
    return created

def add_demo_deadlines(tenant, today, seed):
    """
    Planned end dates on sub-controls for the Deadlines page. Whole controls are
    planned (the sub-controls of a control end within a week or two of each
    other), so the page shows several sub-controls under one control. Roughly a
    quarter of the planned controls are in the past, so there are overdue ones;
    complete sub-controls in the past show up as complete. Uses its own random
    generator, so the rest of the demo data does not change.
    """
    rng = random.Random(seed + 1000)
    dated = 0
    for project in Project.query.filter(Project.tenant_id == tenant.id).all():
        subs = (
            ProjectSubControl.query.filter(ProjectSubControl.project_id == project.id)
            .filter(ProjectSubControl.is_applicable == True)  # noqa: E712
            .all()
        )
        for psc in subs:
            psc.planned_end = None
        by_control = {}
        for psc in subs:
            by_control.setdefault(psc.project_control_id, []).append(psc)
        for control_subs in by_control.values():
            if rng.random() > 0.3:
                continue
            when = weighted(rng, {"past": 25, "soon": 35, "later": 40})
            if when == "past":
                offset = rng.randint(-75, -3)
            elif when == "soon":
                offset = rng.randint(0, 45)
            else:
                offset = rng.randint(46, 270)
            target = today + timedelta(days=offset)
            for psc in control_subs:
                if rng.random() < 0.85:
                    psc.planned_end = target + timedelta(days=rng.randint(-7, 7))
                    dated += 1
        # a few single sub-controls with their own date
        for psc in rng.sample(subs, min(len(subs), 4)):
            if not psc.planned_end:
                psc.planned_end = today + timedelta(days=rng.randint(-30, 120))
                dated += 1
    db.session.commit()
    return dated


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--tenant", default="demo", help="name of the demo tenant (default: demo)")
    parser.add_argument("--projects", type=int, default=10, help="number of projects (1-10, default 10)")
    parser.add_argument("--frameworks", default="soc2,iso_27001_2022,nist_csf_v2.0",
                        help="comma list of framework json names in FRAMEWORK_FOLDER")
    parser.add_argument("--password", default="Demo-Password-2026!", help="password for all demo users")
    parser.add_argument("--seed", type=int, default=42, help="random seed (same seed = same data)")
    parser.add_argument("--reset", action="store_true", help="delete the demo tenant first")
    parser.add_argument("--delete", action="store_true", help="only delete the demo tenant")
    parser.add_argument("--deadlines", action="store_true",
                        help="only (re)set planned end dates in the existing demo tenant")
    args = parser.parse_args()

    app = create_app(os.getenv("FLASK_CONFIG") or "default")
    with app.app_context():
        if args.deadlines:
            tenant = find_tenant(args.tenant)
            if not tenant:
                sys.exit(f"Tenant '{args.tenant}' not found. Create it first.")
            owner = User.query.get(tenant.owner_id)
            if not owner or not owner.email.endswith("@" + DEMO_DOMAIN):
                sys.exit(f"Tenant '{args.tenant}' is not a demo tenant, refusing to change it.")
            today = datetime.utcnow().date()
            log(f"Planned end dates: {add_demo_deadlines(tenant, today, args.seed)} sub-controls")
            return
        if args.delete or args.reset:
            delete_demo(args.tenant)
            if args.delete:
                return
        if find_tenant(args.tenant):
            sys.exit(f"Tenant '{args.tenant}' already exists. Use --reset to recreate it.")

        folder = app.config["FRAMEWORK_FOLDER"]
        frameworks = [f.strip() for f in args.frameworks.split(",") if f.strip()]
        for fw in frameworks:
            if not os.path.isfile(os.path.join(folder, f"{fw}.json")):
                sys.exit(f"Framework file not found: {os.path.join(folder, fw + '.json')}")

        rng = random.Random(args.seed)
        today = datetime.utcnow().date()
        count = max(1, min(args.projects, len(PROJECTS)))

        admin_email = demo_email(USERS[0][0], USERS[0][1])
        admin = User.find_by_email(admin_email) or User.add(
            admin_email,
            password=args.password,
            first_name=USERS[0][0],
            last_name=USERS[0][1],
            confirmed=True,
            return_user_object=True,
        )
        log(f"Creating tenant '{args.tenant}' ...")
        tenant = Tenant.create(admin, args.tenant, admin_email)
        tenant.project_cap = 100
        tenant.user_cap = 100
        db.session.commit()

        users = create_users(tenant, args.password)
        users[admin_email] = admin

        controls_by_fw = {}
        for fw in frameworks:
            log(f"Importing framework {fw} (slow) ...")
            tenant.create_base_controls_for_framework(fw)
            framework = Framework.find_by_name(fw, tenant.id)
            controls_by_fw[fw] = Control.query.filter(Control.framework_id == framework.id).all()
            log(f"  {len(controls_by_fw[fw])} controls")

        # subcontrols that are weak in most projects, so cross-project gaps show up
        all_sub_ids = [s.id for fw in frameworks for c in controls_by_fw[fw] for s in c.subcontrols.all()]
        common_gaps = set(rng.sample(all_sub_ids, max(1, int(len(all_sub_ids) * 0.08))))

        total_risks = 0
        for index, spec in enumerate(PROJECTS[:count]):
            log(f"Project {index + 1}/{count}: {spec[0]} ...")
            _, risks, subs = build_project(
                rng, tenant, index, spec, frameworks, controls_by_fw, users, common_gaps, today
            )
            total_risks += risks
            log(f"  {subs} subcontrols, {risks} risks")

        # a few organisation level risks, not tied to a project
        owners = list(users.values())
        for title, desc, remediation in rng.sample(RISK_TEMPLATES, 5):
            status = weighted(rng, {"new": 30, "in_progress": 50, "accepted": 20})
            review, due = pick_review_dates(rng, today, status)
            tenant.create_risk(
                title=f"[Org] {title}",
                description=desc,
                remediation=remediation,
                status=status,
                priority=rng.choice(["moderate", "high"]),
                assignee=rng.choice(owners).email,
                likelihood=rng.randint(1, 4),
                impact=rng.randint(2, 4),
                ticket_number=f"SEC-{rng.randint(100, 999)}",
                review_date=review,
                due_date=due,
            )
            total_risks += 1

        backdate_risks(tenant)

        # exceptions, with their own random generator so the data above stays the same
        total_exceptions = add_demo_exceptions(tenant, today)

        # planned end dates (Deadlines page)
        total_deadlines = add_demo_deadlines(tenant, today, args.seed)

        log("")
        log(
            f"Done: tenant '{args.tenant}', {count} projects, {total_risks} risks, "
            f"{total_exceptions} exceptions, {total_deadlines} planned end dates"
        )
        log(f"Log in with {admin_email} / {args.password}")
        log(f"All demo users share that password, e.g. {demo_email('Erik', 'Johansson')}")


if __name__ == "__main__":
    main()
