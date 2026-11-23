"""
The client's IP address behind a reverse proxy (HAProxy, nginx ...).

TRUSTED_PROXIES (comma list of IPs or networks, e.g. "10.0.0.5,172.16.0.0/12"):
  When the connection comes from a trusted proxy, X-Forwarded-For is read from
  the right and the first address that is not a trusted proxy is the client
  (OWASP: the left part of the header can be set by the client itself). The
  result becomes request.remote_addr for the whole app, and X-Forwarded-Proto
  sets the scheme. Connections from anywhere else: the headers are ignored.

TRUSTED_PROXIES empty: the old behaviour (audit log uses the first
  X-Forwarded-For address when AUDIT_TRUST_FORWARDED_FOR is true).
"""
import ipaddress

PEER_KEY = "gapps.proxy_peer"
_cache = {"raw": None, "networks": []}


def trusted_networks(raw):
    if raw == _cache["raw"]:
        return _cache["networks"]
    networks = []
    for part in (raw or "").split(","):
        part = part.strip()
        if part:
            networks.append(ipaddress.ip_network(part, strict=False))
    _cache.update(raw=raw, networks=networks)
    return networks


def _ip(value):
    try:
        return ipaddress.ip_address(value.strip().strip("[]"))
    except ValueError:
        return None


def is_trusted(value, networks):
    ip = _ip(value or "")
    return bool(ip) and any(ip in net for net in networks)


def resolve(peer, xff, networks):
    """Client address for a connection from `peer` with the X-Forwarded-For value `xff`."""
    if not networks or not is_trusted(peer, networks):
        return peer
    hops = [h.strip() for h in (xff or "").split(",") if h.strip()]
    for hop in reversed(hops):
        if _ip(hop) is None:
            break  # garbage in the header: stop, do not trust what is left of it
        if not is_trusted(hop, networks):
            return str(_ip(hop))
    valid = [h for h in hops if _ip(h)]
    return str(_ip(valid[0])) if valid else peer


class ProxyMiddleware:
    """WSGI middleware: sets REMOTE_ADDR and the scheme from a trusted proxy."""

    def __init__(self, wsgi_app, flask_app):
        self.wsgi_app = wsgi_app
        self.flask_app = flask_app

    def __call__(self, environ, start_response):
        networks = trusted_networks(self.flask_app.config.get("TRUSTED_PROXIES"))
        peer = environ.get("REMOTE_ADDR")
        if networks and is_trusted(peer, networks):
            client = resolve(peer, environ.get("HTTP_X_FORWARDED_FOR"), networks)
            environ[PEER_KEY] = peer
            environ["REMOTE_ADDR"] = client
            proto = (environ.get("HTTP_X_FORWARDED_PROTO") or "").split(",")[-1].strip()
            if proto in ("http", "https"):
                environ["wsgi.url_scheme"] = proto
        return self.wsgi_app(environ, start_response)


def init_client_ip(app):
    trusted_networks(app.config.get("TRUSTED_PROXIES"))  # fail at start on a typo
    app.wsgi_app = ProxyMiddleware(app.wsgi_app, app)
