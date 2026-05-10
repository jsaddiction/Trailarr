"""Database module."""

import logging
import random
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

from trailarr.models.download import Download, FileDetails, TMDBVideo
from trailarr.db.migrations import run_migrations

DL_HISTORY_TABLE = """
CREATE TABLE IF NOT EXISTS downloads (
    id INTEGER PRIMARY KEY,
    tmdb_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    iso_639_1 TEXT NOT NULL,
    iso_3166_1 TEXT NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    official INTEGER,
    broken INTEGER,
    hash TEXT,
    height INTEGER,
    width INTEGER,
    duration INTEGER,
    frames INTEGER,
    bitrate INTEGER,
    codec_name TEXT,
    forced INTEGER,
    UNIQUE(tmdb_id, url) ON CONFLICT REPLACE
);"""
KODI_TRAILER_CACHE_TABLE = """
CREATE TABLE IF NOT EXISTS kodi_trailer_cache (
    id INTEGER PRIMARY KEY,
    movie_path TEXT NOT NULL UNIQUE,
    trailer_path TEXT NOT NULL UNIQUE
);"""
INDICES = [
    "CREATE INDEX IF NOT EXISTS url_idx ON downloads (url);",
    "CREATE INDEX IF NOT EXISTS tmdb_idx ON downloads (tmdb_id);",
    "CREATE INDEX IF NOT EXISTS hash_idx ON downloads (hash);",
]

# Retry parameters
BASE_TTL_DAYS = 10
JITTER_DAYS = 3

# Provider query cache parameters
QUERY_CACHE_DAYS = 7  # Don't re-query providers for same movie within ~7 days
QUERY_JITTER_DAYS = 2  # ±2 days random jitter


