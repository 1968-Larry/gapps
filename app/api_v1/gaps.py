from flask import jsonify, request
from flask_login import current_user
from sqlalchemy import func

from . import api
from app.models import (
    db,
    Control,
    EvidenceAssociation,
    Framework,
    Project,
    ProjectControl,
    ProjectSubControl,
    RiskAssociation,
    RiskRegister,
    SubControl,
    User,
)
from app.utils.authorizer import Authorizer
from app.utils.decorators import login_required

GAP_STATUSES = [
    "not_complete",
    "not_implemented",
    "partially_implemented",
    "implemented",
    "missing_evidence",
    "not_applicable",
    "all",
]


def _implementation(psc):
    if not psc.is_applicable:
        return "not_applicable"
    if not psc.implemented:
        return "not_implemented"
    if psc.implemented >= 100:
        return "implemented"
    return "partially_implemented"


def _matches(status_filter, implementation, has_evidence):
    applicable = implementation != "not_applicable"
    if status_filter == "all":
        return True
    if status_filter == "not_complete":
        return applicable and not (implementation == "implemented" and has_evidence)
    if status_filter == "missing_evidence":
        return applicable and not has_evidence
    return implementation == status_filter


def _ref_sort_key(ref):
    """natural order so that A.5.2 comes before A.5.10"""
    import re

    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", ref or "")]


@api.route("/tenants/<string:id>/gaps", methods=["GET"])
@login_required
def get_gaps_for_tenant(id):
    """
    Subcontrols across all projects the user can open, grouped by subcontrol
    (the same subcontrol in several projects ends up in one group) so that
    gaps shared by many projects are easy to find.

    query: status (see GAP_STATUSES, default not_complete), framework (id),
           min_projects (default 1), q (text in ref code / name)
    """
    result = Authorizer(current_user).can_user_access_tenant(id)
    tenant = result["extra"]["tenant"]
    authorizer = Authorizer(current_user)

    status_filter = request.args.get("status", "not_complete")
    if status_filter not in GAP_STATUSES:
        status_filter = "not_complete"
    framework_id = request.args.get("framework") or None
    try:
        min_projects = max(1, int(request.args.get("min_projects", 1)))
    except ValueError:
        min_projects = 1
    text = (request.args.get("q") or "").strip().lower()

    projects = {
        p.id: p
        for p in Project.query.filter(Project.tenant_id == tenant.id).all()
        if authorizer._can_user_access_project(p)
    }
    if not projects:
        return jsonify(
            {"groups": [], "frameworks": [], "totals": {}, "status": status_filter}
        )
    project_ids = list(projects.keys())

    query = (
        db.session.query(ProjectSubControl, SubControl, Control, Framework)
        .join(SubControl, SubControl.id == ProjectSubControl.subcontrol_id)
        .join(ProjectControl, ProjectControl.id == ProjectSubControl.project_control_id)
        .join(Control, Control.id == ProjectControl.control_id)
        .join(Framework, Framework.id == Control.framework_id)
        .filter(ProjectSubControl.project_id.in_(project_ids))
    )
    if framework_id:
        query = query.filter(Framework.id == framework_id)
    rows = query.all()

    psc_ids = db.session.query(ProjectSubControl.id).filter(
        ProjectSubControl.project_id.in_(project_ids)
    )
    with_evidence = {
        r[0]
        for r in db.session.query(EvidenceAssociation.control_id)
        .filter(EvidenceAssociation.control_id.in_(psc_ids))
        .distinct()
        .all()
    }
    open_risks = dict(
        db.session.query(RiskAssociation.control_id, func.count(RiskRegister.id))
        .join(RiskRegister, RiskRegister.id == RiskAssociation.risk_id)
        .filter(RiskAssociation.control_id.in_(psc_ids))
        .filter(~RiskRegister.status.in_(RiskRegister.CLOSED_STATUSES))
        .group_by(RiskAssociation.control_id)
        .all()
    )
    owner_ids = {r[0].owner_id for r in rows if r[0].owner_id}
    owners = (
        {u.id: u.email for u in User.query.filter(User.id.in_(owner_ids)).all()}
        if owner_ids
        else {}
    )

    groups = {}
    frameworks = {}
    totals = {
        "subcontrols": 0,
        "gaps": 0,
        "not_implemented": 0,
        "partially_implemented": 0,
        "implemented": 0,
        "not_applicable": 0,
        "missing_evidence": 0,
    }
    for psc, sub, control, framework in rows:
        frameworks[framework.id] = framework.name
        implementation = _implementation(psc)
        has_evidence = psc.id in with_evidence
        group = groups.setdefault(
            sub.id,
            {
                "id": sub.id,
                "ref_code": sub.ref_code,
                "name": sub.name,
                "control": control.name,
                "control_ref_code": control.ref_code,
                "framework": framework.name,
                "framework_id": framework.id,
                "projects": 0,
                "gaps": 0,
                "not_implemented": 0,
                "partially_implemented": 0,
                "implemented": 0,
                "not_applicable": 0,
                "missing_evidence": 0,
                "items": [],
            },
        )
        group["projects"] += 1
        group[implementation] += 1
        if implementation != "not_applicable" and not has_evidence:
            group["missing_evidence"] += 1
        totals["subcontrols"] += 1
        totals[implementation] += 1
        if implementation != "not_applicable" and not has_evidence:
            totals["missing_evidence"] += 1

        if _matches(status_filter, implementation, has_evidence):
            group["gaps"] += 1
            project = projects[psc.project_id]
            group["items"].append(
                {
                    "id": psc.id,
                    "project_id": project.id,
                    "project": project.name,
                    "url": f"/projects/{project.id}",
                    "implementation": implementation,
                    "implemented": psc.implemented or 0,
                    "has_evidence": has_evidence,
                    "open_risks": open_risks.get(psc.id, 0),
                    "owner": owners.get(psc.owner_id) if psc.owner_id else None,
                    "ticket_number": psc.ticket_number,
                }
            )

    data = []
    for group in groups.values():
        if group["gaps"] == 0 or group["gaps"] < min_projects:
            continue
        if text and text not in f"{group['ref_code']} {group['name']} {group['control']}".lower():
            continue
        group["items"].sort(key=lambda x: x["project"].lower())
        data.append(group)
        totals["gaps"] += group["gaps"]
    data.sort(key=lambda g: (-g["gaps"], g["framework"], _ref_sort_key(g["ref_code"])))

    return jsonify(
        {
            "groups": data,
            "frameworks": sorted(
                [{"id": k, "name": v} for k, v in frameworks.items()],
                key=lambda x: x["name"].lower(),
            ),
            "totals": totals,
            "projects": len(projects),
            "status": status_filter,
        }
    )
