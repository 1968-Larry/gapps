#!/usr/bin/env bash
#
# Refreshes app/static/vendor/ (the browser libraries) from vendor/package.json.
#
# Normally you do not need to run this: the "vendor-sync" GitHub workflow runs
# it whenever vendor/package.json changes (for example in a Dependabot PR) and
# commits the result, so the server only needs `git pull`.
#
# Run it by hand on a machine with Node 18+ and internet access, for example
# after editing vendor/package.json or vendor/assets.json, then commit
# vendor/package-lock.json and app/static/vendor/.
#
# Usage: bash scripts/vendor-assets.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/vendor"

if [ -f package-lock.json ]; then
  npm ci --ignore-scripts --no-audit --no-fund
else
  npm install --ignore-scripts --no-audit --no-fund
fi

node "$ROOT/scripts/sync-vendor.mjs"
