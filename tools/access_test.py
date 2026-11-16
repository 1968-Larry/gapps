"""
Access control test (OWASP A01). Run after tools/seed_demo.py on a TEST database.

1. Anonymous: every GET endpoint without a session must answer 401/403/404 or
   redirect to the login page, except the public pages in PUBLIC.
2. Other tenant: a normal user with their own tenant (created here, "outsider")
   requests every GET endpoint with the ids of the demo tenant. Anything other
   than 401/403/404 (or a redirect away) is reported: that user must not see
   the demo tenant's data.
3. Brute force: wrong passwords until the account is locked (LOGIN_MAX_FAILED),
   then the right password must be refused too.

    python3 tools/access_test.py [--tenant demo]
"""
import argparse
import os
import re
import sys
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db  # noqa: E402
from app.models import Tenant, User  # noqa: E402
from smoke_test import SKIP, fill, resolve_ids  # noqa: E402

OUTSIDER = "outsider@access-test.example.com"
OUTSIDER_PASSWORD = "Outsider-Password-2026!"
LOCK_USER = "lockme@access-test.example.com"

# Reachable without a session (the login pages and their helpers)
PUBLIC = re.compile(
    r"^/(login|register|reset-password|set-password|logout|confirm-email|get-started"
    r"|accept|magic-login|oidc/|session/status|api/v1/health|static/)"
)

# Endpoints any logged in user may read, whatever the tenant (own profile and the
# like). Keep this list short and explain every line.
ALLOWED_FOR_ANY_USER = {}


def ensure_user(email, password, with_tenant):
    user = User.query.filter_by(email=email).first()
    if not user:
        user = User.add(
            email,
            password=password,
            confirmed=True,
            return_user_object=True,
        )
    user.last_password_change = datetime.utcnow()
    user.failed_login_count = 0
    user.locked_until = None
    db.session.commit()
    if with_tenant and not Tenant.query.filter_by(name="outsider").first():
        Tenant.create(user, "outsider", email)
    return user


def login(client, email, password):
    return client.post("/login", data={"email": email, "password": password})


def is_denied(resp):
    if resp.status_code in (401, 403, 404):
        return True
    if resp.status_code in (301, 302, 303, 307, 308):
        loc = resp.headers.get("Location", "")
        return "/login" in loc or "/set-password" in loc or loc.rstrip("/") in ("", "/")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="demo")
    args = ap.parse_args()

    app = create_app(os.getenv("FLASK_CONFIG") or "default")
    app.config["TESTING"] = True
    app.config["SESSION_COOKIE_SECURE"] = False
    failures = []

    # Test data in its own app context. The requests below must NOT run inside
    # it: Flask-Login caches the logged in user on the app context (g), so a
    # shared context would make every client look like the last one logged in.
    with app.app_context():
        tenant = Tenant.query.filter_by(name=args.tenant).first()
        if not tenant:
            sys.exit("No demo tenant - run tools/seed_demo.py first")
        ids = resolve_ids(tenant)
        ensure_user(OUTSIDER, OUTSIDER_PASSWORD, with_tenant=True)
        ensure_user(LOCK_USER, OUTSIDER_PASSWORD, with_tenant=False)
        limit = int(app.config.get("LOGIN_MAX_FAILED") or 0)

    rules = [
        r
        for r in sorted(app.url_map.iter_rules(), key=lambda r: r.rule)
        if "GET" in r.methods and r.endpoint != "static" and not SKIP.search(r.rule)
    ]

    # 1. anonymous
    anon = app.test_client()
    checked = 0
    for rule in rules:
        url = fill(rule, ids)
        if url is None or PUBLIC.search(rule.rule):
            continue
        checked += 1
        resp = anon.get(url)
        if not is_denied(resp):
            failures.append(f"anonymous: {url} -> {resp.status_code}")
    print(f"Anonymous: {checked} endpoints checked")

    # 2. a user of another tenant
    client = app.test_client()
    r = login(client, OUTSIDER, OUTSIDER_PASSWORD)
    if client.get("/api/v1/session").status_code != 200:
        sys.exit(f"outsider login failed ({r.status_code} {r.headers.get('Location')})")
    checked = 0
    for rule in rules:
        if "<" not in rule.rule or PUBLIC.search(rule.rule):
            continue  # only endpoints that take an id of the demo tenant
        url = fill(rule, ids)
        if url is None:
            continue
        checked += 1
        try:
            resp = client.get(url)
        except Exception as e:
            failures.append(f"other tenant: {url} -> {type(e).__name__}: {e}")
            continue
        if not is_denied(resp) and rule.rule not in ALLOWED_FOR_ANY_USER:
            body = resp.get_data(as_text=True)[:120].replace("\n", " ")
            failures.append(f"other tenant: {url} -> {resp.status_code} {body}")
    print(f"Other tenant: {checked} endpoints checked")

    # 3. brute force lock
    if limit:
        bf = app.test_client()
        codes = [login(bf, LOCK_USER, "wrong-password-123456").status_code for _ in range(limit)]
        last = login(bf, LOCK_USER, OUTSIDER_PASSWORD)
        if bf.get("/api/v1/session").status_code == 200:
            failures.append(
                f"brute force: right password accepted after {limit} wrong ones "
                f"(answers {codes}, then {last.status_code})"
            )
        else:
            print(f"Brute force: account locked after {limit} wrong passwords")
        with app.app_context():
            ensure_user(LOCK_USER, OUTSIDER_PASSWORD, with_tenant=False)  # unlock again

    if failures:
        print(f"\n{len(failures)} ACCESS PROBLEMS:")
        for f in failures:
            print("  " + f)
        sys.exit(1)
    print("\nAccess control test OK")


if __name__ == "__main__":
    main()
