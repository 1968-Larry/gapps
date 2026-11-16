"""Command line tasks. Same commands as before (Flask-Script is gone, this uses
Flask's own click based CLI):

    python3 manage.py init_db         # drop and recreate all tables, default user and roles
    python3 manage.py create_db       # create missing tables, default user and roles
    python3 manage.py migrate_db      # alembic upgrade to head
    python3 manage.py force_drop_db   # drop every table in the database
    python3 manage.py db <command>    # Flask-Migrate (init, migrate, upgrade, stamp ...)
    python3 manage.py --help
"""
import click
from flask.cli import FlaskGroup

from app import create_app
from app.commands import create_db, force_drop_all_tables, init_db, migrate_db


@click.group(cls=FlaskGroup, create_app=create_app, add_version_option=False)
def cli():
    """gapps management commands."""


@cli.command("init_db")
def init_db_command():
    """Initialize the database (deletes all data)."""
    init_db()
    print("[INFO] Database has been initialized.")


@cli.command("create_db")
def create_db_command():
    """Create the database. Existing tables are left as they are."""
    create_db()
    print("[INFO] Database has been created.")


@cli.command("migrate_db")
def migrate_db_command():
    """Upgrade the database to the newest migration."""
    migrate_db()
    print("[INFO] Database has been migrated.")


@cli.command("force_drop_db")
def force_drop_db_command():
    """Force drop all tables in the database."""
    force_drop_all_tables()


if __name__ == "__main__":
    cli()
