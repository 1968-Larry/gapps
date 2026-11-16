"""
Checks ASSET_MODE=cdn: downloads every file in app/static/vendor/manifest.json
from the CDN URL the app would use and compares it with the SRI hash of the
committed file. A mismatch means browsers would refuse that file in cdn mode.

    python3 tools/check_cdn_assets.py [--all]

Without --all only the files the templates load directly are checked (not the
fonts and TinyMCE plugins that are loaded relative to them). Needs internet.
"""
import argparse
import base64
import hashlib
import importlib.util
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Load the module on its own, without importing the whole app
spec = importlib.util.spec_from_file_location(
    "vendor_assets", os.path.join(ROOT, "app", "utils", "vendor_assets.py")
)
va = importlib.util.module_from_spec(spec)
spec.loader.exec_module(va)


def template_paths():
    found = set()
    for base, _, files in os.walk(os.path.join(ROOT, "app", "templates")):
        for name in files:
            with open(os.path.join(base, name), encoding="utf-8") as fh:
                found.update(re.findall(r"vendor_(?:js|css|url)\('([^']+)'", fh.read()))
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    assets = va.VendorAssets(mode="cdn", cdn_url=os.environ.get("ASSET_CDN_URL", va.DEFAULT_CDN))
    paths = sorted(assets.integrity) if args.all else sorted(template_paths())
    bad = 0
    for path in paths:
        target = assets._cdn_target(path)
        if target is None:
            continue  # always served locally
        url = assets.url(path)
        want = assets.integrity.get(path)
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                body = resp.read()
        except Exception as e:
            print(f"FAIL  {path}: {url}: {e}")
            bad += 1
            continue
        got = "sha384-" + base64.b64encode(hashlib.sha384(body).digest()).decode()
        if want != got:
            print(f"FAIL  {path}: CDN file differs from the committed one ({url})")
            bad += 1
        else:
            print(f"ok    {path}")
    if bad:
        sys.exit(f"{bad} CDN file(s) failed")
    print("All CDN files match the committed files")


if __name__ == "__main__":
    main()
