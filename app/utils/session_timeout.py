"""
Idle and absolute session timeouts.

The session is Flask's signed cookie. At login we store the login time and the
time of the last request in it; every request checks both against
SESSION_IDLE_TIMEOUT_MINUTES and SESSION_ABSOLUTE_TIMEOUT_HOURS. The values are
signed with SECRET_KEY, so the client cannot change them.

Activity = any request from the logged in user, except the status endpoint the
page polls to show the warning dialog (that one must not keep the session alive).
Requests authenticated with the API "token" header are not session based and
are skipped.
"""
import time
from datetime import timedelta

from flask import current_app, flash, jsonify, redirect, request, session, url_for
from flask_login import current_user, logout_user

from app.utils.audit import log_event

LOGIN_AT = "_login_at"
LAST_SEEN = "_last_seen"

# Endpoints that are never counted as activity
PASSIVE_ENDPOINTS = {"auth.session_status"}


def _limits():
    cfg = current_app.config
    idle = int(float(cfg.get("SESSION_IDLE_TIMEOUT_MINUTES") or 0) * 60)
    absolute = int(float(cfg.get("SESSION_ABSOLUTE_TIMEOUT_HOURS") or 0) * 3600)
    return idle, absolute


def start_session():
    """Call right after login_user()."""
    now = int(time.time())
    session.permanent = True
    session[LOGIN_AT] = now
    session[LAST_SEEN] = now


def session_state(now=None):
    """Seconds left of the idle and absolute limits (None = limit is off)."""
    now = now or int(time.time())
    idle, absolute = _limits()
    login_at = session.get(LOGIN_AT, now)
    last_seen = session.get(LAST_SEEN, now)
    return {
        "server_time": now,
        "idle_timeout": idle or None,
        "idle_remaining": (last_seen + idle - now) if idle else None,
        "absolute_timeout": absolute or None,
        "absolute_remaining": (login_at + absolute - now) if absolute else None,
    }


def _wants_json():
    return (
        request.path.startswith("/api/")
        or request.path.startswith("/session/")
        or request.is_json
        or request.accept_mimetypes.best == "application/json"
    )


def expired_response():
    """401 for API/fetch calls, redirect to the login page for normal pages."""
    if _wants_json():
        return (
            jsonify({"ok": False, "message": "Session expired", "code": 401,
                     "session_expired": True}),
            401,
        )
    next_page = (
        request.full_path
        if request.method == "GET" and request.blueprint != "auth"
        else None
    )
    if next_page and next_page.endswith("?"):
        next_page = next_page[:-1]
    return redirect(url_for("auth.get_login", next=next_page))


def safe_next(value):
    """Only allow local paths as redirect target after login ("/x", not "//host")."""
    if value and value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value
    return None


def init_session_timeout(app):
    absolute = int(float(app.config.get("SESSION_ABSOLUTE_TIMEOUT_HOURS") or 0) * 3600)
    # Cookie lifetime = absolute limit plus a margin, so a browser that restores
    # its tabs cannot bring an old session back. The margin lets the server see
    # the expired session (and log why) instead of the cookie silently vanishing.
    # Without an absolute limit keep Flask's default (31 days); idle still applies.
    if absolute:
        app.permanent_session_lifetime = timedelta(seconds=absolute + 300)
    # Used by templates/helpers/session_timeout.html
    app.jinja_env.globals["session_state"] = session_state

    @app.before_request
    def enforce_session_timeout():
        if request.endpoint in (None, "static") or request.headers.get("token"):
            return None
        if not current_user.is_authenticated:
            return None

        now = int(time.time())
        idle, absolute = _limits()

        # Sessions created before this feature: start counting now
        if LOGIN_AT not in session:
            start_session()
            return None

        reason = None
        if absolute and now - session[LOGIN_AT] >= absolute:
            reason = "absolute"
        elif idle and now - session.get(LAST_SEEN, now) >= idle:
            reason = "idle"

        if reason:
            log_event(
                "session_expired",
                email=current_user.email,
                metadata={"reason": reason},
            )
            logout_user()
            session.clear()
            flash("Your session has expired, please log in again", "warning")
            return expired_response()

        if request.endpoint not in PASSIVE_ENDPOINTS:
            session[LAST_SEEN] = now
        return None
