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
        # SQLite ALTER TABLE only accepts constant defaults, not function calls
        # Add column as nullable first, populate it, then we rely on app-level defaults
        conn.execute("ALTER TABLE downloads ADD COLUMN created_at TEXT")
        # Set current timestamp for existing rows
        conn.execute("UPDATE downloads SET created_at = datetime('now') WHERE created_at IS NULL")


def _migration_002_add_imdb_id(conn: sqlite3.Connection) -> None:
    """Add imdb_id column to downloads table."""
    existing = _get_existing_columns(conn, "downloads")

    if "imdb_id" not in existing:
        conn.execute("ALTER TABLE downloads ADD COLUMN imdb_id TEXT")


def _migration_003_create_provider_state(conn: sqlite3.Connection) -> None:
    """Create provider_state table for tracking rate limits."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS provider_state (
            provider_name TEXT PRIMARY KEY,
            rate_limited_until_utc TEXT,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)


def _migration_004_add_last_queried(conn: sqlite3.Connection) -> None:
    """Add last_queried_utc column to track provider query TTL per movie."""
    existing = _get_existing_columns(conn, "downloads")

    if "last_queried_utc" not in existing:
        conn.execute("ALTER TABLE downloads ADD COLUMN last_queried_utc TEXT")


# Register all migrations here, in order
MIGRATIONS: list[Migration] = [
    (1, "Add retry tracking columns (retry_count, last_attempted, created_at)", _migration_001_add_retry_columns),
    (2, "Add imdb_id column to downloads", _migration_002_add_imdb_id),
    (3, "Create provider_state table for rate limit tracking", _migration_003_create_provider_state),
    (4, "Add last_queried_utc for provider query TTL", _migration_004_add_last_queried),
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
