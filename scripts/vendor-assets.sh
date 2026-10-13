#!/usr/bin/env bash
#
# Downloads every third-party CSS/JS asset the app currently loads from a
# public CDN, and writes them into app/static/vendor/ so the app can run
# fully air-gapped (no runtime fetches to jsdelivr/unpkg/cdnjs/gstatic).
#
# Run this ONCE, from a machine with normal internet access (your laptop,
# or a build stage that still has egress), then commit app/static/vendor/
# to git like any other static asset. After that, `docker build` and the
# running app need no network access for these files at all - this script
# does not need to run at image-build time.
#
# Usage: bash scripts/vendor-assets.sh
# Re-run safely at any time to re-pull the pinned versions below.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR="$ROOT/app/static/vendor"

fetch() {
  # fetch <url> <destination-relative-to-vendor>
  local url="$1" dest="$VENDOR/$2"
  mkdir -p "$(dirname "$dest")"
  echo "-> $2"
  curl -fsSL "$url" -o "$dest"
}

echo "Writing vendor assets to: $VENDOR"
mkdir -p "$VENDOR"

# --- dompurify ---
fetch "https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.0.3/purify.min.js" \
  "dompurify/purify.min.js"

# --- ldLoader (spinner) ---
fetch "https://cdn.jsdelivr.net/gh/loadingio/ldLoader@v1.0.0/dist/ldld.min.js" \
  "ldloader/ldld.min.js"
fetch "https://cdn.jsdelivr.net/gh/loadingio/ldLoader@v1.0.0/dist/ldld.min.css" \
  "ldloader/ldld.min.css"

# --- ag-grid (pinned to the version already in use; the jsdelivr "latest"
#     reference in src_macros.html was commented out / unused already) ---
fetch "https://cdnjs.cloudflare.com/ajax/libs/ag-grid/31.3.2/ag-grid-community.min.js" \
  "ag-grid/ag-grid-community.min.js"

# --- apexcharts (jsdelivr's unversioned alias resolves to latest at fetch
#     time; re-run this script if you want to re-pin to a newer release) ---
fetch "https://cdn.jsdelivr.net/npm/apexcharts" \
  "apexcharts/apexcharts.min.js"

# --- flatpickr ---
fetch "https://cdn.jsdelivr.net/npm/flatpickr/dist/flatpickr.min.css" \
  "flatpickr/flatpickr.min.css"
fetch "https://cdn.jsdelivr.net/npm/flatpickr" \
  "flatpickr/flatpickr.min.js"

# --- slim-select -- PINNED to 2.12.0 deliberately. The unpkg "@latest" tag
#     now resolves to a v3/v4 release with a different dist/ layout (see the
#     "SlimSelect" discussion earlier in this project) - do not bump this to
#     @latest without checking the breaking-changes notes at slimselectjs.com
fetch "https://unpkg.com/slim-select@2.12.0/dist/slimselect.min.js" \
  "slim-select/slimselect.min.js"
fetch "https://unpkg.com/slim-select@2.12.0/dist/slimselect.css" \
  "slim-select/slimselect.css"

# --- tinymce core (single-file minified build only; editor plugins/themes/
#     skins/icons that TinyMCE lazy-loads at runtime from relative paths are
#     NOT included here - see the "TinyMCE" note printed at the end) ---
fetch "https://cdnjs.cloudflare.com/ajax/libs/tinymce/6.2.0/tinymce.min.js" \
  "tinymce/tinymce.min.js"
fetch "https://cdn.jsdelivr.net/npm/tinymce-variable@0.9.2/src/plugin.min.js" \
  "tinymce-variable/plugin.min.js"

# --- confetti ---
fetch "https://cdn.jsdelivr.net/npm/tsparticles-confetti@2.9.3/tsparticles.confetti.bundle.min.js" \
  "tsparticles-confetti/tsparticles.confetti.bundle.min.js"

# --- tributejs (@mentions) ---
fetch "https://cdnjs.cloudflare.com/ajax/libs/tributejs/5.1.3/tribute.css" \
  "tributejs/tribute.css"
fetch "https://cdnjs.cloudflare.com/ajax/libs/tributejs/5.1.3/tribute.min.js" \
  "tributejs/tribute.min.js"

# --- filepond ---
fetch "https://unpkg.com/filepond/dist/filepond.css" \
  "filepond/filepond.css"
fetch "https://unpkg.com/filepond/dist/filepond.js" \
  "filepond/filepond.js"
fetch "https://unpkg.com/filepond-plugin-image-preview/dist/filepond-plugin-image-preview.css" \
  "filepond-plugin-image-preview/filepond-plugin-image-preview.css"
