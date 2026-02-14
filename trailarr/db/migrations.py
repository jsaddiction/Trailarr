"""Lightweight database migration system."""

import logging
import sqlite3
from typing import Callable

log = logging.getLogger("TrailArr.Migrations")

Migration = tuple[int, str, Callable[[sqlite3.Connection], None]]

VERSION_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _get_current_version(conn: sqlite3.Connection) -> int:
    """Get current schema version, returning 0 if table doesn't exist."""
    try:
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        return row[0] or 0
    except sqlite3.OperationalError:
        return 0


def _get_existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """Get set of column names for a table."""
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cursor.fetchall()}


def _migration_001_add_retry_columns(conn: sqlite3.Connection) -> None:
    """Add retry tracking columns to downloads table."""
    existing = _get_existing_columns(conn, "downloads")

    if "retry_count" not in existing:
        conn.execute("ALTER TABLE downloads ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0")
    if "last_attempted" not in existing:
        conn.execute("ALTER TABLE downloads ADD COLUMN last_attempted TEXT")
    if "created_at" not in existing:
        conn.execute("ALTER TABLE downloads ADD COLUMN created_at TEXT NOT NULL DEFAULT (datetime('now'))")


def _migration_002_add_imdb_id(conn: sqlite3.Connection) -> None:
    """Add imdb_id column to downloads table."""
    existing = _get_existing_columns(conn, "downloads")

    if "imdb_id" not in existing:
        conn.execute("ALTER TABLE downloads ADD COLUMN imdb_id TEXT")


# Register all migrations here, in order
MIGRATIONS: list[Migration] = [
    (1, "Add retry tracking columns (retry_count, last_attempted, created_at)", _migration_001_add_retry_columns),
    (2, "Add imdb_id column to downloads", _migration_002_add_imdb_id),
]


def run_migrations(conn: sqlite3.Connection) -> None:
    """Run all pending migrations."""
    conn.execute(VERSION_TABLE_DDL)
    conn.commit()

    current = _get_current_version(conn)
    pending = [m for m in MIGRATIONS if m[0] > current]

    if not pending:
        log.debug("Database schema is up to date (version %d)", current)
        return

    for version, description, migrate_fn in pending:
        log.info("Applying migration %d: %s", version, description)
        try:
            migrate_fn(conn)
            conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)", (version,)
            )
            conn.commit()
            log.info("Migration %d applied successfully", version)
        except Exception:
            conn.rollback()
            log.exception("Migration %d failed, rolling back", version)
            raise
