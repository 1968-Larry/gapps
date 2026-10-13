from . import auth
from flask import request, abort, redirect, url_for, session, current_app, flash
from authlib.integrations.base_client.errors import MismatchingStateError, OAuthError
from app.utils.audit import log_event
from app.auth.flows import UserFlow
import secrets


@auth.route("/oidc/microsoft/<string:flow>")
def microsoft_auth(flow):
    """Authenticate the user through Microsoft provider for login or registration"""
    if flow not in UserFlow.VALID_FLOW_TYPES:
        abort(400, "Invalid authentication flow")

    if flow == "accept" and not request.args.get("token"):
        abort(400, "Invalid authentication flow: missing acceptance token")

    if not current_app.is_microsoft_auth_configured:
        flash("Provider not configured", "error")
        return redirect(url_for("auth.get_login"))

    nonce = secrets.token_urlsafe(16)
    session["nonce"] = nonce
    session["flow_type"] = flow
    redirect_uri = url_for(
        "auth.authorize_with_microsoft",
        _external=True,
        _scheme=current_app.config["SCHEME"],
    )

    return current_app.providers["microsoft"].authorize_redirect(
        redirect_uri, nonce=nonce
    )


@auth.route("/oidc/microsoft/authorize")
def authorize_with_microsoft():
    """Handles Microsoft callback after authentication"""
    flow = session.get("flow_type")

    try:
        token = current_app.providers["microsoft"].authorize_access_token()
    except MismatchingStateError as e:
        log_event(
            "login_failed",
            provider="microsoft",
            result="failure",
            metadata={"reason": "state_mismatch"},
        )
        abort(403, "Mismatch error")
    except OAuthError as e:
        log_event(
            "login_failed",
            provider="microsoft",
            result="failure",
            metadata={"reason": "oauth_error", "error": getattr(e, "error", None)},
        )
        abort(403, "Authentication failed")
    except Exception as e:
        # e.g. TLS/network problems towards the identity provider
        log_event(
            "login_failed",
            provider="microsoft",
            result="error",
            metadata={"reason": "provider_unreachable", "error": type(e).__name__},
        )
        raise

    nonce = session.pop("nonce", None)
    try:
        user_info = current_app.providers["microsoft"].parse_id_token(token, nonce=nonce)
    except Exception as e:
        log_event(
            "login_failed",
            provider="microsoft",
            result="failure",
            metadata={"reason": "id_token_invalid", "error": type(e).__name__},
        )
        abort(403, "Invalid identity token")

    attributes = {"token": session.get("token")}
    return UserFlow(
        user_info=user_info, flow_type=flow, provider="microsoft"
    ).handle_flow(attributes)
