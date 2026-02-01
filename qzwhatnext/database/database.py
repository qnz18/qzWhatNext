"""Database connection and session management for qzWhatNext.

This module supports both:
- Local SQLite (default for dev/MVP)
- PostgreSQL (Cloud SQL in production) via `DATABASE_URL`
"""

import os
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.declarative import declarative_base
from dotenv import load_dotenv

load_dotenv()

# Database URL - SQLite by default (local dev/MVP)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./qzwhatnext.db")

def _is_sqlite_url(database_url: str) -> bool:
    return "sqlite" in (database_url or "")


def get_engine_kwargs(database_url: str) -> dict:
    """Return deterministic create_engine kwargs for a DB URL.

    This is separated to allow deterministic unit testing without connecting.
    """
    engine_kwargs: dict = {
        "echo": os.getenv("DEBUG", "False").lower() == "true",
        # Helps avoid stale DB connections (important for Cloud Run + Cloud SQL).
        "pool_pre_ping": True,
    }

    if _is_sqlite_url(database_url):
        # SQLite-specific setting required for FastAPI concurrency in a single process.
        engine_kwargs["connect_args"] = {"check_same_thread": False}
        return engine_kwargs

    # Postgres (Cloud SQL) / other DBs:
    # Keep pooling conservative to avoid exhausting Cloud SQL max connections.
    # These values are intentionally small and can be tuned via env later if needed.
    engine_kwargs["pool_size"] = int(os.getenv("DB_POOL_SIZE", "5"))
    engine_kwargs["max_overflow"] = int(os.getenv("DB_MAX_OVERFLOW", "5"))
    engine_kwargs["pool_timeout"] = int(os.getenv("DB_POOL_TIMEOUT_SEC", "30"))
    return engine_kwargs


def build_engine(database_url: str) -> Engine:
    return create_engine(database_url, **get_engine_kwargs(database_url))


# Create engine (module-level singleton)
engine = build_engine(DATABASE_URL)


@event.listens_for(Engine, "connect")
def set_sqlite_pragmas(dbapi_conn, connection_record):
    """Set SQLite PRAGMA statements on connection for better concurrency and foreign key support."""
    if _is_sqlite_url(DATABASE_URL):
        cursor = dbapi_conn.cursor()
        # Enable foreign keys (required for referential integrity)
        cursor.execute("PRAGMA foreign_keys=ON")
        # Enable WAL mode for better concurrency (allows concurrent reads during writes)
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for declarative models
Base = declarative_base()

def _sqlite_table_has_column(dbapi_conn, table_name: str, column_name: str) -> bool:
    cursor = dbapi_conn.cursor()
    try:
        cursor.execute(f"PRAGMA table_info({table_name})")
        cols = [row[1] for row in cursor.fetchall()]  # row[1] is column name
        return column_name in cols
    finally:
        cursor.close()


def ensure_legacy_schema_compat(*, engine_override: Engine = None, database_url_override: str = None) -> None:
    """Ensure legacy SQLite DB files are compatible with the current schema.

    This is intentionally minimal and deterministic: if the DB was created before we
    introduced multi-user support, it may be missing `tasks.user_id`. SQLite
    `create_all()` does not alter existing tables, so we patch the column in place.
    """
    database_url = database_url_override or DATABASE_URL
    if not _is_sqlite_url(database_url):
        return

    use_engine = engine_override or engine

    # Use raw DB-API connection for PRAGMA and ALTER TABLE
    dbapi_conn = use_engine.raw_connection()
    try:
        # If tasks exists but lacks user_id, add it (nullable for legacy rows).
        if _sqlite_table_has_column(dbapi_conn, "tasks", "id") and not _sqlite_table_has_column(dbapi_conn, "tasks", "user_id"):
            cursor = dbapi_conn.cursor()
            try:
                cursor.execute("ALTER TABLE tasks ADD COLUMN user_id VARCHAR")
                cursor.execute("CREATE INDEX IF NOT EXISTS ix_tasks_user_id ON tasks (user_id)")
                dbapi_conn.commit()
            finally:
                cursor.close()

        # If scheduled_blocks exists but lacks newly-added calendar sync metadata columns, add them.
        if _sqlite_table_has_column(dbapi_conn, "scheduled_blocks", "id"):
            cursor = dbapi_conn.cursor()
            try:
                if not _sqlite_table_has_column(dbapi_conn, "scheduled_blocks", "calendar_event_etag"):
                    cursor.execute("ALTER TABLE scheduled_blocks ADD COLUMN calendar_event_etag VARCHAR")
                if not _sqlite_table_has_column(dbapi_conn, "scheduled_blocks", "calendar_event_updated_at"):
                    cursor.execute("ALTER TABLE scheduled_blocks ADD COLUMN calendar_event_updated_at DATETIME")
                dbapi_conn.commit()
            finally:
                cursor.close()
    finally:
        dbapi_conn.close()


def get_db() -> Session:
    """Get database session (dependency for FastAPI)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize database schema.

    - SQLite (default dev): use `create_all()` and apply minimal legacy patches.
    - PostgreSQL (Cloud SQL): prefer Alembic migrations for deterministic schema.
      Enable by setting `RUN_MIGRATIONS=true` in the environment.
    """
    run_migrations = os.getenv("RUN_MIGRATIONS", "False").lower() == "true"
    if run_migrations and not _is_sqlite_url(DATABASE_URL):
        # Run Alembic migrations in-process (non-interactive).
        # This keeps Cloud Run deployments simple; if multiple instances race, the
        # migrations are idempotent at the DB level for our current use.
        from alembic import command
        from alembic.config import Config

        alembic_cfg = Config(os.getenv("ALEMBIC_INI", "alembic.ini"))
        # Ensure Alembic uses the same runtime DB URL.
        alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
        command.upgrade(alembic_cfg, "head")
        return

    # Default behavior: create schema directly.
    Base.metadata.create_all(bind=engine)
    ensure_legacy_schema_compat()

    # Minimal, idempotent Postgres compatibility patch.
    #
    # If Cloud Run deploys with Postgres but without running Alembic migrations,
    # create_all() will not add new columns to existing tables.
    if not _is_sqlite_url(DATABASE_URL):
        with engine.begin() as conn:
            # Tasks: start_after / due_by (date-only constraints)
            conn.execute(
                text(
                    "ALTER TABLE tasks "
                    "ADD COLUMN IF NOT EXISTS start_after DATE"
                )
            )
            conn.execute(
                text(
                    "ALTER TABLE tasks "
                    "ADD COLUMN IF NOT EXISTS due_by DATE"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_tasks_start_after ON tasks (start_after)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_tasks_due_by ON tasks (due_by)"
                )
            )

            conn.execute(
                text(
                    "ALTER TABLE scheduled_blocks "
                    "ADD COLUMN IF NOT EXISTS calendar_event_etag VARCHAR"
                )
            )
            conn.execute(
                text(
                    "ALTER TABLE scheduled_blocks "
                    "ADD COLUMN IF NOT EXISTS calendar_event_updated_at TIMESTAMP"
                )
            )

