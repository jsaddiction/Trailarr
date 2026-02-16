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


def _migration_005_create_movie_provider_failures(conn: sqlite3.Connection) -> None:
    """Create movie_provider_failures table for tracking permanent failures per movie/provider."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS movie_provider_failures (
            tmdb_id INTEGER NOT NULL,
            provider_name TEXT NOT NULL,
            failure_type TEXT NOT NULL,
            failed_at TEXT NOT NULL DEFAULT (datetime('now')),
            retry_after_utc TEXT,
            PRIMARY KEY (tmdb_id, provider_name)
        )
    """)


def _migration_006_add_provider_to_downloads(conn: sqlite3.Connection) -> None:
    """Add provider_name column to downloads for per-provider query tracking."""
    existing = _get_existing_columns(conn, "downloads")

    if "provider_name" not in existing:
        conn.execute("ALTER TABLE downloads ADD COLUMN provider_name TEXT")
        # Backfill existing downloads based on URL patterns
        conn.execute("UPDATE downloads SET provider_name = 'YouTube' WHERE url LIKE '%youtube.com%' OR url LIKE '%youtu.be%'")
        conn.execute("UPDATE downloads SET provider_name = 'IMDb' WHERE url LIKE '%imdb.com%'")
        conn.execute("UPDATE downloads SET provider_name = 'AppleTV' WHERE url LIKE '%apple.com%' OR url LIKE '%itunes.apple.com%'")
        conn.execute("UPDATE downloads SET provider_name = 'TMDB' WHERE provider_name IS NULL")  # Fallback


