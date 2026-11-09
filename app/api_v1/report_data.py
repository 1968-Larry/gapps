"""
Data for the reports that are built in the browser (jsPDF / CSV).

    GET /api/v1/projects/<pid>/reports/soa   Statement of Applicability rows
"""
from flask import jsonify
from flask_login import current_user

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


def _ref_key(ref):
    """'A.5.10' sorts after 'A.5.9'."""
    parts = []
    for part in str(ref or "").replace("-", ".").split("."):
        parts.append((0, int(part), "") if part.isdigit() else (1, 0, part.lower()))
    return parts
