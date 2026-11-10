"""
Data for the reports that are built in the browser (jsPDF / CSV).

    GET /api/v1/projects/<pid>/reports/soa          Statement of Applicability rows
    GET /api/v1/tenants/<tid>/reports/overview      Gaps, risks and exceptions of
                                                    selected projects (Reports page)
"""
from datetime import datetime

from flask import jsonify, request
from flask_login import current_user
from sqlalchemy import func

from . import api
from app import models
from app.utils.authorizer import Authorizer
from app.utils.decorators import login_required


def _email(user_id, cache):
    if not user_id:
        return None
    if user_id not in cache:
        user = models.User.query.get(user_id)
        cache[user_id] = user.email if user else None
    return cache[user_id]


@api.route("/projects/<string:pid>/reports/soa", methods=["GET"])
@login_required
def get_soa_for_project(pid):
    """
    One row per sub-control: is it applicable, how far it is implemented, the
    justification (context / notes), owner, evidence, and the exceptions and
    risks that are linked to it.
    """
    result = Authorizer(current_user).can_user_read_project(pid)
    project = result["extra"]["project"]
    emails = {}
    rows = []
    controls = sorted(
        project.controls.all(),
        key=lambda c: (c.control.framework.name, _ref_key(c.control.ref_code)),
    )
    for p_control in controls:
        control = p_control.control
        subcontrols = sorted(
            p_control.subcontrols.all(), key=lambda s: _ref_key(s.subcontrol.ref_code)
        )
        for sub in subcontrols:
            justification = (sub.context or "").strip()
            notes = (sub.notes or "").strip()
            if not sub.is_applicable and notes:
                # for an excluded control the reason usually is in the notes
                justification = notes if not justification else f"{justification}\n{notes}"
            exceptions = [e.summary() for e in sub.exceptions.all()]
            rows.append(
                {
                    "id": sub.id,
                    "framework": control.framework.name,
                    "control_ref": control.ref_code,
                    "control": control.name,
                    "category": control.category,
                    "ref": sub.subcontrol.ref_code,
                    "name": sub.subcontrol.name,
                    "same_as_control": (sub.subcontrol.name or "").strip().lower()
                    == (control.name or "").strip().lower(),
                    "applicable": bool(sub.is_applicable),
                    "implemented": sub.implemented or 0,
                    "implementation": sub.implementation_status(),
                    "justification": justification,
                    "owner": _email(sub.owner_id, emails),
                    "evidence": sub.evidence.count(),
                    "ticket_number": sub.ticket_number,
                    "exceptions": [
                        e for e in exceptions if e["state"] in ("active", "expired", "submitted")
                    ],
                    "risks": sub.risks.count(),
                }
            )
    summary = {
        "total": len(rows),
        "applicable": sum(1 for r in rows if r["applicable"]),
        "not_applicable": sum(1 for r in rows if not r["applicable"]),
        "fully_implemented": sum(
            1 for r in rows if r["applicable"] and r["implemented"] == 100
        ),
        "partially_implemented": sum(
            1 for r in rows if r["applicable"] and 0 < r["implemented"] < 100
        ),
        "not_implemented": sum(1 for r in rows if r["applicable"] and not r["implemented"]),
        "with_active_exception": sum(
            1 for r in rows if any(e["state"] == "active" for e in r["exceptions"])
        ),
        "without_justification": sum(
            1 for r in rows if not r["applicable"] and not r["justification"]
        ),
    }
    return jsonify(
        {
            "project": project.name,
            "tenant": project.tenant.name,
            "frameworks": sorted({r["framework"] for r in rows}),
            "summary": summary,
            "rows": rows,
        }
    )


RISK_LEVELS = ["very high", "high", "low", "very low", "unknown"]