fetch "https://unpkg.com/filepond-plugin-image-preview/dist/filepond-plugin-image-preview.js" \
  "filepond-plugin-image-preview/filepond-plugin-image-preview.js"

# --- sortablejs ---
fetch "https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js" \
  "sortablejs/Sortable.min.js"

# --- driver.js (guided tours) ---
fetch "https://cdn.jsdelivr.net/npm/driver.js@1.0.1/dist/driver.js.iife.js" \
  "driverjs/driver.js.iife.js"
fetch "https://cdn.jsdelivr.net/npm/driver.js@1.0.1/dist/driver.css" \
  "driverjs/driver.css"

# --- markdown-it ---
fetch "https://cdn.jsdelivr.net/npm/markdown-it@14.1.0/dist/markdown-it.min.js" \
  "markdown-it/markdown-it.min.js"

# --- jsPDF + autotable (PDF export) ---
fetch "https://cdnjs.cloudflare.com/ajax/libs/jspdf/3.0.1/jspdf.umd.min.js" \
  "jspdf/jspdf.umd.min.js"
fetch "https://cdnjs.cloudflare.com/ajax/libs/jspdf-autotable/3.5.28/jspdf.plugin.autotable.min.js" \
  "jspdf-autotable/jspdf.plugin.autotable.min.js"

# --- daisyui + Tailwind: NOT vendored here on purpose. app/static/css/main.css
#     is already a locally-built Tailwind+daisyui bundle (see tl_src/), and the
#     layout templates no longer load the CDN versions at all. Rebuild it with
#     `cd tl_src && npm install && npx tailwindcss -i ./input.css -o ../app/static/css/main.css --minify`
#     if you change styles - check tl_src/package.json for the exact script name.

# --- toastify-js (jsdelivr unversioned alias resolves to latest) ---
fetch "https://cdn.jsdelivr.net/npm/toastify-js" \
  "toastify/toastify.min.js"
fetch "https://cdn.jsdelivr.net/npm/toastify-js/src/toastify.min.css" \
  "toastify/toastify.min.css"

# --- Alpine.js core + focus plugin (pinned together to the same version to
#     avoid a version-mismatch between core and plugin) ---
fetch "https://unpkg.com/alpinejs@3.13.10/dist/cdn.min.js" \
  "alpinejs/cdn.min.js"
fetch "https://unpkg.com/@alpinejs/focus@3.13.10/dist/cdn.min.js" \
  "alpine-focus/cdn.min.js"

# --- theme-change ---
fetch "https://cdn.jsdelivr.net/npm/theme-change@2.0.2/index.js" \
  "theme-change/index.js"

# --- Tabler icons webfont: the CSS references font files by relative url()
#     paths (fonts/tabler-icons.woff2 etc). We fetch the CSS AND the fonts/
#     subfolder it expects, preserving that relative layout. ---
fetch "https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@3.30.0/dist/tabler-icons.min.css" \
  "tabler-icons/tabler-icons.min.css"
for ext in woff2 woff ttf eot; do
  fetch "https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@3.30.0/dist/fonts/tabler-icons.$ext" \
    "tabler-icons/fonts/tabler-icons.$ext" || echo "   (no .$ext build for this version - skipping)"
done

# --- decorative background image on the home page ---
fetch "https://www.gstatic.com/pantheon/images/welcome/background_illustration_v2.svg" \
  "img/background_illustration.svg"

echo
echo "Done. Vendor assets written to app/static/vendor/."
echo
echo "Still needs manual attention:"
echo "  1. TinyMCE: only the single-file tinymce.min.js was downloaded. If your"
echo "     policy editor uses any TinyMCE plugin, theme, skin, or icon pack beyond"
echo "     what's bundled in that one file, TinyMCE will try to lazy-load it from"
echo "     cdn.tinymce.com at runtime and fail offline. Safest fix: instead of this"
echo "     single file, run 'npm pack tinymce@6.2.0' and vendor the full extracted"
echo "     package (including themes/, plugins/, skins/, icons/, models/) into"
echo "     app/static/vendor/tinymce/, then point tinymce.min.js at that same path"
echo "     and set tinymce.baseURL in the init config to the local vendor path."
echo "  2. cdn.tailwindcss.com: this is the Tailwind *Play CDN* - a JIT compiler"
echo "     that scans your HTML and generates CSS in the browser on every page"
echo "     load. It is NOT a static file and cannot be vendored by downloading"
echo "     one URL. See the accompanying message for how to replace it with a"
echo "     locally-built Tailwind output file."
