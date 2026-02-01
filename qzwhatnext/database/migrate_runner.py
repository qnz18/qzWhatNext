"""Database migration runner for production.

Goal:
- Prefer Alembic migrations for deterministic schema management.
- If the database is already at the desired schema but Alembic history is out of sync
  (e.g., tables exist but Alembic wasn't tracking), detect that safely and `stamp head`.

This is intended to be executed as a one-off Cloud Run Job during deploys.
"""

from __future__ import annotations

import os
import sys
from typing import List, Tuple

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from qzwhatnext.database.database import DATABASE_URL, _is_sqlite_url, build_engine


def _alembic_cfg() -> Config:
    cfg = Config(os.getenv("ALEMBIC_INI", "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    return cfg


def _table_exists(conn, table: str) -> bool:
    # Postgres: to_regclass returns null if missing.
    row = conn.execute(text("SELECT to_regclass(:t)"), {"t": table}).fetchone()
    return bool(row and row[0])


def _column_exists(conn, table: str, column: str) -> bool:
    row = conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).fetchone()
    return bool(row)


def _required_schema_checks() -> List[Tuple[str, str]]:
    """Return (kind, name) checks required to safely stamp head."""
    return [
        ("table", "users"),
        ("table", "tasks"),
        ("table", "scheduled_blocks"),
        ("table", "google_oauth_tokens"),
        ("table", "recurring_task_series"),
        ("table", "recurring_time_blocks"),
        # tasks columns referenced by runtime
        ("column:tasks", "user_id"),
        ("column:tasks", "deleted_at"),
        ("column:tasks", "recurrence_series_id"),
        ("column:tasks", "recurrence_occurrence_start"),
        ("column:tasks", "start_after"),
        ("column:tasks", "due_by"),
        # scheduled_blocks columns referenced by runtime
        ("column:scheduled_blocks", "calendar_event_etag"),
        ("column:scheduled_blocks", "calendar_event_updated_at"),
    ]


def _missing_requirements(conn) -> List[str]:
    missing: List[str] = []
    for kind, name in _required_schema_checks():
        if kind == "table":
            if not _table_exists(conn, name):
                missing.append(f"missing table: {name}")
        elif kind.startswith("column:"):
            table = kind.split(":", 1)[1]
            if not _column_exists(conn, table, name):
                missing.append(f"missing column: {table}.{name}")
        else:
            missing.append(f"unknown check: {kind} {name}")
    return missing


def main() -> int:
    if _is_sqlite_url(DATABASE_URL):
        # In dev/test, Alembic isn't required; but running upgrade is harmless when used.
        command.upgrade(_alembic_cfg(), "head")
        return 0

    engine = build_engine(DATABASE_URL)

    try:
        command.upgrade(_alembic_cfg(), "head")
        return 0
    except Exception as e:
        msg = str(e).lower()
        looks_like_already_applied = any(
            s in msg
            for s in [
                "duplicate",
                "already exists",
                "duplicate_table",
                "relation",
                "exists",
            ]
        )
        if not looks_like_already_applied:
            raise

        # Only stamp head if we can verify the expected schema is present.
        with engine.begin() as conn:
            missing = _missing_requirements(conn)
        if missing:
            raise RuntimeError(
                "Alembic upgrade failed and schema is not at expected baseline; refusing to stamp head. "
                + "; ".join(missing)
            ) from e

        command.stamp(_alembic_cfg(), "head")
        return 0


if __name__ == "__main__":
    sys.exit(main())

