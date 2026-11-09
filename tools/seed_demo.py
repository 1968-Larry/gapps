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
from app.models import (
    db,
    Control,
    EvidenceAssociation,
    Framework,
    Logs,
    PolicyException,
    Project,
    RiskAssociation,
    RiskComment,
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
    ("Peter", "Holm", []),
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

# (title, description, justification, compensating controls, affected assets)
EXCEPTION_TEMPLATES = [
    ("SMBv1 enabled on document scanners", "Hardening baseline: SMBv1 must be disabled on all hosts.",
     "The scanner firmware only supports SMBv1 and the vendor has no update.",
     "Scanners in their own VLAN, firewall only allows TCP/445 to the scan file server.", "scan01, scan02"),
    ("Patch window missed for ERP database", "Patch policy: critical patches within 14 days.",
     "The ERP vendor has not yet certified the latest database patch level.",
     "Extra monitoring of the database host, access limited to the application servers.", "erp-db01"),
    ("Local admin rights for CAD workstations", "Least privilege: no local administrator rights for end users.",
     "The CAD licence tool needs local admin rights to update its dongle driver.",
     "EDR in blocking mode, separate admin account only used for the licence tool.", "CAD workstation group (12 PCs)"),
    ("Legacy TLS 1.0 on badge system", "Encryption standard: TLS 1.2 or newer for all services.",
     "The badge readers can only talk TLS 1.0 to the controller.",
     "Controller and readers on an isolated network without internet access.", "badge-ctrl01"),
    ("Password expiry disabled for service account", "Password policy: service account passwords rotated yearly.",
     "Rotating the password breaks an integration that can not be updated before the replacement project.",
     "Long random password stored in the vault, logon restricted to two servers.", "svc-integration"),
    ("No MFA for shop floor terminals", "Access control: MFA for all interactive logons.",
     "Shared terminals in the production hall, gloves and dust make tokens impractical.",
     "Terminals kiosk-locked, only the MES application, no network access outside the OT zone.", "OT kiosk terminals"),
    ("Unsupported OS on lab instrument PC", "Asset management: no operating systems without vendor support.",
     "The instrument software only runs on Windows 7 and the instrument is replaced next year.",
     "PC disconnected from the network, data moved with a scanned USB stick.", "lab-pc-07"),
    ("Log retention shorter than policy", "Logging: security logs kept for 12 months.",
     "Storage on the old log server is full until the SIEM migration is done.",
     "Critical logs forwarded to the SIEM already, others kept 90 days.", "log01"),
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
    for psc in subs:
        if rng.random() < 0.04:
            psc.is_applicable = False
            psc.implemented = 0
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
    for title, desc, remediation in rng.sample(RISK_TEMPLATES, rng.randint(6, 11)):
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
        # link to one to three subcontrols that are not done yet
        for psc in rng.sample(open_subs, min(len(open_subs), rng.randint(1, 3))):
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


# organisation level exceptions, linked to sub-controls in several projects
ORG_EXCEPTION_TEMPLATES = [
    ("Windows Server 2012 R2 still in use", "Asset management: no operating systems without vendor support.",
     "Three legacy applications are not certified on a newer Windows version yet.",
     "Extended security updates bought, servers in a restricted segment, extra EDR rules.",
     "app-legacy01..03", "active"),
    ("Shared admin account on network switches", "Access control: personal accounts for all administration.",
     "The old switch models do not support RADIUS/TACACS for management logins.",
     "Password in the vault with check-out logging, management only from the jump host.",
     "Access switches, building B", "submitted"),
]


def add_org_exceptions(rng, tenant, users, today):
    """Organisation level exceptions (no project), linked into every project."""
    requester = users.get(demo_email("Maria", "Svensson"))
    approver = users.get(demo_email("Erik", "Johansson"))
    if not requester or not approver:
        return 0
    created = 0
    for title, desc, why, comp, assets, state in ORG_EXCEPTION_TEMPLATES:
        exc = tenant.create_exception(
            {
                "title": title,
                "description": desc,
                "justification": why,
                "compensating_controls": comp,
                "affected_assets": assets,
                "likelihood": rng.randint(2, 3),
                "impact": rng.randint(2, 4),
                "assignee": requester.id,
                "expiry_date": (today + timedelta(days=rng.choice([120, 180]))).isoformat(),
            },
            requested_by=requester.id,
        )
        created += 1
        for project in tenant.projects.all():
            subs = [
                s
                for pc in project.controls.all()
                for s in pc.subcontrols.all()
                if s.is_applicable and s.implemented < 100
            ]
            if subs:
                rng.choice(subs).associate_with_exception(exc.id)
        exc.submit(requester.id)
        if state == "active":
            exc.approve(approver.id, "Accepted for the organisation until the replacement project.")
    return created


def add_demo_exceptions(rng, project, today):
    """A handful of exceptions in every state, linked to open subcontrols and risks."""
    members = {}
    for m in project.members.all():
        members.setdefault(m.access_level, []).append(m.user_id)
    approvers = members.get("manager", [])
    requesters = members.get("contributor", []) or approvers
    if not approvers or not requesters:
        return 0
    subs = [
        s
        for pc in project.controls.all()
        for s in pc.subcontrols.all()
        if s.is_applicable and s.implemented < 100
    ]
    risks = project.risks.all()
    plan = ["active", "active", "active", "expiring", "expired", "submitted", "draft", "rejected", "closed"]
    created = 0
    for (title, desc, why, comp, assets), state in zip(
        rng.sample(EXCEPTION_TEMPLATES, min(len(EXCEPTION_TEMPLATES), rng.randint(4, 7))),
        rng.sample(plan, len(plan)),
    ):
        requester = rng.choice(requesters)
        approver = rng.choice([a for a in approvers if a != requester] or approvers)
        expiry = today + timedelta(days=rng.choice([45, 90, 120, 180, 270]))
        if state == "expiring":
            expiry = today + timedelta(days=rng.randint(3, 20))
        exc = project.create_exception(
            {
                "title": title,
                "description": desc,
                "justification": why,
                "compensating_controls": comp,
                "affected_assets": assets,
                "likelihood": weighted(rng, {1: 15, 2: 45, 3: 30, 4: 10}),
                "impact": weighted(rng, {1: 10, 2: 35, 3: 35, 4: 20}),
                "assignee": requester,
                "expiry_date": expiry.isoformat(),
                "ticket_number": f"CHG-{rng.randint(1000, 9999)}" if rng.random() < 0.6 else None,
            },
            requested_by=requester,
        )
        created += 1
        for psc in rng.sample(subs, min(len(subs), rng.randint(1, 2))):
            psc.associate_with_exception(exc.id)
        if risks and rng.random() < 0.5:
            exc.associate_with_risk(rng.choice(risks).id)
        if state == "draft":
            continue
        exc.submit(requester)
        if state == "submitted":
            continue
        if state == "rejected":
            exc.reject(approver, "Describe the compensating controls in more detail.")
            continue
        exc.approve(approver, "Accepted until the replacement is in place.")
        if state == "expired":
            # pretend it was approved a while ago and nobody renewed it
            exc.valid_from = today - timedelta(days=200)
            exc.expiry_date = today - timedelta(days=rng.randint(5, 40))
            exc._skip_history = True
            db.session.commit()
        elif state == "closed":
            exc.close("Fixed - the system was replaced.")
    return created


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
    args = parser.parse_args()

    app = create_app(os.getenv("FLASK_CONFIG") or "default")
    with app.app_context():
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

        # exceptions, with their own random generator so the data above stays the same
        erng = random.Random(args.seed + 1)
        total_exceptions = 0
        for project in tenant.projects.order_by(Project.date_added).all():
            total_exceptions += add_demo_exceptions(erng, project, today)
        total_exceptions += add_org_exceptions(random.Random(args.seed + 2), tenant, users, today)

        log("")
        log(
            f"Done: tenant '{args.tenant}', {count} projects, {total_risks} risks, "
            f"{total_exceptions} exceptions"
        )
        log(f"Log in with {admin_email} / {args.password}")
        log(f"All demo users share that password, e.g. {demo_email('Erik', 'Johansson')}")


if __name__ == "__main__":
    main()