def _migration_007_create_movie_provider_queries(conn: sqlite3.Connection) -> None:
    """Create movie_provider_queries table and migrate existing last_queried_utc data."""
    # Create the new table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS movie_provider_queries (
            tmdb_id INTEGER NOT NULL,
            provider_name TEXT NOT NULL,
            last_queried_utc TEXT NOT NULL,
            query_count INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (tmdb_id, provider_name)
        )
    """)

    # Migrate existing last_queried_utc data from downloads table
    # Group by tmdb_id and provider_name, take the MAX(last_queried_utc)
    conn.execute("""
        INSERT OR IGNORE INTO movie_provider_queries (tmdb_id, provider_name, last_queried_utc, query_count)
        SELECT
            tmdb_id,
            COALESCE(provider_name, 'TMDB') as provider_name,
            MAX(last_queried_utc) as last_queried_utc,
            1 as query_count
        FROM downloads
        WHERE last_queried_utc IS NOT NULL
        GROUP BY tmdb_id, COALESCE(provider_name, 'TMDB')
    """)


def _migration_008_deprecate_last_queried(conn: sqlite3.Connection) -> None:
    """Clear last_queried_utc from downloads (now in movie_provider_queries).

    We keep the column for backward compatibility but mark it deprecated by setting to NULL.
    SQLite doesn't support DROP COLUMN easily, so we leave it in place.
    """
    existing = _get_existing_columns(conn, "downloads")

    if "last_queried_utc" in existing:
        # Clear the data (now redundant with movie_provider_queries)
        conn.execute("UPDATE downloads SET last_queried_utc = NULL")
        log.info("Deprecated last_queried_utc in downloads (use movie_provider_queries)")


def _migration_009_convert_to_partial_hash(conn: sqlite3.Connection, radarr_api=None, ffmpeg_api=None) -> None:
    """Convert full MD5 hashes to partial hashes for deployed trailers.

    This migration requires filesystem access to scan deployed trailer files.
    It recalculates hashes in-place using the partial hash algorithm (~25x faster).
    """
    import hashlib
    import time
    from pathlib import Path

    VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".webm"}

    def calc_full_hash(file: Path) -> str | None:
        """Calculate full MD5 hash (slow, for finding DB records)."""
        if not file or not file.exists():
            return None
        with open(file, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()

    def calc_partial_hash(file: Path) -> str | None:
        """Calculate partial MD5 hash (fast, new algorithm)."""
        if not file or not file.exists():
            return None

        file_size = file.stat().st_size
        if file_size < 192 * 1024:
            with open(file, "rb") as f:
                return hashlib.md5(f.read()).hexdigest()

        chunk_size = 64 * 1024
        with open(file, "rb") as f:
            first = f.read(chunk_size)
            f.seek(file_size // 2 - chunk_size // 2)
            middle = f.read(chunk_size)
            f.seek(-chunk_size, 2)
            last = f.read(chunk_size)
        return hashlib.md5(first + middle + last).hexdigest()

    if not radarr_api:
        log.warning("Skipping hash migration - no Radarr API provided")
        return

    start_time = time.time()
    log.info("=" * 60)
    log.info("Migration 9: Converting to partial hash algorithm")
    log.info("=" * 60)
    log.info("Scanning deployed trailers and updating hashes...")
    log.info("This may take 30-45 minutes for large libraries.")
    log.info("")

    try:
        movies = radarr_api.get_downloaded_movies()
    except Exception as e:
        log.error("Failed to get movie list: %s", e)
        return

    log.info("Found %d movies in Radarr", len(movies))

    files_processed = 0
    files_updated = 0
    files_not_in_db = 0
    errors = 0

    for i, movie in enumerate(movies, 1):
        if i % 50 == 0:
            elapsed = time.time() - start_time
            rate = i / elapsed if elapsed > 0 else 0
            remaining = (len(movies) - i) / rate if rate > 0 else 0
            log.info("Progress: %d/%d (%.1f%%) - %.1f movies/sec - ETA: %.1f min",
                    i, len(movies), (i / len(movies)) * 100, rate, remaining / 60)

        if not movie.file_path or not movie.file_path.exists():
            continue

        trailer_file = None
        for item in movie.directory.iterdir():
            if item.is_dir() or item == movie.file_path:
                continue
            if item.suffix in VIDEO_EXTENSIONS and "-trailer" in item.name.lower():
                trailer_file = item
                break

        if not trailer_file:
            continue

        try:
            files_processed += 1
            full_hash = calc_full_hash(trailer_file)
            if not full_hash:
                continue

            partial_hash = calc_partial_hash(trailer_file)
            if not partial_hash:
                continue

            row = conn.execute("SELECT id FROM downloads WHERE hash = ?", (full_hash,)).fetchone()
            if not row:
                files_not_in_db += 1
                continue

            conn.execute("UPDATE downloads SET hash = ? WHERE hash = ?", (partial_hash, full_hash))
            files_updated += 1

            if files_updated % 10 == 0:
                conn.commit()

        except Exception as e:
            log.error("Error processing %s: %s", trailer_file, e)
            errors += 1

    conn.commit()
    duration = time.time() - start_time

    log.info("")
    log.info("=" * 60)
    log.info("Migration 9 Complete!")
    log.info("Files Scanned: %d | Updated: %d | Not in DB: %d | Errors: %d",
            files_processed, files_updated, files_not_in_db, errors)
    log.info("Duration: %.1f minutes", duration / 60)
    log.info("=" * 60)


# Register all migrations here, in order
MIGRATIONS: list[Migration] = [
    (1, "Add retry tracking columns (retry_count, last_attempted, created_at)", _migration_001_add_retry_columns),
    (2, "Add imdb_id column to downloads", _migration_002_add_imdb_id),
    (3, "Create provider_state table for rate limit tracking", _migration_003_create_provider_state),
    (4, "Add last_queried_utc for provider query TTL", _migration_004_add_last_queried),
    (5, "Create movie_provider_failures table", _migration_005_create_movie_provider_failures),
    (6, "Add provider_name to downloads for per-provider tracking", _migration_006_add_provider_to_downloads),
    (7, "Create movie_provider_queries table and migrate data", _migration_007_create_movie_provider_queries),
    (8, "Deprecate last_queried_utc in downloads", _migration_008_deprecate_last_queried),
    (9, "Convert to partial hash algorithm for faster file checks", _migration_009_convert_to_partial_hash),
]


def run_migrations(conn: sqlite3.Connection, radarr_api=None, ffmpeg_api=None) -> None:
    """Run all pending migrations.

    Args:
        conn: Database connection
        radarr_api: Optional RadarrApi instance (required for filesystem migrations)
        ffmpeg_api: Optional FfmpegAPI instance (reserved for future use)
    """
    conn.execute(VERSION_TABLE_DDL)
    conn.commit()

    current = _get_current_version(conn)
    pending = [m for m in MIGRATIONS if m[0] > current]

    if not pending:
        log.debug("Database schema is up to date (version %d)", current)
        return

    # Use print() to ensure visibility regardless of logging config
    print(f"\nFound {len(pending)} pending migration(s)")
    log.info("Found %d pending migration(s)", len(pending))

    for version, description, migrate_fn in pending:
        print(f"Applying migration {version}: {description}")
        log.info("Applying migration %d: %s", version, description)
        try:
            # Check if migration needs extra dependencies
            import inspect
            sig = inspect.signature(migrate_fn)
            if 'radarr_api' in sig.parameters or 'ffmpeg_api' in sig.parameters:
                migrate_fn(conn, radarr_api=radarr_api, ffmpeg_api=ffmpeg_api)
            else:
                migrate_fn(conn)

            conn.execute("INSERT OR IGNORE INTO schema_version (version) VALUES (?)", (version,))
            conn.commit()
            print(f"Migration {version} applied successfully\n")
            log.info("Migration %d applied successfully", version)
        except Exception:
            conn.rollback()
            print(f"Migration {version} FAILED - rolling back")
            log.exception("Migration %d failed, rolling back", version)
            raise
