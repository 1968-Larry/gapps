"""
Send email reminders about risks whose review date or due date is close or has
passed. Meant to run once a day from outside the app, for example:

    # crontab on the docker host, 07:30 every day
    30 7 * * *  docker exec <app-container> python3 tools/send_risk_reminders.py

    python3 tools/send_risk_reminders.py --dry-run          # show, do not send
    python3 tools/send_risk_reminders.py --today 2026-11-01 # pretend it is that day

Settings are read from the environment (see RISK_REMINDER_* and APP_BASE_URL in
.env.example) and the normal MAIL_* settings are used to send. Exit code 1 means
at least one mail could not be sent (it is retried at the next run).
"""
import argparse
import os
import sys
from datetime import datetime

# Make the app package importable when run as a script
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.utils.risk_reminders import run


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="show what would be sent, send nothing")
    parser.add_argument("--today", help="YYYY-MM-DD, run as if this were today (for testing)")
    args = parser.parse_args()

    today = datetime.strptime(args.today, "%Y-%m-%d").date() if args.today else None
    app = create_app(os.getenv("FLASK_CONFIG") or "default")
    with app.app_context():
        _, failed = run(app, dry_run=args.dry_run, today=today)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