class DB:
    """Database interface."""

    def __init__(self, db_file: Path) -> None:
        self.log = logging.getLogger("TrailArr.DB")
        self.conn = sqlite3.connect(db_file)
        self.conn.row_factory = sqlite3.Row

        # Ensure tables exist with indices
        with self.conn:
            self.conn.execute(DL_HISTORY_TABLE)
            self.conn.execute(KODI_TRAILER_CACHE_TABLE)
            for index in INDICES:
                self.conn.execute(index)

        # Migrations will be run after app is fully initialized

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def close(self) -> None:
        """Close the database connection."""
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def _parse_row(self, row: sqlite3.Row) -> Download:
        """Parse row into Download object."""
        return Download(
            tmdb=TMDBVideo(
                tmdb_id=row["tmdb_id"],
                url=row["url"],
                iso_639_1=row["iso_639_1"],
                iso_3166_1=row["iso_3166_1"],
                name=row["name"],
                type=row["type"],
                official=bool(row["official"]),
            ),
            file=FileDetails(
                broken=bool(row["broken"]),
                hash=row["hash"],
                height=row["height"],
                width=row["width"],
                duration=row["duration"],
                frames=row["frames"],
                bitrate=row["bitrate"],
                codec_name=row["codec_name"],
            ),
            retry_count=row["retry_count"] if "retry_count" in row.keys() else 0,
            last_attempted=row["last_attempted"] if "last_attempted" in row.keys() else None,
            created_at=row["created_at"] if "created_at" in row.keys() else None,
        )

    def test(self) -> bool:
        """Test connection."""
        try:
            with self.conn:
                self.conn.execute("SELECT 1")
        except sqlite3.OperationalError:
            return False
        return True

    def insert_download(self, download: Download) -> None:
        """Insert download into database."""
        now = datetime.now(timezone.utc).isoformat()
        sql = """INSERT OR REPLACE INTO downloads
        (tmdb_id, url, iso_639_1, iso_3166_1, name, type, official,
        broken, hash, height, width, duration, frames, bitrate, codec_name, forced,
        retry_count, last_attempted, created_at)
        VALUES
        (:tmdb_id, :url, :iso_639_1, :iso_3166_1, :name, :type, :official,
        :broken, :hash, :height, :width, :duration, :frames, :bitrate, :codec_name, 0,
        :retry_count, :last_attempted, :created_at)
        """
        data = asdict(download.tmdb) | asdict(download.file)
        data["retry_count"] = download.retry_count
        data["last_attempted"] = download.last_attempted or now
        data["created_at"] = download.created_at or now
        try:
            with self.conn:
                self.conn.execute(sql, data)
        except sqlite3.OperationalError as e:
            self.log.warning("Failed to insert download %s: %s", download.tmdb.url, e)

    def mark_broken(self, tmdb_id: int, url: str) -> None:
        """Mark a download as broken and increment retry count."""
        now = datetime.now(timezone.utc).isoformat()
        sql = """
            UPDATE downloads
            SET broken = 1, last_attempted = :now, retry_count = retry_count + 1
            WHERE tmdb_id = :tmdb_id AND url = :url
        """
        try:
            with self.conn:
                self.conn.execute(sql, {"tmdb_id": tmdb_id, "url": url, "now": now})
        except sqlite3.OperationalError as e:
            self.log.warning("Failed to mark broken %s: %s", url, e)

    def is_retryable(self, download: Download) -> bool:
        """Check if a broken download is eligible for retry."""
        if not download.file.broken:
            return False
        if download.last_attempted is None:
            return True  # Legacy data with no timestamp, retry immediately

        last = datetime.fromisoformat(download.last_attempted)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        jitter = random.uniform(-JITTER_DAYS, JITTER_DAYS)
        ttl = timedelta(days=BASE_TTL_DAYS + jitter)
        return datetime.now(timezone.utc) >= last + ttl

    def should_query_provider(self, tmdb_id: int, provider_name: str) -> bool:
        """Check if we should query a specific provider for this movie (TTL-based cache).

        Returns True if:
        - Provider has never been queried for this movie
        - Last query was more than QUERY_CACHE_DAYS ± QUERY_JITTER_DAYS ago

        Args:
            tmdb_id: Movie ID
            provider_name: Provider to check (TMDB, AppleTV)

        Returns:
            True if provider should be queried, False if within cache TTL
        """
        sql = """SELECT last_queried_utc FROM movie_provider_queries
                 WHERE tmdb_id = :tmdb_id AND provider_name = :provider"""

        with self.conn:
            row = self.conn.execute(sql, {"tmdb_id": tmdb_id, "provider": provider_name}).fetchone()

        if not row or not row[0]:
            # Never queried this provider for this movie
            return True

        try:
            last_queried = datetime.fromisoformat(row[0])
            if last_queried.tzinfo is None:
                last_queried = last_queried.replace(tzinfo=timezone.utc)

            # Calculate TTL with jitter (deterministic per movie+provider)
            rng = random.Random(f"{tmdb_id}:{provider_name}")
            jitter = rng.uniform(-QUERY_JITTER_DAYS, QUERY_JITTER_DAYS)
            ttl = timedelta(days=QUERY_CACHE_DAYS + jitter)

            return datetime.now(timezone.utc) >= last_queried + ttl
        except (ValueError, TypeError):
            # Invalid timestamp, allow query
            return True

    def update_provider_query(self, tmdb_id: int, provider_name: str) -> None:
        """Record that a provider was queried for this movie.

        Updates movie_provider_queries table with timestamp and increments query_count.

        Args:
            tmdb_id: Movie ID
            provider_name: Provider that was queried (TMDB, AppleTV)
        """
        now = datetime.now(timezone.utc).isoformat()

        # UPSERT: insert if new, update if exists
        sql = """
            INSERT INTO movie_provider_queries (tmdb_id, provider_name, last_queried_utc, query_count)
            VALUES (:tmdb_id, :provider, :now, 1)
            ON CONFLICT(tmdb_id, provider_name) DO UPDATE SET
                last_queried_utc = :now,
                query_count = query_count + 1
        """

        try:
            with self.conn:
                self.conn.execute(sql, {"tmdb_id": tmdb_id, "provider": provider_name, "now": now})
        except sqlite3.OperationalError as e:
            self.log.warning("Failed to update provider query for tmdb_id=%d provider=%s: %s",
                           tmdb_id, provider_name, e)

    def update_provider_queries(self, tmdb_id: int, provider_names: set[str]) -> None:
        """Record that multiple providers were queried for this movie.

        Args:
            tmdb_id: Movie ID
            provider_names: Set of provider names that were queried successfully
        """
        if not provider_names:
            return

        for provider_name in provider_names:
            self.update_provider_query(tmdb_id, provider_name)

    def insert_kodi_trailer_cache(self, movie_path: str, trailer_path: str) -> None:
        """Insert kodi trailer cache into database."""
        sql = """INSERT OR REPLACE INTO kodi_trailer_cache
        (movie_path, trailer_path)
        VALUES
        (:movie_path, :trailer_path)"""
        try:
            with self.conn:
                self.conn.execute(sql, {"movie_path": movie_path, "trailer_path": trailer_path})
        except sqlite3.OperationalError as e:
            self.log.warning("Failed to insert kodi trailer cache: %s", e)

    def select_kodi_trailer_cache(self) -> list[tuple[int, str, str]]:
        """Select kodi trailer cache from database."""
        sql = "SELECT * FROM kodi_trailer_cache"
        try:
            with self.conn:
                return [row for row in self.conn.execute(sql)]
        except sqlite3.OperationalError as e:
            self.log.error("Failed to select kodi trailer cache. Error: %s", e)
            return []

    def delete_kodi_trailer_cache(self, movie_path: str) -> None:
        """Delete kodi trailer cache from database."""
        sql = "DELETE FROM kodi_trailer_cache WHERE movie_path = :movie_path"
        try:
            with self.conn:
                self.conn.execute(sql, {"movie_path": movie_path})
        except sqlite3.OperationalError as e:
            self.log.warning("Failed to delete kodi trailer cache: %s", e)

    def select_by_url(self, url: str) -> Download | None:
        """Select download by url."""
        sql = "SELECT * FROM downloads WHERE url = :url"
        with self.conn:
            if row := self.conn.execute(sql, {"url": url}).fetchone():
                return self._parse_row(row)
            return None

    def select_by_tmdb_id(self, tmdb_id: int) -> list[Download]:
        """Select download by tmdb_id."""
        sql = "SELECT * FROM downloads WHERE tmdb_id = :tmdb_id"
        with self.conn:
            return [self._parse_row(row) for row in self.conn.execute(sql, {"tmdb_id": tmdb_id})]

    def select_by_hash(self, hash_str: str) -> Download | None:
        """Select download by hash."""
        sql = "SELECT * FROM downloads WHERE hash = :hash"
        with self.conn:
            if row := self.conn.execute(sql, {"hash": hash_str}).fetchone():
                return self._parse_row(row)
            return None

    def delete_by_tmdb_id(self, tmdb_id: int) -> None:
        """Delete download by tmdb_id."""
        sql = "DELETE FROM downloads WHERE tmdb_id = :tmdb_id"
        with self.conn:
            self.conn.execute(sql, {"tmdb_id": tmdb_id})

    def get_tmdb_ids(self) -> list[int]:
        """Get all tmdb_ids."""
        sql = "SELECT DISTINCT tmdb_id FROM downloads"
        with self.conn:
            return [row[0] for row in self.conn.execute(sql)]
