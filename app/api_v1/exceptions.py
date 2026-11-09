"""
Exceptions (deviations) API.

Mirrors the risk endpoints (list/create/update per project, history, comments,
links to sub-controls) and adds the approval flow:

    POST /exceptions/<id>/submit     draft/rejected -> submitted
    POST /exceptions/<id>/approve    submitted -> approved   (not by the requester)
    POST /exceptions/<id>/reject     submitted -> rejected   (reason required)
    POST /exceptions/<id>/close      any -> closed           (deviation fixed)
    POST /exceptions/<id>/reopen     closed -> draft
"""
from flask import jsonify, request
from flask_login import current_user

from . import api
from app import models, db
from app.utils.authorizer import Authorizer
from app.utils.decorators import login_required
from app.utils.audit import log_event


def _payload():
    return request.get_json(silent=True) or {}


def _with_links(exceptions):
    authorizer = Authorizer(current_user)
    links = models.bulk_exception_links(
        [e.id for e in exceptions], can_access=authorizer._can_user_access_project
    )
    data = []
    rights = {}  # per project: (can edit, can manage)
    for exc in exceptions:
        item = exc.as_dict()
        item["links"] = links.get(exc.id, [])
        if exc.project_id not in rights:
            if exc.project_id:
                rights[exc.project_id] = (
                    authorizer._can_user_edit_project(exc.project),
                    authorizer._can_user_manage_project(exc.project),
                )
            else:
                manage = authorizer._can_user_manage_risk(exc.tenant)
                rights[exc.project_id] = (manage, manage)
        item["can_edit"], item["can_manage"] = rights[exc.project_id]
        item["can_approve"] = authorizer._can_user_approve_exception(exc)
        # separation of duties: the requester never approves (unless allowed)
        item["is_requester"] = exc.requested_by == current_user.id
        data.append(item)
    return data


def _one(exc):
    return jsonify(_with_links([exc])[0])


def _log_decision(exc, event_name):
    log_event(
        event_name,
        tenant=exc.tenant_id,
        metadata={
            "model": "PolicyException",
            "id": exc.id,
            "label": exc.title[:120],
            "project": exc.project.name if exc.project_id else None,
            "risk": exc.risk,
            "expiry_date": exc.expiry_date.isoformat() if exc.expiry_date else None,
        },
    )


# --------------------------------------------------------------------------- #
# Project exceptions
# --------------------------------------------------------------------------- #
@api.route("/projects/<string:pid>/exceptions", methods=["GET"])
@login_required
def get_exceptions_for_project(pid):
    result = Authorizer(current_user).can_user_access_project(pid)
    project = result["extra"]["project"]
    exceptions = project.exceptions.order_by(models.PolicyException.date_added).all()
    return jsonify(_with_links(exceptions))


@api.route("/projects/<string:pid>/exceptions/summary", methods=["GET"])
@login_required
def get_exception_summary_for_project(pid):
    result = Authorizer(current_user).can_user_access_project(pid)
    return jsonify(result["extra"]["project"].exception_summary())


@api.route("/projects/<string:pid>/exceptions", methods=["POST"])
@login_required
def create_exception_for_project(pid):
    result = Authorizer(current_user).can_user_edit_project(pid)
    project = result["extra"]["project"]
    data = _payload()
    try:
        exc = project.create_exception(data, requested_by=current_user.id)
    except ValueError as e:
        db.session.rollback()
        return jsonify({"message": str(e)}), 400
    if subcontrols := data.get("subcontrols"):
        for sid in subcontrols if isinstance(subcontrols, list) else [subcontrols]:
            sub = Authorizer(current_user).can_user_manage_project_subcontrol(sid)
            sub["extra"]["subcontrol"].associate_with_exception(exc.id)
    if risks := data.get("risks"):
        exc.associate_with_risk(risks)
    if data.get("submit"):
        exc.submit(current_user.id)
    return _one(exc)


@api.route("/exception-settings", methods=["GET"])
@login_required
def get_exception_settings():
    return jsonify(models.PolicyException.settings())


# --------------------------------------------------------------------------- #
# One exception
# --------------------------------------------------------------------------- #
@api.route("/exceptions/<string:id>", methods=["GET"])
@login_required
def get_exception(id):
    result = Authorizer(current_user).can_user_read_exception(id)
    return _one(result["extra"]["exception"])


@api.route("/exceptions/<string:id>", methods=["PUT"])
@login_required
def update_exception(id):
    result = Authorizer(current_user).can_user_edit_exception(id)
    exc = result["extra"]["exception"]
    data = _payload()
    if "assignee" in data:
        if exc.status == "closed":
            return jsonify({"message": "A closed exception can not be changed"}), 400
        if exc.project_id:
            exc.assignee = exc.project.validate_risk_assignee(data.get("assignee"))
        else:
            exc.assignee = data.get("assignee") or None
    try:
        exc.update(data)
    except ValueError as e:
        db.session.rollback()
        return jsonify({"message": str(e)}), 400
    return _one(exc)


@api.route("/exceptions/<string:id>", methods=["DELETE"])
@login_required
def delete_exception(id):
    result = Authorizer(current_user).can_user_manage_exception(id)
    db.session.delete(result["extra"]["exception"])
    db.session.commit()
    return jsonify({"message": "ok"})


@api.route("/exceptions/<string:id>/submit", methods=["POST"])
@login_required
def submit_exception(id):
    result = Authorizer(current_user).can_user_edit_exception(id)
    exc = result["extra"]["exception"].submit(current_user.id, _payload().get("note"))
    _log_decision(exc, "exception_submitted")
    return _one(exc)


