"""
Third-party browser libraries: served locally (on-prem / air-gapped) or from a CDN.

ASSET_MODE=local (default)  /static/vendor/<path>, the files committed in git.
ASSET_MODE=cdn              <ASSET_CDN_URL>/<package>@<version>/<file>, with the
                            SRI hash of the local copy, so the browser refuses a
                            CDN file that differs from the one in git.

The versions come from vendor/package.json (via app/static/vendor/manifest.json
when it exists), so both modes always load the same version. Templates use:

    {{ vendor_js('dompurify/purify.min.js') }}
    {{ vendor_js('alpinejs/cdn.min.js', defer=True) }}
    {{ vendor_css('flatpickr/flatpickr.min.css') }}
    {{ vendor_url('img/background_illustration.svg') }}

The same module sets the Content-Security-Policy header (CSP_MODE).
"""
import json
import os
from urllib.parse import urlsplit

from flask import url_for
from markupsafe import Markup, escape

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ASSETS_FILE = os.path.join(ROOT, "vendor", "assets.json")
PACKAGE_FILE = os.path.join(ROOT, "vendor", "package.json")
MANIFEST_FILE = os.path.join(ROOT, "app", "static", "vendor", "manifest.json")

DEFAULT_CDN = "https://cdn.jsdelivr.net/npm"


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


class VendorAssets:
    def __init__(self, mode="local", cdn_url=DEFAULT_CDN, logger=None):
        self.mode = (mode or "local").strip().lower()
        if self.mode not in ("local", "cdn"):
            raise ValueError(f"ASSET_MODE must be 'local' or 'cdn', not {mode!r}")
        self.cdn_url = (cdn_url or DEFAULT_CDN).rstrip("/")
        self.logger = logger
        self.files = {}  # local path -> asset entry (file entries)
        self.dirs = []  # (local prefix, asset entry) for folder entries
        self.versions = {}
        self.integrity = {}
        self._load()

    def _load(self):
        assets = (_read_json(ASSETS_FILE) or {}).get("assets", [])
        for a in assets:
            if a.get("dir") is not None:
                self.dirs.append((a["local"], a))
            else:
                self.files[a["local"]] = a
        self.versions = dict((_read_json(PACKAGE_FILE) or {}).get("dependencies", {}))
        manifest = _read_json(MANIFEST_FILE) or {}
        # The manifest has what was actually installed and copied
        self.versions.update(manifest.get("packages", {}))
        self.integrity = manifest.get("files", {})
        if self.mode == "cdn" and not self.integrity and self.logger:
            self.logger.warning(
                "ASSET_MODE=cdn but app/static/vendor/manifest.json is missing: "
                "CDN files are loaded without SRI. Run scripts/vendor-assets.sh."
            )

    def _cdn_target(self, path):
        """(package, file in package) for a local path, or None = always local."""
        a = self.files.get(path)
        if a:
            return (a["package"], a["file"]) if a.get("package") else None
        for prefix, a in self.dirs:
            if path.startswith(prefix):
                base = a["dir"].strip("./")
                rest = path[len(prefix):]
                return a["package"], f"{base}/{rest}" if base else rest
        return None

    def url(self, path):
        if self.mode == "cdn":
            target = self._cdn_target(path)
            if target and self.versions.get(target[0]):
                pkg, file = target
                version = self.versions[pkg].lstrip("^~=")
                return f"{self.cdn_url}/{pkg}@{version}/{file}"
            if target is None and path not in self.files and self.logger:
                self.logger.warning("vendor asset %s is not in vendor/assets.json", path)
        return url_for("static", filename=f"vendor/{path}")

    def _sri_attrs(self, path):
        if self.mode != "cdn":
            return ""
        attrs = ' crossorigin="anonymous"'
        sri = self.integrity.get(path)
        if sri:
            attrs = f' integrity="{escape(sri)}"' + attrs
        return attrs

    def js(self, path, defer=False):
        return Markup(
            f'<script src="{escape(self.url(path))}"'
            f'{self._sri_attrs(path)}{" defer" if defer else ""}></script>'
        )

    def css(self, path):
        return Markup(
            f'<link rel="stylesheet" href="{escape(self.url(path))}"{self._sri_attrs(path)}>'
        )

    def cdn_origin(self):
        parts = urlsplit(self.cdn_url)
        return f"{parts.scheme}://{parts.netloc}"


def build_csp(assets):
    """
    The pages use inline scripts, inline event handlers and Alpine.js (which
    evaluates expressions), so 'unsafe-inline' and 'unsafe-eval' are needed.
    What the policy does stop: loading scripts, styles, fonts and frames from
    any other host, posting forms elsewhere, and framing of the app.
    """
    extra = f" {assets.cdn_origin()}" if assets.mode == "cdn" else ""
    return "; ".join(
        [
            "default-src 'self'",
            f"script-src 'self' 'unsafe-inline' 'unsafe-eval'{extra}",
            f"style-src 'self' 'unsafe-inline'{extra}",
            f"font-src 'self' data:{extra}",
            "img-src 'self' data: blob:",
            "connect-src 'self'",
            "frame-ancestors 'self'",
            "base-uri 'self'",
            "object-src 'none'",
        ]
    )


def init_vendor_assets(app):
    assets = VendorAssets(
        mode=app.config.get("ASSET_MODE", "local"),
        cdn_url=app.config.get("ASSET_CDN_URL", DEFAULT_CDN),
        logger=app.logger,
    )
    app.vendor_assets = assets
    app.jinja_env.globals.update(
        vendor_url=assets.url, vendor_js=assets.js, vendor_css=assets.css
    )

    csp_mode = (app.config.get("CSP_MODE") or "report-only").strip().lower()
    if csp_mode not in ("off", "report-only", "enforce"):
        raise ValueError(f"CSP_MODE must be off, report-only or enforce, not {csp_mode!r}")
    if csp_mode == "off":
        return
    header = (
        "Content-Security-Policy"
        if csp_mode == "enforce"
        else "Content-Security-Policy-Report-Only"
    )
    policy = build_csp(assets)

    @app.after_request
    def _set_csp(response):
        if response.mimetype == "text/html":
            response.headers.setdefault(header, policy)
        return response
