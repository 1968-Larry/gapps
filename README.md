# Gapps (fork)

> **This is a fork of [bmarsh9/gapps](https://github.com/bmarsh9/gapps)**, the security compliance
> platform by Brendan Marshall. It is maintained separately, with the changes listed under
> [Added in this fork](#added-in-this-fork-wrench) (on-prem ADFS sign-in, audit logging, risk
> management, exceptions, security fixes and more).
>
> - Questions, bugs and ideas about **this fork**: open an
>   [issue in this repository](https://github.com/1968-Larry/gapps/issues). Please do not
>   contact the original project about anything that only exists here.
> - Security problems: see [SECURITY.md](SECURITY.md) (report privately, not in a public issue).
> - The original project, its documentation and its community are at
>   [bmarsh9/gapps](https://github.com/bmarsh9/gapps).
>
> Licence: the same as the original, AGPL-3.0 with the Commons Clause (see [LICENSE](LICENSE)).

Gapps is a security compliance platform that makes it easy to track your progress against various security frameworks.

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
- Idle and absolute session timeouts with a "stay logged in" warning

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

**Exceptions (deviations)**
- Exceptions tab in every project for approved, time limited deviations from controls, hardening,
  patching or policies: description, justification, compensating controls, affected assets
- Same 4x4 assessment as risks, owner, ticket number, valid from / expiry date (at most
  `EXCEPTION_MAX_VALIDITY_MONTHS`). Active / expired follows from the expiry date
- Approval flow: draft -> submitted -> approved / rejected -> closed. The level decides who
  approves (`EXCEPTION_APPROVERS`, default: CISO for high and very high, security manager for low
  and very low). A higher role may approve lower levels; never the person who requested it; admins
  only when nobody else holds the required role
- Changing an approved exception (assessment, dates, justification ...) asks for confirmation,
  shows what changes and who must approve, and sends it back for approval to the role its new level
  needs. The API refuses such a change (409) unless `confirm_resubmit` is sent
- Linked to sub-controls (Exceptions tab in the control drawer) and, optionally, to risks; shown
  both ways, including a badge in the risk tables (red when an exception has expired)
- Organisation level exceptions (no project), like organisation level risks: can be attached to
  sub-controls in every project and then show up in those projects
- Collection page (menu: Risk > Exceptions) with every exception you may see, filter per state,
  level and project
- Change history, comments and audit log events (`exception_approved`, `exception_rejected`, ...)
- Project summary: risks and exceptions counted per level (open / active, awaiting approval,
  expiring soon, expired, overdue reviews). Exceptions do not change the implementation %
- Expiry reminders by the same daily `tools/send_risk_reminders.py` run

**Roles**
- New tenant role `ciso`: reads every project of the organisation without being a member, works in
  the risk module and approves exceptions of every level. Changes inside a project still need a
  project role
- `riskmanager` is shown as "Security manager" (the technical name is unchanged). Security managers
  see and approve exceptions in every project
- Fixed: the reminder recipient `risk_managers` (also the default fallback) found nobody, because it
  read an old, unused role table. New recipient token `ciso`

**Controls and evidence**
- Custom controls and sub-controls: choose the reference code, rename, and add sub-controls
- Ticket number on sub-controls and a link field on evidence
- Planned end date on sub-controls; an overdue mark in the control drawer when the date has passed
  and the sub-control is not complete (fully implemented with evidence)
- Deadlines page (menu: Deadlines): what has to be done when, over the projects you can open:
  planned end of sub-controls, review and due dates of open risks and expiry of approved
  exceptions (same rules as the reminder mails). Filter on owner (default: me), projects, type,
  status (overdue / upcoming / complete / without a date) and a date range; organisation level
  risks and exceptions are on by default, review dates of accepted risks on request. Grouped per
  month or per project, with sub-controls under their control and risks / exceptions in their own
  block; a row opens the item (`?risk-id=` / `?exception-id=` links)
- "Reload frameworks" for existing tenants

**Reports (project > Report)**
- Statement of Applicability: every control with applicability, implementation, justification,
  owner, evidence and the exceptions that apply; controls excluded without a justification are
  highlighted
- Risk register and exception register (with the approval trail)
- Each as PDF (landscape, page numbers, who generated it) and as CSV for Excel (semicolon separated,
  UTF-8 with BOM)
- The Executive / Technical report also show open risks per level and the exceptions

**Reports across projects (More > Reports)**
- Pick the projects (and whether organisation level risks and exceptions are included); an overview
  per project shows implemented, evidence, gaps, open risks and exceptions
- Gap report: a summary per project, sub-controls excluded without a justification and the
  sub-controls that are not done (not implemented / not complete / missing evidence), grouped by project
- Common gaps: the same sub-control over the selected projects as one row, the gaps found in most
  projects first, with the status in each project (the Gaps page as a report)
- Risk register and exception register over the selected projects
- Everybody reports on the projects they can open; the CISO on every project

**Reporting across projects**
- Gaps page (menu: More > gaps): sub-controls grouped across all projects to show common gaps.
  Filter on status (not complete, not implemented, partial, missing evidence ...), framework and
  chosen projects. CSV export

**Deployment and operations**
- Browser libraries served locally (on-prem / air-gapped) or from a CDN with SRI hashes, one setting
  (`ASSET_MODE`), the same pinned versions either way; Content-Security-Policy header
- Dependabot for Python, browser libraries, Tailwind, Docker base image and GitHub Actions; a workflow
  copies updated browser libraries into the PR
- Docker: proxy and internal pip mirror settings for builds, `.env.example` and `docker-compose.override.yml.example`
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

#### Captures of the features added in this fork
Screenshots with the demo data from `tools/seed_demo.py`.

Project summary with risks and exceptions          |
:-------------------------:|
![](img/gapps_project_summary_risks_exceptions.png)  |

Exceptions of a project          |
:-------------------------:|
![](img/gapps_exceptions_project.png)  |

All exceptions of the organisation          |
:-------------------------:|
![](img/gapps_exceptions_all.png)  |

Exception details          |
:-------------------------:|
![](img/gapps_exception_details.png)  |

Level based approval (here by the CISO)          |
:-------------------------:|
![](img/gapps_exception_approval.png)  |

Confirmation before an approved exception goes back for approval          |
:-------------------------:|
![](img/gapps_exception_resubmit.png)  |

Exceptions on a sub-control          |
:-------------------------:|
![](img/gapps_subcontrol_exceptions.png)  |

Exceptions linked to a risk          |
:-------------------------:|
![](img/gapps_risk_linked_exceptions.png)  |

Statement of Applicability (PDF)          |
:-------------------------:|
![](img/gapps_report_soa.png)  |

Exception register (PDF)          |
:-------------------------:|
![](img/gapps_report_exceptions.png)  |

Reports across projects          |
:-------------------------:|
![](img/gapps_org_reports.png)  |

Gap report over several projects (PDF)          |
:-------------------------:|
![](img/gapps_report_gaps.png)  |

### Getting Started

This fork is run from source with Docker Compose (there are no published images for it; the
images on Docker Hub, `bmarsh13/gapps`, are the original project without the changes of this fork).

```
git clone https://github.com/1968-Larry/gapps.git
cd gapps
cp .env.example .env                      # set SECRET_KEY, HOST_NAME, mail, sign-in ...
cp docker-compose.override.yml.example docker-compose.override.yml   # volumes, .env
docker compose build app
docker compose up -d
```

Updating: `git pull`, then `docker compose build app && docker compose up -d`. Schema changes
are applied when the container starts (see [Updating the database](#updating-the-database-after-pulling-new-code)).
The general documentation of the original project is at
[web-gapps.pages.dev/docs](https://web-gapps.pages.dev/docs).


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

1. Make sure the postgres service publishes port 5432 (it does in `docker-compose.yml`)
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
1. Clone this repository (or download it as a ZIP from GitHub) and open a command prompt in the folder
2. Copy `.env.example` to `.env` and set at least `SECRET_KEY`
3. Run `docker compose up --build`

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
1.) `git pull`  
2.) `docker compose build app && docker compose up -d`  
3.) [Perform database migration](#perform-database-migration) if necessary (normally not: new
columns and tables are added at start, see below)

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
| `SESSION_IDLE_TIMEOUT_MINUTES` / `SESSION_ABSOLUTE_TIMEOUT_HOURS` | `30` / `4` | Logout after inactivity / this long after login, whatever the activity. A warning is shown 2 / 10 minutes before. Expiry is logged as `session_expired` (reason `idle` or `absolute`). `0` = off |
| `SESSION_COOKIE_SECURE` | `true` when `HOST_NAME` is https | Send the session cookie over https only |
| `AUDIT_LOG_ENABLED` / `AUDIT_LOG_PATH` / `AUDIT_LOG_RETENTION_DAYS` | `true` / `/var/log/app/audit.log` / `90` | JSON audit log, one file per day |
| `AUDIT_GUI_ENABLED` / `AUDIT_GUI_RETENTION_DAYS` / `AUDIT_GUI_EVENTS` | `true` / `90` / built-in list | Events that are also shown on the Logs page |
| `RISK_REVIEW_INTERVALS` | `very high=3,high=6,low=12,very low=12` | Months to the next review per risk level |
| `RISK_REMINDER_TO` / `RISK_REMINDER_CC` | `assignee` / empty | Who gets the reminder: `assignee`, `project_managers`, `tenant_owner`, `risk_managers`, `ciso` or fixed email addresses (comma list) |
| `RISK_REMINDER_FALLBACK_TO` | `risk_managers` | Used when the To list is empty for a risk (for example no assignee) |
| `RISK_REMINDER_DAYS_BEFORE` | `7` | First reminder this many days before the review/due date |
| `RISK_REMINDER_OVERDUE_REPEAT_DAYS` | `7` | Repeat every N days once overdue, `0` = never |
| `RISK_REMINDER_EXCLUDE_DOMAINS` | `demo.example.com` | Never send reminders to these domains (protects the demo users) |
| `APP_BASE_URL` | empty | Public address of the app, used for the links in the reminder mails |
| `EXCEPTION_MAX_VALIDITY_MONTHS` | `12` | Longest validity of an exception from approval, `0` = no limit |
| `EXCEPTION_EXPIRING_SOON_DAYS` | `30` | "Expiring soon" is shown this many days before the expiry date |
| `EXCEPTION_APPROVERS` | `very high=ciso,high=ciso,low=riskmanager,very low=riskmanager` | Who approves each level: `project_manager`, `riskmanager` (Security manager) or `ciso`, from low to high. A higher role may approve lower levels; admins only when nobody else holds the role |
| `EXCEPTION_ALLOW_SELF_APPROVAL` | `false` | Let the requester approve their own exception (only for one-person setups) |
| `EXCEPTION_REMINDERS_ENABLED` | `true` | Expiry reminders for approved exceptions, sent with the `RISK_REMINDER_*` rules and recipients |
| `SECRET_KEY` | none, required | Signs session cookies and tokens. gapps refuses to start when it is empty or the default |
| `LOGIN_MAX_FAILED` / `LOGIN_LOCK_MINUTES` | `10` / `15` | Lock a local account after this many wrong passwords in a row, for this many minutes (`0` = off). Logged as `account_locked` |
| `API_TOKEN_MAX_DAYS` | `90` | Longest lifetime of API tokens, also for `expiration=0`. `DELETE /api/v1/token` revokes all your tokens, `DELETE /api/v1/users/<id>/tokens` those of a user you manage |
| `UPLOAD_MAX_MB` / `UPLOAD_ALLOWED_EXTENSIONS` | `50` / office, text, image and archive types | Largest upload (413 above it) and allowed file extensions (415 otherwise, `*` = any) |
| `HSTS_MAX_AGE` | `31536000` | `Strict-Transport-Security` max-age when `HOST_NAME` is https (`0` = off) |
| `TRUSTED_PROXIES` | empty | Reverse proxies (IPs/networks). Their `X-Forwarded-For` is read from the right to find the client (audit log, `request.remote_addr`), `X-Forwarded-Proto` sets the scheme. Check with `/api/v1/admin/client-ip` (platform admins). HAProxy needs `option forwardfor` and `http-request set-header X-Forwarded-Proto https` |
| `ASSET_MODE` | `local` | `local` = CSS/JS from `app/static/vendor` (no internet needed), `cdn` = from `ASSET_CDN_URL` with SRI hashes |
| `ASSET_CDN_URL` | `https://cdn.jsdelivr.net/npm` | npm CDN with the jsDelivr layout `<url>/<package>@<version>/<file>` |
| `CSP_MODE` | `report-only` | Content-Security-Policy header: `off`, `report-only` (violations only in the browser console) or `enforce` |
| `PIP_INDEX_URL` / `PIP_TRUSTED_HOST` | empty | Internal pip mirror for `docker compose build` (empty = pypi.org) |

##### Third-party libraries and updates
The browser libraries (Alpine.js, TinyMCE, ag-grid, flatpickr ...) are pinned in `vendor/package.json`.
`vendor/assets.json` maps each file in `app/static/vendor/` to a file in one of those packages. The files
and `app/static/vendor/manifest.json` (installed versions and SRI hashes) are committed to git, so a server
needs neither npm nor internet: `git pull` and rebuild.

- `ASSET_MODE=local` serves them from the app, `ASSET_MODE=cdn` loads the same version from the CDN with an
  `integrity` hash taken from the committed file, so the browser refuses anything that differs from git.
- Templates use `{{ vendor_js('path') }}`, `{{ vendor_css('path') }}` and `{{ vendor_url('path') }}` with the
  path below `app/static/vendor/`, never a hard-coded URL.
- Dependabot (`.github/dependabot.yml`) opens monthly PRs for `vendor/`, `tl_src/`, `requirements.txt`, the
  Dockerfile base image and the GitHub Actions; minor and patch updates are grouped. Security updates come
  right away when "Dependabot security updates" is on in the repository settings.
- The `vendor-sync` workflow runs on every change to `vendor/package.json` (including Dependabot PRs),
  copies the new files to `app/static/vendor/` and commits them to the same branch. Review, merge, pull.
- By hand (Node 18+ and internet): edit `vendor/package.json` or `vendor/assets.json`, run
  `bash scripts/vendor-assets.sh` and commit `vendor/package-lock.json` and `app/static/vendor/`.
- Python 3.12 (image `python:3.12-slim`), Flask 3.1, SQLAlchemy 1.4 with Flask-SQLAlchemy 3.0.
  `requirements.txt` holds minimum versions (the fixed releases of known vulnerabilities); Dependabot keeps
  them current. SQLAlchemy 2 / Flask-SQLAlchemy 3.1 need code changes and are left out of its updates.
- TinyMCE 7 and later are licensed GPL-2.0-or-later (compatible with the AGPL-3.0 of gapps); the editor
  configs set `license_key: 'gpl'`. `app/static/js/tinymce-compat.js` keeps the older tinymce-variable
  plugin working.
- `manage.py` uses Flask's CLI (Flask-Script is gone): `python3 manage.py init_db`, `create_db`,
  `migrate_db`, `force_drop_db`, `db <flask-migrate command>`.

##### Tests (GitHub Actions, `.github/workflows/ci.yml`)
Every push, every PR (Dependabot's included) and every Monday:
- builds the image, starts gapps with Postgres and demo data, logs in over HTTP
- `tools/smoke_test.py`: every GET page and API endpoint; fails on 5xx or a missing static file
  (`KNOWN_BROKEN` lists endpoints that were already broken upstream)
- `tools/browser_test.py`: TinyMCE with the gapps settings and the main pages in Chromium; fails on new
  JavaScript errors (`tools/browser/known_errors.txt` lists the ones that were there before) and lists
  CSP violations
- `tools/check_cdn_assets.py`: the CDN files are byte for byte the committed ones (SRI)
- pip-audit on the installed Python packages, npm audit on the shipped browser libraries and the
  Tailwind tools
When `vendor/package.json` changes, ci waits for vendor-sync, which commits the files and starts ci.

##### Risk reminder emails
Reminders are sent by a small script that you run once a day from the docker host, for example from cron.
Try it first with `--dry-run`, which only shows what would be sent:
```
docker exec app python3 tools/send_risk_reminders.py --dry-run
30 7 * * *  docker exec app python3 tools/send_risk_reminders.py
```
The same run reminds the owners of approved exceptions about the expiry date (`EXCEPTION_REMINDERS_ENABLED`).
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
Creates a tenant called `demo` with fake users (`@demo.example.com`, one of them CISO and two security managers), 10 projects, subcontrol status, evidence, risks linked to the controls they concern, and exceptions in every state (active, renewed, expiring, expired, awaiting approval, rejected and reworked, draft, closed) with a back-dated history, comments and organisation level exceptions across projects, and planned end dates on sub-controls (some overdue) for the Deadlines page. The curated content is in `tools/demo_data.py`:
```
docker exec app python3 tools/seed_demo.py                      # SOC 2, ISO 27001:2022 and NIST CSF 2.0
docker exec app python3 tools/seed_demo.py --reset              # delete and recreate
docker exec app python3 tools/seed_demo.py --frameworks iso_27001_2022
docker exec app python3 tools/seed_demo.py --deadlines          # only (re)set planned end dates (Deadlines page)
```
Only the demo tenant is touched. `--delete` removes it again.

##### Updating the database after pulling new code
New columns and tables are added by `tools/apply_schema_updates.py`, which runs when the container starts.
To apply the changes by hand, use the SQL scripts in `db/` (`db/apply.sh`, see `db/README.md`).

##### Building the image
```
docker compose build app
```
Do not push images of this fork as `bmarsh13/gapps`: that name belongs to the original project.

##### API Authentication

You can generate an API token by viewing the following route in your browsers
```
# Create token that expires in 15 minutes
<gapps-host>/api/v1/token

# Create token that expires in 30 seconds
<gapps-host>/api/v1/token?expiration=30

# Create a token with the longest allowed lifetime (API_TOKEN_MAX_DAYS, 90 days)
<gapps-host>/api/v1/token?expiration=0

# Revoke all your API tokens (for example when one has leaked)
curl -X DELETE <gapps-host>/api/v1/token -H "token: $TOKEN"
```

And here is how you use the token to authenticate (curl as an example)

```
TOKEN="TOKEN HERE"
curl <gapps-host>/api/v1/tenants -H "token: $TOKEN"
```
