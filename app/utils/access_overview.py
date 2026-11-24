"""
What a user can reach: instance level, organisations (tenants) with roles, and
projects - explicit project memberships plus the access some tenant roles give
without a membership (owner/admin: every project, CISO: reads every project).

Used by GET /api/v1/users/<id>/access (the Access tab under Instance users) and
GET /api/v1/admin/access-report (CSV for access reviews).
"""
from app.models import Project, ProjectMember, Role, Tenant

# Tenant roles that reach projects without being a member of them
IMPLICIT_PROJECT_ACCESS = {
    "admin": "every project (tenant admin)",
    "ciso": "reads every project (CISO)",
}


def role_label(name):
    return Role.ROLE_LABELS.get(name, name)


def user_access(user):
    tenants = {}

    def tenant_entry(tenant):
        if tenant.id not in tenants:
            tenants[tenant.id] = {
                "id": tenant.id,
                "name": tenant.name,
                "owner": tenant.owner_id == user.id,
                "member": False,
                "roles": [],
                "projects": [],
                "implicit": [],
            }
        return tenants[tenant.id]

    for membership in user.memberships.all():
        if not membership.tenant:
            continue
        entry = tenant_entry(membership.tenant)
        entry["member"] = True
        entry["roles"] = sorted(
            ({"name": r.name, "label": role_label(r.name)} for r in membership.roles.all()),
            key=lambda r: r["name"],
        )

    for tenant in Tenant.query.filter(Tenant.owner_id == user.id).all():
        tenant_entry(tenant)

    for pm in ProjectMember.query.filter(ProjectMember.user_id == user.id).all():
        project = Project.query.get(pm.project_id)
        if not project or not project.tenant:
            continue
        tenant_entry(project.tenant)["projects"].append(
            {"id": project.id, "name": project.name, "access_level": pm.access_level}
        )

    for entry in tenants.values():
        names = {r["name"] for r in entry["roles"]}
        if entry["owner"]:
            entry["implicit"].append("every project (tenant owner)")
        for role, text in IMPLICIT_PROJECT_ACCESS.items():
            if role in names and text not in entry["implicit"]:
                entry["implicit"].append(text)
        entry["projects"].sort(key=lambda p: p["name"].lower())

    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "name": " ".join(x for x in (user.first_name, user.last_name) if x),
            "is_active": bool(user.is_active),
            "super": bool(user.super),
            "login_count": user.login_count or 0,
            "date_added": user.date_added.isoformat() if user.date_added else None,
            "locked": user.is_login_locked(),
            "tokens_revoked_at": user.tokens_valid_after.isoformat()
            if user.tokens_valid_after
            else None,
        },
        "instance": "full access to every tenant (instance admin)" if user.super else None,
        "tenants": sorted(tenants.values(), key=lambda t: t["name"].lower()),
    }


def access_summary(access):
    """Short columns for the users list."""
    tenants = access["tenants"]
    roles = sorted({r["label"] for t in tenants for r in t["roles"]})
    return {
        "access_tenants": len(tenants),
        "access_roles": ", ".join(roles),
        "access_projects": sum(len(t["projects"]) for t in tenants),
    }


def access_report_rows(users):
    """One row per user x tenant x project, for Excel filtering."""
    header = [
        "email", "name", "active", "instance_admin", "tenant", "tenant_owner",
        "tenant_roles", "project", "project_access", "implicit_access",
    ]
    rows = [header]
    for user in users:
        access = user_access(user)
        u = access["user"]
        base = [u["email"], u["name"], u["is_active"], u["super"]]
        if not access["tenants"]:
            rows.append(base + ["", "", "", "", "", ""])
        for t in access["tenants"]:
            roles = ", ".join(r["label"] for r in t["roles"])
            implicit = "; ".join(t["implicit"])
            tenant_part = [t["name"], t["owner"], roles]
            if not t["projects"]:
                rows.append(base + tenant_part + ["", "", implicit])
            for p in t["projects"]:
                rows.append(base + tenant_part + [p["name"], p["access_level"], implicit])
    return rows