@api.route("/tenants/<string:tid>/reports/overview", methods=["GET"])
@login_required
def get_report_overview_for_tenant(tid):
    """
    Data for the organisation reports (Gaps / Risks / Exceptions) over the
    projects the user selects. Only projects the user may open are used, so a
    security manager or project member reports on what he can see and the CISO
    on everything.

    query: projects  comma list of project ids (empty = every project the user can open)
           org       include organisation level risks and exceptions (default 1)
    """
    result = Authorizer(current_user).can_user_access_tenant(tid)
    tenant = result["extra"]["tenant"]
    authorizer = Authorizer(current_user)

    accessible = {
        p.id: p
        for p in models.Project.query.filter(models.Project.tenant_id == tenant.id).all()
        if authorizer._can_user_access_project(p)
    }
    project_list = sorted(
        [{"id": p.id, "name": p.name} for p in accessible.values()],
        key=lambda x: x["name"].lower(),
    )
    wanted = [x for x in (request.args.get("projects") or "").split(",") if x]
    selected = (
        {pid: accessible[pid] for pid in wanted if pid in accessible}
        if wanted
        else dict(accessible)
    )
    include_org = request.args.get("org", "1") not in ("0", "false", "no")
    today = datetime.utcnow().date()
    emails = {}

    # -- exceptions: the project's own and organisation level ones that hit a selected project
    from .exceptions import _visible_tenant_exceptions, _with_links

    visible = _visible_tenant_exceptions(tenant)
    exception_items = []
    for item, exc in zip(_with_links(visible), visible):
        if exc.project_id:
            if exc.project_id in selected:
                exception_items.append((item, exc))
        elif include_org:
            projects = {link.get("project_id") for link in item["links"]}
            if not projects or projects & set(selected):
                exception_items.append((item, exc))

    # -- risks (only for users with the risk module)
    risks = None
    if authorizer._can_user_access_risk_module(tenant):
        query = models.RiskRegister.query.filter(models.RiskRegister.tenant_id == tenant.id)
        risk_objects = [
            r
            for r in query.all()
            if (r.project_id in selected) or (include_org and not r.project_id)
        ]
        ids = [r.id for r in risk_objects]
        links = models.bulk_risk_links(ids, can_access=authorizer._can_user_access_project)
        linked = models.bulk_risk_exceptions(ids, can_read=authorizer._can_user_read_exception)
        risks = []
        for risk in risk_objects:
            item = risk.as_dict()
            item.pop("comments", None)
            item["links"] = links.get(risk.id, [])
            item["exceptions"] = linked.get(risk.id, [])
            item["assignee_email"] = _email(risk.assignee, emails)
            risks.append(item)

    # -- gaps and a summary per project (evidence and open risks counted in bulk)
    psc_ids = models.db.session.query(models.ProjectSubControl.id).filter(
        models.ProjectSubControl.project_id.in_(list(selected) or [""])
    )
    evidence_count = dict(
        models.db.session.query(
            models.EvidenceAssociation.control_id, func.count(models.EvidenceAssociation.id)
        )
        .filter(models.EvidenceAssociation.control_id.in_(psc_ids))
        .group_by(models.EvidenceAssociation.control_id)
        .all()
    )
    open_risk_count = dict(
        models.db.session.query(models.RiskAssociation.control_id, func.count(models.RiskRegister.id))
        .join(models.RiskRegister, models.RiskRegister.id == models.RiskAssociation.risk_id)
        .filter(models.RiskAssociation.control_id.in_(psc_ids))
        .filter(~models.RiskRegister.status.in_(models.RiskRegister.CLOSED_STATUSES))
        .group_by(models.RiskAssociation.control_id)
        .all()
    )
    summaries = []
    gaps = []
    without_justification = []
    for project in sorted(selected.values(), key=lambda p: p.name.lower()):
        counts = {
            "subcontrols": 0, "applicable": 0, "not_applicable": 0, "without_justification": 0,
            "implemented": 0, "partially_implemented": 0, "not_implemented": 0,
            "with_evidence": 0, "gaps": 0,
        }
        frameworks = set()
        p_controls = project.controls.all()
        per_control_implemented, per_control_evidence = [], []
        for p_control in p_controls:
            control = p_control.control
            applicable_subs = [(x.implemented or 0, evidence_count.get(x.id, 0)) for x in p_control.subcontrols.all() if x.is_applicable]
            if applicable_subs:
                per_control_implemented.append(round(sum(i for i, _ in applicable_subs) / len(applicable_subs)))
                per_control_evidence.append(round(100 * sum(1 for _, e in applicable_subs if e) / len(applicable_subs)))
            frameworks.add(control.framework.name)
            for sub in p_control.subcontrols.all():
                counts["subcontrols"] += 1
                if not sub.is_applicable:
                    counts["not_applicable"] += 1
                    if not ((sub.context or "").strip() or (sub.notes or "").strip()):
                        counts["without_justification"] += 1
                        without_justification.append(
                            {
                                "project": project.name,
                                "framework": control.framework.name,
                                "ref": sub.subcontrol.ref_code,
                                "name": sub.subcontrol.name,
                                "owner": _email(sub.owner_id, emails),
                            }
                        )
                    continue
                implemented = sub.implemented or 0
                evidence = evidence_count.get(sub.id, 0)
                counts["applicable"] += 1
                if evidence:
                    counts["with_evidence"] += 1
                if implemented >= 100:
                    counts["implemented"] += 1
                elif implemented:
                    counts["partially_implemented"] += 1
                else:
                    counts["not_implemented"] += 1
                if implemented >= 100 and evidence:
                    continue
                counts["gaps"] += 1
                active = [
                    e.title for e in sub.exceptions.all() if e.state(today) == "active"
                ]
                gaps.append(
                    {
                        "project": project.name,
                        "project_id": project.id,
                        "framework": control.framework.name,
                        "control_ref": control.ref_code,
                        "control": control.name,
                        "ref": sub.subcontrol.ref_code,
                        "name": sub.subcontrol.name,
                        "implemented": implemented,
                        "implementation": sub.implementation_status(),
                        "evidence": evidence,
                        "owner": _email(sub.owner_id, emails),
                        "open_risks": open_risk_count.get(sub.id, 0),
                        "exceptions": active,
                        "ticket_number": sub.ticket_number,
                    }
                )
        project_exceptions = models.PolicyException.summarize(
            [
                e
                for item, e in exception_items
                if e.project_id == project.id
                or (not e.project_id and project.id in {l["project_id"] for l in item["links"]})
            ]
        )
        open_risks = {level: 0 for level in RISK_LEVELS}
        overdue = 0
        for risk in risks or []:
            if risk.get("project_id") == project.id and risk["status"] not in models.RiskRegister.CLOSED_STATUSES:
                open_risks[risk["risk"] if risk["risk"] in RISK_LEVELS else "unknown"] += 1
                overdue += 1 if risk["review_overdue"] else 0
        summaries.append(
            {
                "id": project.id,
                "name": project.name,
                "frameworks": sorted(frameworks),
                **counts,
                # computed like the project summary page: averaged per control
                "implemented_pct": round(sum(per_control_implemented) / len(p_controls)) if p_controls else 0,
                "evidence_pct": round(sum(per_control_evidence) / len(p_controls)) if p_controls else 0,
                "open_risks": open_risks if risks is not None else None,
                "review_overdue": overdue if risks is not None else None,
                "exceptions": {
                    "active": project_exceptions["by_state"]["active"],
                    "submitted": project_exceptions["by_state"]["submitted"],
                    "expired": project_exceptions["by_state"]["expired"],
                    "expiring_soon": project_exceptions["expiring_soon"],
                },
            }
        )
    gaps.sort(key=lambda g: (g["project"].lower(), g["framework"], _ref_key(g["ref"])))

    return jsonify(
        {
            "tenant": tenant.name,
            "project_list": project_list,
            "selected": [p["id"] for p in summaries],
            "include_org": include_org,
            "projects": summaries,
            "gaps": gaps,
            "without_justification": without_justification,
            "risks": risks,
            "exceptions": [item for item, _ in exception_items],
            "exception_summary": models.PolicyException.summarize([e for _, e in exception_items]),
        }
    )


def _ref_key(ref):
    """'A.5.10' sorts after 'A.5.9'."""
    parts = []
    for part in str(ref or "").replace("-", ".").split("."):
        parts.append((0, int(part), "") if part.isdigit() else (1, 0, part.lower()))
    return parts
