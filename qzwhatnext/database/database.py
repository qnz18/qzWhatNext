"""Database connection and session management for qzWhatNext."""

import os
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.declarative import declarative_base
from dotenv import load_dotenv

load_dotenv()

# Database URL - SQLite for MVP
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./qzwhatnext.db")

# Create engine
connect_args = {}
if "sqlite" in DATABASE_URL:
    connect_args["check_same_thread"] = False

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    echo=os.getenv("DEBUG", "False").lower() == "true"
)


@event.listens_for(Engine, "connect")
def set_sqlite_pragmas(dbapi_conn, connection_record):
    """Set SQLite PRAGMA statements on connection for better concurrency and foreign key support."""
    if "sqlite" in DATABASE_URL:
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


def ensure_legacy_schema_compat() -> None:
    """Ensure legacy SQLite DB files are compatible with the current schema.

    This is intentionally minimal and deterministic: if the DB was created before we
    introduced multi-user support, it may be missing `tasks.user_id`. SQLite
    `create_all()` does not alter existing tables, so we patch the column in place.
    """
    if "sqlite" not in DATABASE_URL:
        return

    # Use raw DB-API connection for PRAGMA and ALTER TABLE
    dbapi_conn = engine.raw_connection()
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
    """Initialize database - create all tables."""
    Base.metadata.create_all(bind=engine)
    ensure_legacy_schema_compat()

