"""
Browser test (Chromium via Playwright), run by CI against the running app.

1. Editor: opens tools/browser/editor_harness.html (served from the repository
   root) and checks that TinyMCE starts with the gapps settings: licence key,
   plugins, the tinymce-variable plugin, "/" commands, read-only mode.
2. Pages: logs in and opens the main pages. Fails on JavaScript errors and on
   /static files that do not load. Content-Security-Policy violations
   (CSP_MODE=report-only) are listed but do not fail: they show whether
   CSP_MODE=enforce would break something.

    pip install playwright && playwright install chromium
    python3 tools/browser_test.py --base http://localhost:8000 \
        --repo-url http://localhost:8099 --tid <tenant id> --pid <project id>
"""
import argparse
import json
import sys

from playwright.sync_api import sync_playwright

PAGES = [
    "/",
    "/projects",
    "/projects/{pid}",
    "/projects/{pid}/policy-center",
    "/frameworks",
    "/gaps",
    "/deadlines",
    "/reports",
    "/logs",
    "/users",
    "/tenants",
    "/admin/users",
    "/admin/settings",
    "/tenants/{tid}/risk",
    "/tenants/{tid}/exceptions",
]


def check_editor(browser, repo_url):
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.goto(f"{repo_url}/tools/browser/editor_harness.html")
    page.wait_for_function("window.harnessResult !== undefined", timeout=30000)
    result = page.evaluate("window.harnessResult")
    page.close()
    print("Editor:", json.dumps(result, indent=1))
    problems = list(result.get("errors", [])) + errors
    expect = {
        "variableRendered": True,
        "table": True,
        "policyMode": "design",
        "readonlyMode": "readonly",
        "removed": True,
    }
    for key, want in expect.items():
        if result.get(key) != want:
            problems.append(f"{key} is {result.get(key)!r}, expected {want!r}")
    if "{company}" not in (result.get("contentRoundTrip") or ""):
        problems.append("getContent() does not give the variable back as {company}")
    return problems


def check_pages(browser, base, tid, pid, email, password):
    context = browser.new_context()
    page = context.new_page()
    problems, csp = [], set()
    current = {"url": ""}

    def on_console(msg):
        text = msg.text
        if "Content Security Policy" in text or "Content-Security-Policy" in text:
            csp.add(f"{current['url']}: {text[:300]}")
        elif msg.type == "error" and "Failed to load resource" not in text:
            problems.append(f"{current['url']}: console error: {text[:300]}")

    page.on("console", on_console)
    page.on("pageerror", lambda e: problems.append(f"{current['url']}: {e}"[:400]))

    def on_response(resp):
        if "/static/" in resp.url and resp.status >= 400:
            problems.append(f"{current['url']}: {resp.status} {resp.url}")

    page.on("response", on_response)
    page.on(
        "requestfailed",
        lambda r: problems.append(f"{current['url']}: failed {r.url} ({r.failure})"),
    )

    page.goto(f"{base}/login")
    page.fill("input[name=email]", email)
    page.fill("input[name=password]", password)
    page.press("input[name=password]", "Enter")
    page.wait_for_load_state("networkidle")
    if "/login" in page.url:
        return [f"login failed, still on {page.url}"], csp

    for path in PAGES:
        url = base + path.format(tid=tid, pid=pid)
        current["url"] = path
        resp = page.goto(url)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(500)  # let Alpine/x-init fetches finish
        status = resp.status if resp else "?"
        print(f"  {status}  {path}")
        if resp and resp.status >= 500:
            problems.append(f"{path}: HTTP {resp.status}")
    context.close()
    return problems, csp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--repo-url", default="http://localhost:8099")
    ap.add_argument("--tid", required=True)
    ap.add_argument("--pid", required=True)
    ap.add_argument("--email", default="admin@example.com")
    ap.add_argument("--password", default="admin1234567")
    args = ap.parse_args()

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        editor_problems = check_editor(browser, args.repo_url)
        page_problems, csp = check_pages(
            browser, args.base, args.tid, args.pid, args.email, args.password
        )
        browser.close()

    if csp:
        print(f"\nCSP violations (report-only, {len(csp)}):")
        for line in sorted(csp):
            print("  " + line)
    problems = [f"editor: {p}" for p in editor_problems] + page_problems
    if problems:
        print(f"\n{len(problems)} PROBLEMS:")
        for p in problems:
            print("  " + p)
        sys.exit(1)
    print("\nBrowser test OK")


if __name__ == "__main__":
    main()
