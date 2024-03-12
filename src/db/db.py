#!/usr/bin/env python
"""Database module"""

import logging
import sqlite3
from dataclasses import asdict
from pathlib import Path
from src import Download, FileDetails, TMDBVideo

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
    trailer_path TEXT NOT NULL UNIQUE,
"""
INDICES = [
    "CREATE INDEX IF NOT EXISTS url_idx ON downloads (url);",
    "CREATE INDEX IF NOT EXISTS tmdb_idx ON downloads (tmdb_id);",
    "CREATE INDEX IF NOT EXISTS hash_idx ON downloads (hash);",
]


class DB:
    """Database interface"""

    def __init__(self, db_file: Path) -> None:
        self.log = logging.getLogger("TrailArr.DB")
        self.movies = []
        self.conn = sqlite3.connect(db_file)

        # Ensure tables exist with indices
        with self.conn:
            self.conn.execute(DL_HISTORY_TABLE)
            self.conn.execute(KODI_TRAILER_CACHE_TABLE)
            for index in INDICES:
                self.conn.execute(index)

    def __del__(self) -> None:
        self.close()

    def close(self) -> None:
        """Close the database connection"""
        if self.conn:
            self.conn.close()
            self.conn = None

    def _parse_row(self, row: tuple) -> Download:
        """Parse row into Download object"""
        return Download(
            tmdb=TMDBVideo(
                tmdb_id=row[1],
                url=row[2],
                iso_639_1=row[3],
                iso_3166_1=row[4],
                name=row[5],
                type=row[6],
                official=bool(row[7]),
            ),
            file=FileDetails(
                broken=bool(row[8]),
                hash=row[9],
                height=row[10],
                width=row[11],
                duration=row[12],
                frames=row[13],
                bitrate=row[14],
                codec_name=row[15],
                forced=bool(row[16]),
            ),
        )

    def test(self) -> bool:
        """Test connection"""
        try:
            with self.conn:
                self.conn.execute("SELECT 1")
        except sqlite3.OperationalError:
            return False
        return True

    def insert_download(self, download: Download) -> None:
        """Insert download into database"""
        sql = """INSERT OR REPLACE INTO downloads
        (tmdb_id, url, iso_639_1, iso_3166_1, name, type, official,
        broken, hash, height, width, duration, frames, bitrate, codec_name, forced)
        VALUES
        (:tmdb_id, :url, :iso_639_1, :iso_3166_1, :name, :type, :official,
        :broken, :hash, :height, :width, :duration, :frames, :bitrate, :codec_name, :forced)
        """
        data = asdict(download.tmdb) | asdict(download.file)
        try:
            with self.conn:
                self.conn.execute(sql, data)
        except sqlite3.OperationalError as e:
            self.log.error("Failed to insert %s. Error: %s", download, e)

    def insert_kodi_trailer_cache(self, movie_path: str, trailer_path: str) -> None:
        """Insert kodi trailer cache into database"""
        sql = """INSERT OR REPLACE INTO kodi_trailer_cache
        (movie_path, trailer_path)
        VALUES
        (:movie_path, :trailer_path)"""
        try:
            with self.conn:
                self.conn.execute(sql, {"movie_path": movie_path, "trailer_path": trailer_path})
        except sqlite3.OperationalError as e:
            self.log.error("Failed to insert kodi trailer cache. Error: %s", e)

    def select_kodi_trailer_cache(self) -> list[tuple[str, str]]:
        """Select kodi trailer cache from database"""
        sql = "SELECT * FROM kodi_trailer_cache"
        try:
            with self.conn:
                return [row for row in self.conn.execute(sql)]
        except sqlite3.OperationalError as e:
            self.log.error("Failed to select kodi trailer cache. Error: %s", e)
            return []

    def delete_kodi_trailer_cache(self, movie_path: str) -> None:
        """Delete kodi trailer cache from database"""
        sql = "DELETE FROM kodi_trailer_cache WHERE movie_path = :movie_path"
        try:
            with self.conn:
                self.conn.execute(sql, {"movie_path": movie_path})
        except sqlite3.OperationalError as e:
            self.log.error("Failed to delete kodi trailer cache. Error: %s", e)

    def clear_forced(self, tmdb_id: int) -> None:
        """Clear forced flag for tmdb_id"""
        sql = "UPDATE downloads SET forced = 0 WHERE tmdb_id = :tmdb_id"
        with self.conn:
            self.conn.execute(sql, {"tmdb_id": tmdb_id})

    def set_forced(self, tmdb_id: int, url: str) -> None:
        """Set forced flag for record containing tmdb_id and url"""
        sql = "UPDATE downloads SET forced = 1 WHERE tmdb_id = :tmdb_id AND url = :url"
        with self.conn:
            self.conn.execute(sql, {"tmdb_id": tmdb_id, "url": url})

    def select_by_url(self, url: str) -> Download:
        """Select download by url"""
        sql = "SELECT * FROM downloads WHERE url = :url"
        with self.conn:
            if row := self.conn.execute(sql, {"url": url}).fetchone():
                return self._parse_row(row)
            return None

    def select_by_tmdb_id(self, tmdb_id: int) -> list[Download]:
        """Select download by tmdb_id"""
        sql = "SELECT * FROM downloads WHERE tmdb_id = :tmdb_id"
        with self.conn:
            return [self._parse_row(row) for row in self.conn.execute(sql, {"tmdb_id": tmdb_id})]

    def select_by_hash(self, hash_str: str) -> Download:
        """Select download by hash"""
        sql = "SELECT * FROM downloads WHERE hash = :hash"
        with self.conn:
            if row := self.conn.execute(sql, {"hash": hash_str}).fetchone():
                return self._parse_row(row)
            return None

    def delete_by_tmdb_id(self, tmdb_id: int) -> None:
        """Delete download by tmdb_id"""
        sql = "DELETE FROM downloads WHERE tmdb_id = :tmdb_id"
        with self.conn:
            self.conn.execute(sql, {"tmdb_id": tmdb_id})
