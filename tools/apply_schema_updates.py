"""
Idempotent schema updates for columns/tables added after the initial release.

db.create_all() never alters existing tables, so on an existing database the new
risk link table and columns would be missing. This runs at container start
(from run.sh), only changes what is missing, and is safe to run every time.
"""
import os
import sys

# Make the app package importable when run as a script
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text
from app import create_app
from app.models import db, RiskAssociation

# (table, column, SQL type)
NEW_COLUMNS = [
    ("project_subcontrols", "ticket_number", "VARCHAR"),
    ("project_evidence", "link", "VARCHAR"),
    ("risk_register", "likelihood", "INTEGER"),
    ("risk_register", "impact", "INTEGER"),
]

app = create_app(os.getenv("FLASK_CONFIG") or "default")

with app.app_context():
    try:
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()

        # Nothing to update on a brand new database - init_db creates everything
        if "project_subcontrols" not in tables:
            print("[INFO] Schema updates: database not initialised yet, skipping")
            sys.exit(0)

        if "risk_association" not in tables:
            RiskAssociation.__table__.create(bind=db.engine, checkfirst=True)
            print("[INFO] Schema updates: created table risk_association")

        for table, column, coltype in NEW_COLUMNS:
            existing = [c["name"] for c in inspector.get_columns(table)]
            if column not in existing:
                with db.engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}"))
                print(f"[INFO] Schema updates: added {table}.{column}")
        print("[INFO] Schema updates: up to date")
    except SystemExit:
        raise
    except Exception as e:
        # never block startup on this; the app still starts
        print(f"[WARNING] Schema updates failed: {e}")
