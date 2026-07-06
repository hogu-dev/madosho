from __future__ import annotations

import asyncio

import procrastinate
from sqlalchemy import inspect

from madosho_server import auth, db
from madosho_server.settings import Settings, pg_conninfo


def seed_admin_user(settings: Settings) -> None:
    """Create an admin user from MADOSHO_BOOTSTRAP_ADMIN_USER/PASSWORD iff both are set
    AND no active admin user exists. Idempotent; safe to leave configured."""
    if not (settings.bootstrap_admin_user and settings.bootstrap_admin_password):
        return
    with db.SessionLocal() as session:
        if session.query(db.User).filter_by(scope="admin", is_active=True).count() > 0:
            return
        try:
            auth.create_user(session, settings.bootstrap_admin_user,
                             settings.bootstrap_admin_password, "admin")
        except ValueError:
            pass        # raced or username already taken; nothing to do


async def _apply_procrastinate_schema(conninfo: str) -> None:
    queue = procrastinate.App(connector=procrastinate.PsycopgConnector(conninfo=conninfo))
    async with queue.open_async():
        await queue.schema_manager.apply_schema_async()


def init_database(database_url: str) -> None:
    """Create the app tables and the procrastinate queue tables. Idempotent.

    The compose `init` one-shot re-runs on every `docker compose up`, so this
    must be safe to re-run against an already-initialised database. The app
    tables use CREATE IF NOT EXISTS; procrastinate's schema uses bare CREATE
    statements (no IF NOT EXISTS), so we apply it only when its tables are
    absent — otherwise a second run would raise "relation already exists" and
    the init container would fail, blocking app/worker startup.
    """
    db.configure_engine(database_url)
    db.create_all()
    seed_admin_user(Settings.from_env())
    if not inspect(db.engine).has_table("procrastinate_jobs"):
        asyncio.run(_apply_procrastinate_schema(pg_conninfo(database_url)))
