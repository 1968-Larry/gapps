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
import io
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

    # 4. tokens: an API token is not a reset token and the other way round, and
    #    a reset token stops working once the password has changed
    with app.app_context():
        user = User.query.filter_by(email=LOCK_USER).first()
        api_token = user.generate_auth_token(600)
        reset_token = user.generate_reset_token(600)
        checks = {
            "API token accepted as API token": bool(User.verify_auth_token(api_token)),
            "reset token accepted for reset": bool(User.verify_reset_token(reset_token)),
            "API token refused for reset": not User.verify_reset_token(api_token),
            "reset token refused as API token": not User.verify_auth_token(reset_token),
            "reset token refused as invite": not User.verify_invite_token(reset_token),
        }
        user.set_password("Another-Password-2026!", set_pwd_change=True)
        db.session.commit()
        checks["reset token refused after password change"] = not User.verify_reset_token(
            reset_token
        )
        ensure_user(LOCK_USER, OUTSIDER_PASSWORD, with_tenant=False)
        user.set_password(OUTSIDER_PASSWORD, set_pwd_change=True)
        db.session.commit()
    for name, ok in checks.items():
        if not ok:
            failures.append(f"tokens: {name} failed")
    print(f"Tokens: {sum(checks.values())}/{len(checks)} checks passed")

    # 5. security headers on a page of a logged in user
    resp = client.get("/projects")
    want = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "SAMEORIGIN",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Cache-Control": "no-store",
    }
    for header, value in want.items():
        if resp.headers.get(header) != value:
            failures.append(f"header {header}: {resp.headers.get(header)!r}, expected {value!r}")
    if not (
        resp.headers.get("Content-Security-Policy")
        or resp.headers.get("Content-Security-Policy-Report-Only")
    ):
        failures.append("no Content-Security-Policy header")
    print("Headers: checked")

    # 6. API token lifetime and revocation
    resp = client.get("/api/v1/token?expiration=0")
    max_days = float(app.config.get("API_TOKEN_MAX_DAYS") or 0)
    got = (resp.get_json() or {}).get("expires_in")
    if max_days and got != int(max_days * 86400):
        failures.append(f"token: expiration=0 gave expires_in={got}, expected the {max_days} day maximum")
    token = (resp.get_json() or {}).get("token")
    api = app.test_client()
    before = api.get("/api/v1/session", headers={"token": token}).status_code
    client.delete("/api/v1/token")
    after = api.get("/api/v1/session", headers={"token": token}).status_code
    if before != 200 or after == 200:
        failures.append(f"token revocation: before {before}, after revoke {after}")
    else:
        print("Tokens: lifetime capped, revocation works")

    # 7. uploads: file type and size (as the admin, who may add evidence)
    admin = app.test_client()
    login(admin, os.environ.get("DEFAULT_EMAIL", "admin@example.com"),
          os.environ.get("DEFAULT_PASSWORD", "admin1234567"))
    url = f"/api/v1/projects/{ids['projects']}/evidence"

    def upload(name, size=10):
        data = {"name": f"upload test {name}", "file": (io.BytesIO(b"x" * size), name)}
        return admin.post(url, data=data, content_type="multipart/form-data").status_code

    if upload("evil.html") != 415:
        failures.append("upload: .html was not refused with 415")
    if upload(f"ok-{datetime.utcnow().timestamp():.0f}.txt") != 200:
        failures.append("upload: .txt was refused")
    app.config["MAX_CONTENT_LENGTH"] = 1024
    if upload("big.txt", 4096) != 413:
        failures.append("upload: a too large file was not refused with 413")
    app.config["MAX_CONTENT_LENGTH"] = int(float(app.config.get("UPLOAD_MAX_MB") or 50) * 1024 * 1024)
    print("Uploads: checked")

    # 8. client IP behind a trusted proxy (TRUSTED_PROXIES)
    app.config["TRUSTED_PROXIES"] = "172.16.0.0/12"
    cases = [
        ("172.18.0.1", "1.2.3.4, 203.0.113.7", "203.0.113.7"),  # spoofed left part ignored
        ("198.51.100.9", "1.2.3.4", "198.51.100.9"),            # not a proxy: header ignored
    ]
    for peer, xff, want in cases:
        resp = admin.get(
            "/api/v1/admin/client-ip",
            headers={"X-Forwarded-For": xff},
            environ_base={"REMOTE_ADDR": peer},
        )
        got = (resp.get_json() or {}).get("client_ip_used")
        if got != want:
            failures.append(f"client ip: from {peer} with X-Forwarded-For '{xff}' got {got}, expected {want}")
    app.config["TRUSTED_PROXIES"] = ""
    print("Client IP: checked")

    # 9. access overview (Instance users > Access) and the access report
    with app.app_context():
        outsider_id = User.query.filter_by(email=OUTSIDER).first().id
    data = admin.get(f"/api/v1/users/{outsider_id}/access").get_json() or {}
    tenants = {t["name"]: t for t in data.get("tenants", [])}
    if not tenants.get("outsider", {}).get("owner"):
        failures.append(f"access overview: outsider should own tenant 'outsider', got {list(tenants)}")
    if args.tenant in tenants:
        failures.append("access overview: outsider wrongly shown in the demo tenant")
    if client.get(f"/api/v1/users/{outsider_id}/access").status_code not in (401, 403, 404):
        failures.append("access overview: a normal user could read it")
    report = admin.get("/api/v1/admin/access-report")
    text = report.get_data(as_text=True)
    if report.status_code != 200 or OUTSIDER not in text or ";" not in text.splitlines()[0]:
        failures.append(f"access report: HTTP {report.status_code}, outsider row or header missing")
    print("Access overview: checked")

    if failures:
        print(f"\n{len(failures)} ACCESS PROBLEMS:")
        for f in failures:
            print("  " + f)
        sys.exit(1)
    print("\nAccess control test OK")


if __name__ == "__main__":
    main()
