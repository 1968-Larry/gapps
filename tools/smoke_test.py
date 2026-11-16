"""
Smoke test: logs in as the default admin and requests every GET page and API
endpoint the app has, with ids taken from the demo tenant, then fetches every
/static file those pages reference. Fails on any 5xx, exception or missing
static file. Used by the CI workflow after dependency updates.

    python3 tools/seed_demo.py --projects 2 --frameworks soc2   # demo data first
    python3 tools/smoke_test.py [--tenant demo] [-v]

Requests that could change data or send mail are skipped (see SKIP).
"""
import argparse
import os
import re
import sys
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db  # noqa: E402
from app.models import (  # noqa: E402
    Control,
    Framework,
    PolicyException,
    Project,
    ProjectControl,
    ProjectEvidence,
    ProjectPolicy,
    ProjectSubControl,
    RiskRegister,
    Tenant,
    User,
)

# Endpoint paths containing these words are never requested
SKIP = re.compile(r"logout|delete|/token|email|reset|/file\b|reports/<path|download|jobs|deployments")
STATIC_RE = re.compile(r"""(?:src|href)=["'](/static/[^"'?#]+)""")


def first(model, **filters):
    q = model.query
    for col, value in filters.items():
        if value is not None and hasattr(model, col):
            q = q.filter(getattr(model, col) == value)
    row = q.first()
    return row.id if row else None


def resolve_ids(tenant):
    project = Project.query.filter_by(tenant_id=tenant.id).first()
    pid = project.id if project else None
    admin = User.query.filter_by(email=os.environ.get("DEFAULT_EMAIL", "admin@example.com")).first()
    return {
        "tenants": tenant.id,
        "projects": pid,
        "users": admin.id if admin else None,
        "exceptions": first(PolicyException, project_id=pid),
        "risks": first(RiskRegister, project_id=pid),
        "frameworks": first(Framework, tenant_id=tenant.id),
        "evidence": first(ProjectEvidence, project_id=pid),
        "policies": first(ProjectPolicy, project_id=pid),
        "subcontrols": first(ProjectSubControl, project_id=pid),
        "project_controls": first(ProjectControl, project_id=pid),
        "controls": first(Control, tenant_id=tenant.id),
    }


def fill(rule, ids):
    """URL for a rule with its <params> filled in, or None when an id is unknown."""
    parts = rule.rule.split("/")
    in_project = False
    out = []
    for i, part in enumerate(parts):
        if part == "projects":
            in_project = True
        m = re.fullmatch(r"<(?:[a-z]+:)?([a-z_]+)>", part)
        if not m:
            out.append(part)
            continue
        prev = parts[i - 1] if i else ""
        key = "project_controls" if (prev == "controls" and in_project) else prev
        if prev == "users" or (prev == "matrix" or m.group(1) == "uid"):
            key = "users"
        value = ids.get(key)
        if value is None:
            return None
        out.append(str(value))
    return "/".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="demo")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument(
        "--clear-pwd-change",
        action="store_true",
        help="clear 'must change password' on the admin first (test databases only)",
    )
    args = ap.parse_args()

    app = create_app(os.getenv("FLASK_CONFIG") or "default")
    app.config["TESTING"] = True
    # The test client talks plain http; a Secure cookie would never be sent back
    app.config["SESSION_COOKIE_SECURE"] = False
    failures, checked, skipped = [], 0, 0
    with app.app_context():
        tenant = Tenant.query.filter_by(name=args.tenant).first() or Tenant.query.first()
        if not tenant:
            sys.exit("No tenant found - run tools/seed_demo.py first")
        if args.clear_pwd_change:
            admin = User.query.filter_by(
                email=os.environ.get("DEFAULT_EMAIL", "admin@example.com")
            ).first()
            if admin and admin.is_password_change_required():
                admin.last_password_change = datetime.utcnow()
                db.session.commit()
        ids = resolve_ids(tenant)
        print(f"Tenant {tenant.name}: " + ", ".join(f"{k}={v}" for k, v in ids.items()))

        client = app.test_client()
        r = client.post(
            "/login",
            data={
                "email": os.environ.get("DEFAULT_EMAIL", "admin@example.com"),
                "password": os.environ.get("DEFAULT_PASSWORD", "admin1234567"),
            },
        )
        check = client.get("/api/v1/session")
        if r.status_code >= 400 or check.status_code != 200:
            jar = getattr(client, "_cookies", {})
            sys.exit(
                f"Login failed: POST /login -> {r.status_code} {r.headers.get('Location')}, "
                f"GET /api/v1/session -> {check.status_code} {check.headers.get('Location')}\n"
                f"  Set-Cookie: {r.headers.getlist('Set-Cookie')}\n"
                f"  client cookies: {[(k, getattr(c, 'value', c)[:20]) for k, c in dict(jar).items()]}"
            )

        static_refs = set()
        rules = sorted(app.url_map.iter_rules(), key=lambda r: r.rule)
        for rule in rules:
            if "GET" not in rule.methods or rule.endpoint == "static" or SKIP.search(rule.rule):
                skipped += 1
                continue
            url = fill(rule, ids)
            if url is None:
                skipped += 1
                if args.verbose:
                    print(f"  skip  {rule.rule} (no id)")
                continue
            checked += 1
            try:
                resp = client.get(url)
            except Exception as e:  # an exception in the view = a 500
                failures.append(f"{url}: {type(e).__name__}: {e}")
                continue
            if resp.status_code >= 500:
                failures.append(f"{url}: HTTP {resp.status_code}")
            if args.verbose or resp.status_code >= 500:
                print(f"  {resp.status_code}  {url}")
            if resp.mimetype == "text/html":
                static_refs.update(STATIC_RE.findall(resp.get_data(as_text=True)))

        for ref in sorted(static_refs):
            resp = client.get(ref)
            if resp.status_code != 200:
                failures.append(f"{ref}: HTTP {resp.status_code} (referenced by a page)")
            resp.close()

    print(f"\n{checked} endpoints requested, {skipped} skipped, {len(static_refs)} static files checked")
    if failures:
        print(f"\n{len(failures)} FAILURES:")
        for f in failures:
            print("  " + f)
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()
