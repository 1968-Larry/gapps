#!/usr/bin/env bash
#
# Restore from a backup made by tools/backup.sh. Run it on the docker HOST.
#
#   tools/restore.sh backups/gapps-2026-10-15_021500            # database + files + audit log
#   tools/restore.sh backups/gapps-2026-10-15_021500 --db       # only the database
#   tools/restore.sh backups/gapps-2026-10-15_021500 --files    # only evidence and reports
#   tools/restore.sh backups/gapps-2026-10-15_021500 --config   # everything, plus .env / override file
#   tools/restore.sh backups/gapps-2026-10-15_021500 --config-only   # only .env / override file
#   tools/restore.sh --latest                                   # newest backup in BACKUP_DIR
#
# The database is OVERWRITTEN (the dump drops and recreates the tables) and files
# are written over existing ones, so you are asked to type "yes" first
# (skip with --yes). Checksums are verified before anything is touched.
# The app is stopped while the database is restored and started again afterwards.
#
# Settings: same as backup.sh (BACKUP_DIR, APP_CONTAINER, DB_CONTAINER,
# POSTGRES_USER, POSTGRES_DB, BACKUP_PASSPHRASE for an encrypted config).
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"

env_get() {
    [ -f "$ENV_FILE" ] || return 0
    grep -E "^$1=" "$ENV_FILE" | tail -n 1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'\$//" || true
}
pick() {
    local name="$1" default="$2" value="${!1:-}"
    [ -n "$value" ] || value="$(env_get "$name")"
    echo "${value:-$default}"
}

BACKUP_DIR="$(pick BACKUP_DIR "$ROOT/backups")"
PASSPHRASE="$(pick BACKUP_PASSPHRASE "")"
APP_CONTAINER="$(pick APP_CONTAINER app)"
DB_CONTAINER="$(pick DB_CONTAINER postgres)"
PG_USER="$(pick POSTGRES_USER db1)"
PG_DB="$(pick POSTGRES_DB db1)"

TMP=""
APP_STOPPED=0
cleanup() {
    [ -z "$TMP" ] || rm -rf "$TMP"
    # never leave the app stopped, also when something fails halfway
    if [ "$APP_STOPPED" = "1" ]; then
        echo "Starting $APP_CONTAINER ..."
        docker start "$APP_CONTAINER" >/dev/null || echo "Could not start $APP_CONTAINER, start it manually" >&2
    fi
}
trap cleanup EXIT

SRC=""
DO_DB=0; DO_FILES=0; DO_AUDIT=0; DO_CONFIG=0; PICKED=0; ASSUME_YES=0

while [ $# -gt 0 ]; do
    case "$1" in
        --db) DO_DB=1; PICKED=1 ;;
        --files) DO_FILES=1; PICKED=1 ;;
        --audit) DO_AUDIT=1; PICKED=1 ;;
        --config) DO_CONFIG=1 ;;
        --config-only) DO_CONFIG=1; PICKED=1 ;;
        --yes) ASSUME_YES=1 ;;
        --latest) SRC="$(ls -d "$BACKUP_DIR"/gapps-????-??-??_?????? 2>/dev/null | sort | tail -n 1 || true)" ;;
        -h|--help) sed -n '2,21p' "$0"; exit 0 ;;
        -*) echo "Unknown option: $1" >&2; exit 2 ;;
        *) SRC="$1" ;;
    esac
    shift
done

[ -n "$SRC" ] || { echo "Give a backup folder, or --latest" >&2; exit 2; }
[ -d "$SRC" ] || { echo "Not a folder: $SRC" >&2; exit 1; }
SRC="$(cd "$SRC" && pwd)"
if [ "$PICKED" = "0" ]; then DO_DB=1; DO_FILES=1; DO_AUDIT=1; fi

command -v docker >/dev/null || { echo "docker not found" >&2; exit 1; }
for c in "$APP_CONTAINER" "$DB_CONTAINER"; do
    [ "$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null || echo false)" = "true" ] \
        || { echo "Container '$c' must be running (the data is restored through it)" >&2; exit 1; }
done

echo "Backup:   $SRC"
echo "Restore:  $([ $DO_DB = 1 ] && echo database) $([ $DO_FILES = 1 ] && echo files) $([ $DO_AUDIT = 1 ] && echo audit-log) $([ $DO_CONFIG = 1 ] && echo config)"

# verify before touching anything
if [ -f "$SRC/SHA256SUMS" ]; then
    ( cd "$SRC" && sha256sum -c --quiet SHA256SUMS ) || { echo "Checksum mismatch - the backup is damaged, nothing was changed" >&2; exit 1; }
    echo "Checksums ok"
else
    echo "WARNING: no SHA256SUMS in the backup, cannot verify it"
fi
[ "$DO_DB" = 0 ] || [ -f "$SRC/db.sql.gz" ] || { echo "db.sql.gz is missing in the backup" >&2; exit 1; }
[ "$DO_FILES" = 0 ] || [ -f "$SRC/files.tar.gz" ] || { echo "files.tar.gz is missing in the backup" >&2; exit 1; }

if [ "$ASSUME_YES" != "1" ]; then
    echo
    echo "This OVERWRITES the current data. Type yes to continue:"
    read -r answer
    [ "$answer" = "yes" ] || { echo "Aborted"; exit 1; }
fi

# files first, while the app container is up
if [ "$DO_FILES" = "1" ]; then
    echo "Restoring evidence and reports ..."
    gzip -dc "$SRC/files.tar.gz" | docker exec -i "$APP_CONTAINER" tar -C /app/app/files -xf -
fi
if [ "$DO_AUDIT" = "1" ] && [ -f "$SRC/audit.tar.gz" ]; then
    echo "Restoring audit log ..."
    gzip -dc "$SRC/audit.tar.gz" | docker exec -i "$APP_CONTAINER" tar -C /var/log -xf -
fi

# database: stop the app so nobody holds connections or writes meanwhile
if [ "$DO_DB" = "1" ]; then
    echo "Stopping $APP_CONTAINER ..."
    docker stop "$APP_CONTAINER" >/dev/null
    APP_STOPPED=1
    echo "Restoring database ..."
    gzip -dc "$SRC/db.sql.gz" | docker exec -i "$DB_CONTAINER" psql -q -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 >/dev/null
fi

# configuration only on request, and never silently over an existing file
if [ "$DO_CONFIG" = "1" ]; then
    TMP="$(mktemp -d)"
    if [ -f "$SRC/config.tar.gz.enc" ]; then
        [ -n "$PASSPHRASE" ] || { echo "config is encrypted: set BACKUP_PASSPHRASE" >&2; exit 1; }
        BACKUP_PASSPHRASE_VALUE="$PASSPHRASE" openssl enc -d -aes-256-cbc -pbkdf2 -pass env:BACKUP_PASSPHRASE_VALUE \
            -in "$SRC/config.tar.gz.enc" | tar -xzf - -C "$TMP"
    elif [ -f "$SRC/config.tar.gz" ]; then
        tar -xzf "$SRC/config.tar.gz" -C "$TMP"
    else
        echo "No config in this backup"
    fi
    if [ -n "$(ls -A "$TMP")" ]; then
        for f in "$TMP"/* "$TMP"/.env; do
            [ -f "$f" ] || continue
            name="$(basename "$f")"
            if [ -e "$ROOT/$name" ]; then
                cp "$ROOT/$name" "$ROOT/$name.before-restore"
                echo "  kept the current $name as $name.before-restore"
            fi
            cp "$f" "$ROOT/$name"; chmod 600 "$ROOT/$name"
            echo "  restored $name"
        done
    fi
fi

echo "Restore finished"
