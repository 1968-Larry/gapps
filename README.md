# Gapps

Gapps is an Security compliance platform that makes it easy to track your progress against various security frameworks.

:snowflake: View the [Gapps site](https://web-gapps.pages.dev/)  
🏠 Interested in contacting me? Please join our [discord](https://discord.gg/9unhWAqadg)

### Table of Contents
1. [Getting Started](#getting-started)
2. [FAQ](#faq)

### New Features :snowflake:
- SOC2, NIST CSF, NIST-800-53, CMMC, HIPAA, ASVS, ISO27001, CSC CIS18, PCI DSS and SSF have been added! That makes 10 total frameworks
- Multi-tenancy, OIDC (SSO)
- Collaboration with auditors
- Risk Register
- S3/GCS for file storage

### Added in this fork :wrench:
**Sign-in and audit**
- On-prem ADFS sign-in (OIDC) next to Google and Microsoft Entra ID (`ADFS_SERVER`)
- JSON audit log in daily files with retention, bulk collapsing and whitelisted values only
- Important audit events, including logins and logouts, are shown on the Logs page

**Risk management**
- 4x4 assessment: likelihood x impact calculates the risk level (very low, low, high, very high)
- Next review date, due date and completed date, with a standard review rhythm per risk level
  (`RISK_REVIEW_INTERVALS`), live date suggestion and a "Mark as reviewed" action
- Full change history per risk (who changed what and when)
- Ticket number and owner (any user in the organisation) on risks
- Risks can be linked to sub-controls, with "Linked to" tabs on risks and evidence
- The project of every risk is shown in the risk register
- Daily email reminders to risk owners before review/due dates and when overdue; recipients (To/Cc)
  and timing are set in `.env` (`tools/send_risk_reminders.py`)

**Controls and evidence**
- Custom controls and sub-controls: choose the reference code, rename, and add sub-controls
- Ticket number on sub-controls and a link field on evidence
- "Reload frameworks" for existing tenants

**Reporting across projects**
- Gaps page (menu: More > gaps): sub-controls grouped across all projects to show common gaps.
  Filter on status (not complete, not implemented, partial, missing evidence ...), framework and
  chosen projects. CSV export

**Deployment and operations**
- Air-gapped install: CSS/JS served from local vendor assets (`scripts/vendor-assets.sh`)
- Docker: proxy settings for builds, `.env.example` and `docker-compose.override.yml.example`
- Schema updater that runs at start, plus idempotent SQL change scripts in `db/`
- Backup and restore scripts for database, evidence, reports, audit log and configuration
  (`tools/backup.sh`, `tools/restore.sh`)
- Demo tenant with 10 projects and example data (`tools/seed_demo.py`)

See [Settings added in this fork](#settings-added-in-this-fork) for the `.env` values.

### Next big features :snowflake:  
- Integrations!

#### Captures from the platform

Control Dashboard          |
:-------------------------:|
![](img/gapps_2.PNG)  |


Project Overview          |
:-------------------------:|
![](img/gapps_1.PNG)  |

Track Progress of Controls          |
:-------------------------:|
![](img/gapps_3.PNG)  |

### Getting Started

Follow the documentation [documentation](https://web-gapps.pages.dev/docs)


### FAQ

##### If you get a database connection error trying to start Gapps, you need to update (or remove) your env variables
```
[INFO] Checking if we can connect to the database server: postgresql://db1:db1@localhost/db1
[ERROR] could not connect to server: Connection refused
        Is the server running on host "localhost" (127.0.0.1) and accepting
        TCP/IP connections on port 5432?
could not connect to server: Cannot assign requested address
        Is the server running on host "localhost" (::1) and accepting
        TCP/IP connections on port 5432?
```

Can usually be fixed by unsetting two variables if running within docker. If you want to use a external database, see the next FAQ
```
unset SQLALCHEMY_DATABASE_URI
unset POSTGRES_HOST
```

##### Set env variables for the database connection

The value `db1` is the default value for the username, database and password. If you would like to change it, update `db1` with the respective values and `postgres` for the host.
```
export POSTGRES_HOST=${POSTGRES_HOST:-postgres}
export POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-db1}
export POSTGRES_USER=${POSTGRES_USER:-db1}
export POSTGRES_DB=${POSTGRES_DB:-db1}
export SQLALCHEMY_DATABASE_URI="postgresql://db1:db1@postgres/db1"
```

##### Resetting the database
When starting Gapps for the first time, it will automatically create the database models. If you want to reset the data (e.g. delete all data), you can set the `RESET_DB` env variable such as `export RESET_DB=yes`.

##### Running Gapps for development
Sometimes you may want to run Gapps outside of Docker. You can do this by starting the Postgres container and then starting Gapps in the foreground.

1. Uncomment ports declaration [here](https://github.com/bmarsh9/gapps/blob/e8dd926fb946e47fa66f918afa543c535ae212be/docker-compose.yml#L59)
2. Start the postgres container: `docker-compose up -d postgres`
3. Set the following env variables:
```
export POSTGRES_HOST=${POSTGRES_HOST:-localhost}
export POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-db1}
export POSTGRES_USER=${POSTGRES_USER:-db1}
export POSTGRES_DB=${POSTGRES_DB:-db1}
export SQLALCHEMY_DATABASE_URI="postgresql://db1:db1@localhost/db1"
```
4. Run `export FLASK_CONFIG=development;bash run.sh` 
5. Gapps should be running and connected to the database. You can now make changes to the code.

##### Running with Docker Desktop
1. Download the [docker-compose.yml](https://github.com/bmarsh9/gapps/blob/main/docker-compose.yml) file
2. Open up a elevated command prompt and change directories (cd) to where the docker-compose.yml file was downloaded (likely Downloads)
3. Run `docker compose up`

##### View env variables for debugging
```
docker exec -e ONESHOT=yes gapps env
```

##### Perform database migration
```
docker exec -e INIT_MIGRATE=yes -e MIGRATE=yes -e ONESHOT=yes gapps bash run.sh
```
**OR**
```
docker-compose up -d
docker exec -it gapps bash
python3 manage.py db migrate
python3 manage.py db stamp head
python3 manage.py db upgrade
exit
```

##### Creating database manually

Warning - this will delete all data in the database!  
```
docker exec -it gapps bash
python3 tools/check_db_connection.py
python3 tools/check_db_models.py
python3 manage.py init_db
```

##### Upgrading versions
1.) Edit `docker-compose.yml` file with the desired version from [Docker Hub](https://hub.docker.com/r/bmarsh13/gapps/tags). Anywhere you see the old version in the compose file (should be 4 instances), update it with the desired version. (e.g. bmarsh13/gapps:3.3.9 -> bmarsh13/gapps:3.4.0)  
2.) `docker-compose up -d`  
3.) [Perform database migration](https://github.com/bmarsh9/gapps#perform-database-migration) if neccesary 

##### Loading new frameworks into Gapps

You can always create a new Framework and controls within the UI - but this would take a long time. Instead, you can load a JSON file into Gapps. 

The format consists of controls and subcontrols. The snippet below shows an example of a control having one (1) subcontrol however you can add as many as you like. It is not a requirement to have subcontrols for a control (you can have zero). However it may make sense if you want to break down a control into specific actions that are trackable. Let's take the CIS 18 framework as an example. You could place all 18 "domains" as controls and the controls within each domain would be a subcontrol within Gapps.

```
[
    {
        "name": "Limit information system access to authorized users, processes acting on behalf of authorized users or",       
        "description": "Maintain list of authorized users defining their identity and associated role and sync with sys",       
        "guidance": "List approved users, services, and devices, and have logical controls in place to prevent unauthor",
        "ref_code": "AC.L1-3.1.1",
        "system_level": false,
        "subcategory": "Identity & Access Management (IAM)",
        "category": "Access Control",
        "dti": "easy",
        "dtc": "easy",
        "meta": {},
        "subcontrols": [
            {
                "ref_code": "3.1.1.a",
                "name": "Authorized users are identified.",
                "description": "Authorized users are identified.",
                "meta": {},
                "tasks": [
                    {
                        "title": "title of the task",
                        "description": "description of the task"
                    }
                ]
            }
        ]
    }
}
```

Next, save the above JSON format into a file (such as `my_framework.json` but it must end with `.json`). The name of your framework will be taken from the filename when Gapps loads it (`my_framework` in this case). Save the file in the `app/files/base_controls/` directory. You can also change the load directory by setting the `FRAMEWORK_FOLDER` env variable. Once your new framework is saved to a file and sitting in the framework directory, you can go ahead and create a new Tenant within the UI. Gapps will load your framework automatically. If you want to add a framework to a existing Tenant, go to the "Tenants" page, edit the Tenant and click the "Reload Frameworks" button.

##### Settings added in this fork
All settings go in `.env` (see `.env.example` for a complete, commented template).

| Setting | Default | Meaning |
|---|---|---|
| `ADFS_SERVER` | empty | Host name of an on-prem ADFS (`sts.example.com`). Empty = Microsoft Entra ID. Used with `ENABLE_MICROSOFT_AUTH=true` |
| `AUDIT_LOG_ENABLED` / `AUDIT_LOG_PATH` / `AUDIT_LOG_RETENTION_DAYS` | `true` / `/var/log/app/audit.log` / `90` | JSON audit log, one file per day |
| `AUDIT_GUI_ENABLED` / `AUDIT_GUI_RETENTION_DAYS` / `AUDIT_GUI_EVENTS` | `true` / `90` / built-in list | Events that are also shown on the Logs page |
| `RISK_REVIEW_INTERVALS` | `very high=3,high=6,low=12,very low=12` | Months to the next review per risk level |
| `RISK_REMINDER_TO` / `RISK_REMINDER_CC` | `assignee` / empty | Who gets the reminder: `assignee`, `project_managers`, `tenant_owner`, `risk_managers` or fixed email addresses (comma list) |
| `RISK_REMINDER_FALLBACK_TO` | `risk_managers` | Used when the To list is empty for a risk (for example no assignee) |
| `RISK_REMINDER_DAYS_BEFORE` | `7` | First reminder this many days before the review/due date |
| `RISK_REMINDER_OVERDUE_REPEAT_DAYS` | `7` | Repeat every N days once overdue, `0` = never |
| `RISK_REMINDER_EXCLUDE_DOMAINS` | `demo.example.com` | Never send reminders to these domains (protects the demo users) |
| `APP_BASE_URL` | empty | Public address of the app, used for the links in the reminder mails |

##### Risk reminder emails
Reminders are sent by a small script that you run once a day from the docker host, for example from cron.
Try it first with `--dry-run`, which only shows what would be sent:
```
docker exec app python3 tools/send_risk_reminders.py --dry-run
30 7 * * *  docker exec app python3 tools/send_risk_reminders.py
```
The normal `MAIL_*` settings are used. A reminder is sent once per risk, date and interval, so running the script
more often does not send duplicates. The `tools/` folder is part of the image, rebuild it
(`docker compose build app && docker compose up -d app`) after pulling.

##### Backup and restore
```
tools/backup.sh                       # backups/gapps-<date>_<time>/  (database, evidence, reports, audit log, config)
tools/restore.sh --latest             # restore the newest backup, asks for confirmation first
```
Set `BACKUP_PASSPHRASE` to encrypt the configuration (it contains secrets) and `BACKUP_KEEP_DAYS` to control rotation.
See the header of each script for all options. More in `db/README.md`.

##### Demo tenant with example data
Creates a tenant called `demo` with fake users (`@demo.example.com`), 10 projects, subcontrol status, evidence and risks:
```
docker exec app python3 tools/seed_demo.py --frameworks iso_27001_2022
docker exec app python3 tools/seed_demo.py --reset --frameworks iso_27001_2022    # delete and recreate
```
Only the demo tenant is touched. `--delete` removes it again.

##### Updating the database after pulling new code
New columns and tables are added by `tools/apply_schema_updates.py`, which runs when the container starts.
To apply the changes by hand, use the SQL scripts in `db/` (`db/apply.sh`, see `db/README.md`).

##### Building and pushing
```
docker build -t gapps:3.4.3 .
docker tag gapps:3.4.3 bmarsh13/gapps:3.4.3
docker push bmarsh13/gapps:3.4.3
```

##### API Authentication

You can generate an API token by viewing the following route in your browsers
```
# Create token that expires in 15 minutes
<gapps-host>/api/v1/token

# Create token that expires in 30 seconds
<gapps-host>/api/v1/token?expiration=30

# Create token that never expires
<gapps-host>/api/v1/token?expiration=0
```

And here is how you use the token to authenticate (curl as an example)

```
TOKEN="TOKEN HERE"
curl <gapps-host>/api/v1/tenants -H "token: $TOKEN"
```
