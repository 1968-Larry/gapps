# Database changes

`db.create_all()` only creates missing tables; it never adds columns to existing
ones. The app therefore also runs `tools/apply_schema_updates.py` on a full
container start. If you only restart the app process, or want to apply a change
by hand, use the SQL files here.

- `changes/` - one file per feature, applied in file name order. Every file is
  idempotent (`IF NOT EXISTS`), so running them again does no harm.
- `optional/` - one-off data changes you run yourself, only if you want them.
- `apply.sh` - applies the files to the PostgreSQL container.

```
db/apply.sh <postgres-container> <db-user> <db-name>
db/apply.sh <postgres-container> <db-user> <db-name> db/optional/risk_initial_review_dates.sql
```

Or without the script:

```
docker exec -i <postgres-container> psql -U <db-user> -d <db-name> < db/changes/003_risk_review_dates_and_history.sql
```

When a change adds a column or a table, add a new numbered file in `changes/`
and, if it should also happen automatically on start, the same column in
`NEW_COLUMNS` in `tools/apply_schema_updates.py`.

## Backup and restore

`tools/backup.sh` and `tools/restore.sh` run on the docker host (see the header of each
script for all options). A backup is one folder named with the date and time:

```
tools/backup.sh                                   # -> backups/gapps-2026-10-15_021500/
tools/restore.sh --latest                         # newest backup
tools/restore.sh backups/gapps-2026-10-15_021500 --db     # only the database
```

It contains the database dump, evidence + reports, the audit log and (secrets!) the
configuration (`.env`, `docker-compose.override.yml`). Set `BACKUP_PASSPHRASE` to encrypt the
configuration. Cron example, 02:15 every night, 14 days kept:

```
15 2 * * *  cd /path/to/gapps && tools/backup.sh >> /var/log/gapps-backup.log 2>&1
```
