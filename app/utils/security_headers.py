"""
HTTP security headers (OWASP Secure Headers / ASVS V14.4) and a start-up check
of SECRET_KEY. The Content-Security-Policy is set in vendor_assets.py, because
it depends on ASSET_MODE.
"""
from flask import request
from flask_login import current_user

INSECURE_KEYS = {"", "change_secret_key", "changeme", "secret", "dev"}

PERMISSIONS_POLICY = (
    "camera=(), microphone=(), geolocation=(), payment=(), usb=(), "
    "magnetometer=(), gyroscope=(), accelerometer=()"
)


def check_secret_key(app):
    """Refuse to run a production config with the default or an empty key: anyone
    who knows it can forge session cookies and tokens (log in as any user)."""
    if app.debug or app.testing:
        return
    key = app.config.get("SECRET_KEY") or ""
    if key in INSECURE_KEYS:
        raise RuntimeError(
            "SECRET_KEY is not set (or is the default). Set a long random value in "
            ".env, for example: python3 -c \"import secrets; print(secrets.token_hex(32))\""
        )
    if len(key) < 32:
        app.logger.warning("SECRET_KEY is shorter than 32 characters; use a longer random value")


def init_security_headers(app):
    check_secret_key(app)
    hsts_max_age = int(app.config.get("HSTS_MAX_AGE") or 0)
    https = app.config.get("SCHEME") == "https"

    @app.after_request
    def _security_headers(response):
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "SAMEORIGIN")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
        h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if https and hsts_max_age:
            h.setdefault("Strict-Transport-Security", f"max-age={hsts_max_age}")
        # Pages and API answers for a logged in user must not end up in a shared
        # or browser cache (back button after logout, proxies)
        if request.endpoint != "static" and current_user.is_authenticated:
            h["Cache-Control"] = "no-store"
            h["Pragma"] = "no-cache"
        return response
