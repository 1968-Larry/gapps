"""
Deadlines page: dates to keep over the projects the user can open.

    GET /api/v1/tenants/<tid>/deadlines?projects=&owner=

Row kinds:
    subcontrol    planned end of an applicable sub-control
    risk_review   next review date of a risk (open risks; accepted risks are
                  sent with accepted=true, the page shows them on request)
    risk_due      due date of an open risk (not mitigated / accepted)
    exception     expiry date of an approved exception (active or expired)
Risks need access to the risk module. Risks and exceptions without a project
(organisation level) have project_id null. Same rules as the reminder mails.

Status per sub-control row (same "complete" as the project view: fully
implemented AND has evidence):
    done      complete
    overdue   not complete and planned end before today
    upcoming  not complete and planned end today or later
    no_date   no planned end set
Risk and exception rows are overdue (date passed, exception expired) or
upcoming. Status, type and date filtering is done in the browser.
"""
from datetime import datetime

from flask import jsonify, request
from flask_login import current_user

from . import api
from app import models, db
from app.utils.authorizer import Authorizer
from app.utils.decorators import login_required


@api.route("/tenants/<string:tid>/deadlines", methods=["GET"])
@login_required
def get_deadlines_for_tenant(tid):
    """
    query: projects  comma list of project ids (empty = every project the user can open)
           owner     "me" (default), a user id, or "all"
    """
    result = Authorizer(current_user).can_user_access_tenant(tid)
    tenant = result["extra"]["tenant"]
    authorizer = Authorizer(current_user)

    accessible = {
        p.id: p
        for p in models.Project.query.filter(models.Project.tenant_id == tenant.id).all()
        if authorizer._can_user_access_project(p)
    }
    wanted = [x for x in (request.args.get("projects") or "").split(",") if x]
    selected = [pid for pid in wanted if pid in accessible] if wanted else list(accessible)

    owner = request.args.get("owner") or "me"
    if owner == "me":
        owner = current_user.id

    PSC, SC = models.ProjectSubControl, models.SubControl
    PC, C = models.ProjectControl, models.Control
    rows, owners = [], {}
    if selected:
        query = (
            db.session.query(
                PSC.id,
                PSC.project_id,
                PSC.project_control_id,
                PSC.owner_id,
                PSC.implemented,
                PSC.planned_end,
                SC.name,
                SC.ref_code,
                C.name,
                C.ref_code,
            )
            .join(SC, SC.id == PSC.subcontrol_id)
            .join(PC, PC.id == PSC.project_control_id)
            .join(C, C.id == PC.control_id)
            .filter(PSC.project_id.in_(selected))
            .filter(PSC.is_applicable == True)  # noqa: E712
        )
        if owner != "all":
            query = query.filter(PSC.owner_id == owner)
        records = query.all()

        ids = [r[0] for r in records]
        with_evidence = set()
        for i in range(0, len(ids), 500):
            with_evidence.update(
                x[0]
                for x in db.session.query(models.EvidenceAssociation.control_id)
                .filter(models.EvidenceAssociation.control_id.in_(ids[i : i + 500]))
                .distinct()
            )

        owner_ids = {r[3] for r in records if r[3]}
        if owner_ids:
            owners = {
                u.id: u.email
                for u in models.User.query.filter(models.User.id.in_(owner_ids)).all()
            }

        today = datetime.utcnow().date()
        for (sid, pid, pcid, oid, implemented, planned_end, name, ref_code,
             control_name, control_ref) in records:
            complete = (implemented or 0) == 100 and sid in with_evidence
            if complete:
                status = "done"
            elif not planned_end:
                status = "no_date"
            elif planned_end < today:
                status = "overdue"
            else:
                status = "upcoming"
            rows.append(
                {
                    "kind": "subcontrol",
                    "id": sid,
                    "project_id": pid,
                    "project": accessible[pid].name,
                    "project_control_id": pcid,
                    "name": name,
                    "ref_code": ref_code,
                    "control": control_name,
                    "control_ref_code": control_ref,
                    "owner_id": oid,
                    "owner": owners.get(oid),
                    "implemented": implemented or 0,
                    "has_evidence": sid in with_evidence,
                    "planned_end": planned_end.isoformat() if planned_end else None,
                    "status": status,
                }
            )

    today = datetime.utcnow().date()
    owner_filter = None if owner == "all" else owner
    in_scope = lambda project_id: (project_id in selected) if project_id else True  # noqa: E731

    def person(user_id):
        if user_id and user_id not in owners:
            user = models.User.query.get(user_id)
            owners[user_id] = user.email if user else None
        return owners.get(user_id) if user_id else None

    def project_name(project_id):
        return accessible[project_id].name if project_id else "Organisation"

    # -- risks (only with access to the risk module)
    if authorizer._can_user_access_risk_module(tenant):
        R = models.RiskRegister
        query = (
            R.query.filter(R.tenant_id == tenant.id)
            .filter(R.enabled.isnot(False))
            .filter(R.status != "mitigated")
            .filter((R.review_date.isnot(None)) | (R.due_date.isnot(None)))
        )
        if owner_filter:
            query = query.filter(R.assignee == owner_filter)
        for risk in query.all():
            if not in_scope(risk.project_id):
                continue
            accepted = risk.status == "accepted"
            dates = [("risk_review", risk.review_date)]
            if not accepted:
                dates.append(("risk_due", risk.due_date))
            for kind, when in dates:
                if not when:
                    continue
                rows.append(
                    {
                        "kind": kind,
                        "id": risk.id,
                        "project_id": risk.project_id,
                        "project": project_name(risk.project_id),
                        "name": risk.title,
                        "level": risk.risk,
                        "risk_status": risk.status,
                        "accepted": accepted,
                        "owner_id": risk.assignee,
                        "owner": person(risk.assignee),
                        "planned_end": when.isoformat(),
                        "status": "overdue" if when < today else "upcoming",
                    }
                )

    # -- exceptions: approved ones with an expiry date that the user may read
    from .exceptions import _visible_tenant_exceptions

    for exc in _visible_tenant_exceptions(tenant):
        if exc.status != "approved" or not exc.expiry_date:
            continue
        if not in_scope(exc.project_id):
            continue
        if owner_filter and exc.assignee != owner_filter:
            continue
        state = exc.state(today)
        rows.append(
            {
                "kind": "exception",
                "id": exc.id,
                "project_id": exc.project_id,
                "project": project_name(exc.project_id),
                "name": exc.title,
                "level": exc.risk,
                "exc_state": state,
                "owner_id": exc.assignee,
                "owner": person(exc.assignee),
                "planned_end": exc.expiry_date.isoformat(),
                "status": "overdue" if state == "expired" else "upcoming",
            }
        )

    # People to pick in the owner filter: members of the projects the user can open
    people = {k: v for k, v in owners.items() if v}
    if accessible:
        member_ids = {
            x[0]
            for x in db.session.query(models.ProjectMember.user_id)
            .filter(models.ProjectMember.project_id.in_(list(accessible)))
            .distinct()
        }
        member_ids -= set(people)
        if member_ids:
            people.update(
                {
                    u.id: u.email
                    for u in models.User.query.filter(models.User.id.in_(member_ids)).all()
                }
            )
    people[current_user.id] = current_user.email

    return jsonify(
        {
            "today": today.isoformat(),
            "tenant_id": tenant.id,
            "risk_module": authorizer._can_user_access_risk_module(tenant),
            "me": current_user.id,
            "owner": owner,
            "projects": sorted(
                [{"id": p.id, "name": p.name} for p in accessible.values()],
                key=lambda x: x["name"].lower(),
            ),
            "people": sorted(
                [{"id": k, "email": v} for k, v in people.items()],
                key=lambda x: x["email"].lower(),
            ),
            "rows": rows,
        }
    )