@api.route("/exceptions/<string:id>/approve", methods=["POST"])
@login_required
def approve_exception(id):
    result = Authorizer(current_user).can_user_approve_exception(id)
    exc = result["extra"]["exception"].approve(current_user.id, _payload().get("note"))
    _log_decision(exc, "exception_approved")
    return _one(exc)


@api.route("/exceptions/<string:id>/reject", methods=["POST"])
@login_required
def reject_exception(id):
    result = Authorizer(current_user).can_user_approve_exception(id)
    exc = result["extra"]["exception"].reject(current_user.id, _payload().get("note"))
    _log_decision(exc, "exception_rejected")
    return _one(exc)


@api.route("/exceptions/<string:id>/close", methods=["POST"])
@login_required
def close_exception(id):
    result = Authorizer(current_user).can_user_manage_exception(id)
    exc = result["extra"]["exception"].close(_payload().get("note"))
    _log_decision(exc, "exception_closed")
    return _one(exc)


@api.route("/exceptions/<string:id>/reopen", methods=["POST"])
@login_required
def reopen_exception(id):
    result = Authorizer(current_user).can_user_manage_exception(id)
    exc = result["extra"]["exception"].reopen(_payload().get("note"))
    return _one(exc)


@api.route("/exceptions/<string:id>/history", methods=["GET"])
@login_required
def get_history_for_exception(id):
    result = Authorizer(current_user).can_user_read_exception(id)
    exc = result["extra"]["exception"]
    entries = exc.history.order_by(models.ExceptionHistory.date_added.desc()).limit(500)
    return jsonify([entry.as_dict() for entry in entries])


@api.route("/exceptions/<string:id>/comments", methods=["POST"])
@login_required
def add_comment_for_exception(id):
    result = Authorizer(current_user).can_user_edit_exception(id)
    exc = result["extra"]["exception"]
    data = _payload()
    if not (data.get("message") or "").strip():
        return jsonify({"message": "empty comment"}), 400
    comment = models.ExceptionComment(
        message=data["message"], owner_id=current_user.id, tenant_id=exc.tenant_id
    )
    exc.comments.append(comment)
    db.session.commit()
    return jsonify(comment.as_dict())


# --------------------------------------------------------------------------- #
# Links: sub-controls and risks
# --------------------------------------------------------------------------- #
def _visible_links(subcontrols):
    authorizer = Authorizer(current_user)
    links = [
        models.subcontrol_link_info(sub)
        for sub in subcontrols
        if authorizer._can_user_access_project(sub.p_control.project)
    ]
    links.sort(key=lambda x: (x["project"], x["framework"], x["ref_code"] or ""))
    return links


@api.route("/exceptions/<string:id>/links", methods=["GET"])
@login_required
def get_links_for_exception(id):
    result = Authorizer(current_user).can_user_read_exception(id)
    return jsonify(_visible_links(result["extra"]["exception"].project_subcontrols.all()))


@api.route("/subcontrols/<string:sid>/associate-exception", methods=["PUT"])
@login_required
def associate_exception_with_subcontrol(sid):
    result = Authorizer(current_user).can_user_manage_project_subcontrol(sid)
    data = _payload()
    subcontrol = result["extra"]["subcontrol"]
    wanted = data.get("exception") or []
    if not isinstance(wanted, list):
        wanted = [wanted]
    if data.get("replace"):
        # the attach dialog sends the complete list: also remove what was unticked
        current = [e.id for e in subcontrol.exceptions.all()]
        removed = [eid for eid in current if eid not in wanted]
        if removed:
            subcontrol.disassociate_with_exception(removed)
    if wanted:
        subcontrol.associate_with_exception(wanted)
    return jsonify(subcontrol.as_dict())


@api.route("/subcontrols/<string:sid>/disassociate-exception", methods=["DELETE"])
@login_required
def disassociate_exception_with_subcontrol(sid):
    result = Authorizer(current_user).can_user_manage_project_subcontrol(sid)
    result["extra"]["subcontrol"].disassociate_with_exception(_payload().get("exception"))
    return jsonify(result["extra"]["subcontrol"].as_dict())


@api.route("/exceptions/<string:id>/risks", methods=["PUT"])
@login_required
def associate_risk_with_exception(id):
    result = Authorizer(current_user).can_user_edit_exception(id)
    exc = result["extra"]["exception"]
    risk_ids = _payload().get("risk") or []
    if not isinstance(risk_ids, list):
        risk_ids = [risk_ids]
    for rid in risk_ids:
        Authorizer(current_user).can_user_read_risk(rid)
    exc.associate_with_risk(risk_ids)
    return _one(exc)


@api.route("/exceptions/<string:id>/risks", methods=["DELETE"])
@login_required
def disassociate_risk_with_exception(id):
    result = Authorizer(current_user).can_user_edit_exception(id)
    exc = result["extra"]["exception"]
    exc.disassociate_with_risk(_payload().get("risk") or [])
    return _one(exc)


@api.route("/risks/<string:id>/exceptions", methods=["GET"])
@login_required
def get_exceptions_for_risk(id):
    result = Authorizer(current_user).can_user_read_risk(id)
    authorizer = Authorizer(current_user)
    data = []
    for exc in result["extra"]["risk"].exceptions.all():
        if exc.project_id and not authorizer._can_user_access_project(exc.project):
            continue
        data.append(exc.summary())
    return jsonify(data)
