#!/usr/bin/env bash
# Apply the SQL files in db/migrations (in order) to the PostgreSQL container.
#
#   db/apply.sh <postgres-container> <db-user> <db-name>
#   db/apply.sh <postgres-container> <db-user> <db-name> db/optional/risk_initial_review_dates.sql
#
# With extra file arguments only those files are applied. All migrations are
# written to be safe to run more than once.
set -euo pipefail

if [ "$#" -lt 3 ]; then
  echo "usage: $0 <postgres-container> <db-user> <db-name> [file.sql ...]" >&2
  exit 1
fi
container="$1"; user="$2"; database="$3"; shift 3

here="$(cd "$(dirname "$0")" && pwd)"
if [ "$#" -gt 0 ]; then
  files=("$@")
else
  files=("$here"/migrations/*.sql)
fi

for file in "${files[@]}"; do
  echo "==> $file"
  docker exec -i "$container" psql -U "$user" -d "$database" -v ON_ERROR_STOP=1 < "$file"
done
echo "Done."
