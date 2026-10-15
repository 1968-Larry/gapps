#!/usr/bin/env bash
#
# Backup of the database, evidence/report files, audit log and (optionally) the
# configuration. Run it on the docker HOST, for example from cron:
#
#   15 2 * * *  cd /path/to/gapps && tools/backup.sh >> /var/log/gapps-backup.log 2>&1
#
# Every run writes ONE folder named with the date and time, so your normal file
# backup can pick it up and old runs can be kept or rotated:
#
#   backups/gapps-2026-10-15_021500/
#     db.sql.gz          pg_dump of the database (consistent while the app runs)
#     files.tar.gz       evidence + generated reports
#     audit.tar.gz       JSON audit log
#     config.tar.gz      .env and docker-compose.override.yml   (contains secrets!)
#     SHA256SUMS         checksums, verified again by restore.sh
#
# Works whether the data lives in named volumes or in folders on the host, because
# everything is read through the containers.
#
# Settings (environment variables or .env, defaults in brackets):
#   BACKUP_DIR            where to put the backups            [./backups]
#   BACKUP_KEEP_DAYS      delete backups older than this, 0 = keep all   [14]
#   BACKUP_PASSPHRASE     if set, config.tar.gz is encrypted (AES-256) to config.tar.gz.enc
#   APP_CONTAINER         [app]        DB_CONTAINER   [postgres]
#   POSTGRES_USER / POSTGRES_DB       [db1] / [db1]  (read from .env when present)
#
# Options:  --no-config   do not include .env / override file
#           --keep-days N override BACKUP_KEEP_DAYS
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"

env_get() {
    # value of KEY from .env without executing anything
    [ -f "$ENV_FILE" ] || return 0
    grep -E "^$1=" "$ENV_FILE" | tail -n 1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'\$//" || true
}

pick() {
    # environment first, then .env, then default
    local name="$1" default="$2" value="${!1:-}"
    [ -n "$value" ] || value="$(env_get "$name")"
    echo "${value:-$default}"
}

BACKUP_DIR="$(pick BACKUP_DIR "$ROOT/backups")"
KEEP_DAYS="$(pick BACKUP_KEEP_DAYS 14)"
PASSPHRASE="$(pick BACKUP_PASSPHRASE "")"
APP_CONTAINER="$(pick APP_CONTAINER app)"
DB_CONTAINER="$(pick DB_CONTAINER postgres)"
PG_USER="$(pick POSTGRES_USER db1)"
PG_DB="$(pick POSTGRES_DB db1)"
INCLUDE_CONFIG=1

while [ $# -gt 0 ]; do
    case "$1" in
        --no-config) INCLUDE_CONFIG=0 ;;
        --keep-days) KEEP_DAYS="${2:?--keep-days needs a number}"; shift ;;
        -h|--help) sed -n '2,32p' "$0"; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

command -v docker >/dev/null || { echo "docker not found" >&2; exit 1; }
for c in "$APP_CONTAINER" "$DB_CONTAINER"; do
    [ "$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null || echo false)" = "true" ] \
        || { echo "Container '$c' is not running" >&2; exit 1; }
done

STAMP="$(date +%Y-%m-%d_%H%M%S)"
DEST="$BACKUP_DIR/gapps-$STAMP"
umask 077
mkdir -p "$DEST"
echo "[$(date +%F' '%T)] Backup to $DEST"

# 1. database -------------------------------------------------------------
echo "  database ..."
docker exec "$DB_CONTAINER" pg_dump -U "$PG_USER" -d "$PG_DB" --clean --if-exists --no-owner \
    | gzip -9 > "$DEST/db.sql.gz"
gzip -t "$DEST/db.sql.gz"
[ "$(gzip -dc "$DEST/db.sql.gz" | head -c 200 | wc -c)" -gt 0 ] || { echo "Database dump is empty" >&2; exit 1; }

# 2. evidence + reports (the app container is the one that sees both) ------
echo "  evidence and reports ..."
docker exec "$APP_CONTAINER" sh -c 'cd /app/app/files && tar -cf - $(ls -d evidence reports 2>/dev/null)' \
    | gzip > "$DEST/files.tar.gz"
gzip -t "$DEST/files.tar.gz"

# 3. audit log --------------------------------------------------------------
echo "  audit log ..."
if docker exec "$APP_CONTAINER" test -d /var/log/app; then
    docker exec "$APP_CONTAINER" tar -C /var/log -cf - app | gzip > "$DEST/audit.tar.gz"
    gzip -t "$DEST/audit.tar.gz"
else
    echo "  (no /var/log/app in the container, skipped)"
fi

# 4. configuration (secrets) -------------------------------------------------
if [ "$INCLUDE_CONFIG" = "1" ]; then
    echo "  configuration ..."
    files=()
    for f in .env docker-compose.override.yml; do [ -f "$f" ] && files+=("$f"); done
    if [ ${#files[@]} -gt 0 ]; then
        if [ -n "$PASSPHRASE" ]; then
            # use the variable explicitly so the passphrase never shows up in the process list
            tar -czf - "${files[@]}" | BACKUP_PASSPHRASE_VALUE="$PASSPHRASE" \
                openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:BACKUP_PASSPHRASE_VALUE > "$DEST/config.tar.gz.enc"
        else
            tar -czf "$DEST/config.tar.gz" "${files[@]}"
            echo "  NOTE: config.tar.gz contains secrets and is NOT encrypted (set BACKUP_PASSPHRASE to encrypt it)"
        fi
    fi
fi

# 5. checksums ----------------------------------------------------------------
( cd "$DEST" && sha256sum $(ls | grep -v '^SHA256SUMS$') > SHA256SUMS )
echo "  done: $(du -sh "$DEST" | cut -f1) in $(ls "$DEST" | wc -l) files"

# 6. rotation ------------------------------------------------------------------
if [ "$KEEP_DAYS" -gt 0 ] 2>/dev/null; then
    find "$BACKUP_DIR" -maxdepth 1 -type d -name 'gapps-????-??-??_??????' -mtime +"$KEEP_DAYS" \
        -print -exec rm -rf {} + | sed 's/^/  removed old backup /'
fi
echo "[$(date +%F' '%T)] Backup finished"
