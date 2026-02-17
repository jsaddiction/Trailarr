"""Provider state management for tracking rate limits and run statistics."""

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime


@dataclass
class ProviderRunState:
    """In-memory state for current run only.

    Tracks transient, provider-scoped state that doesn't survive process exit.
    For persistent failures, use ProviderStateManager.
    """

    provider_name: str
    auth_failed: bool = False  # Set on 401/403 - skip provider for THIS RUN only
    request_count: int = 0
    transient_error_count: int = 0  # 5xx errors, timeouts (retry on next run)
    errors: list[str] = field(default_factory=list)  # Error messages for run summary
    warnings: list[str] = field(default_factory=list)  # Warning messages for run summary


class ProviderStateManager:
    """Manages provider state persistence in DB."""

    DEFAULT_RATE_LIMIT_HOURS = 1

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.log = logging.getLogger("TrailArr.ProviderState")

    def is_rate_limited(self, provider_name: str) -> tuple[bool, datetime | None]:
        """Check if provider is currently rate limited.

        Returns:
            (is_limited, expires_at): Tuple of boolean and expiration datetime (or None)
        """
        sql = "SELECT rate_limited_until_utc FROM provider_state WHERE provider_name = :name"
        with self.conn:
            row = self.conn.execute(sql, {"name": provider_name}).fetchone()

        if not row or not row[0]:
            return False, None

        try:
            expires_at = datetime.fromisoformat(row[0])
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)

            now = datetime.now(timezone.utc)
            is_limited = now < expires_at

            return is_limited, expires_at
        except (ValueError, TypeError):
            self.log.warning("Invalid rate limit timestamp for %s: %s", provider_name, row[0])
            return False, None

    def set_rate_limit(self, provider_name: str, retry_after: str | int | None) -> None:
        """Store rate limit state with expiration time.

        Args:
            provider_name: Name of the provider
            retry_after: Can be:
                - Integer (seconds to wait)
                - HTTP-date string (RFC 2822)
                - None (use default 1 hour)
        """
        now = datetime.now(timezone.utc)

        if retry_after is None:
            # Default to 1 hour
            expires_at = now + timedelta(hours=self.DEFAULT_RATE_LIMIT_HOURS)
        elif isinstance(retry_after, int):
            # Seconds from now
            expires_at = now + timedelta(seconds=retry_after)
        elif isinstance(retry_after, str):
            try:
                # Try parsing as integer first
                seconds = int(retry_after)
                expires_at = now + timedelta(seconds=seconds)
            except ValueError:
                # Try parsing as HTTP-date (RFC 2822)
                try:
                    expires_at = parsedate_to_datetime(retry_after)
                    if expires_at.tzinfo is None:
                        expires_at = expires_at.replace(tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    self.log.warning(
                        "Could not parse Retry-After '%s', using default %dh",
                        retry_after,
                        self.DEFAULT_RATE_LIMIT_HOURS,
                    )
                    expires_at = now + timedelta(hours=self.DEFAULT_RATE_LIMIT_HOURS)
        else:
            expires_at = now + timedelta(hours=self.DEFAULT_RATE_LIMIT_HOURS)

        sql = """
            INSERT OR REPLACE INTO provider_state (provider_name, rate_limited_until_utc, updated_at)
            VALUES (:name, :expires, datetime('now'))
        """
        data = {"name": provider_name, "expires": expires_at.isoformat()}

        try:
            with self.conn:
                self.conn.execute(sql, data)
            self.log.info("Set rate limit for %s until %s", provider_name, expires_at)
        except sqlite3.OperationalError as e:
            self.log.error("Failed to set rate limit for %s: %s", provider_name, e)

    def clear_rate_limit(self, provider_name: str) -> None:
        """Clear rate limit (after successful request)."""
        sql = """
            UPDATE provider_state
            SET rate_limited_until_utc = NULL, updated_at = datetime('now')
            WHERE provider_name = :name
        """
        try:
            with self.conn:
                self.conn.execute(sql, {"name": provider_name})
            self.log.debug("Cleared rate limit for %s", provider_name)
        except sqlite3.OperationalError as e:
            self.log.warning("Failed to clear rate limit for %s: %s", provider_name, e)

    def set_movie_failure(
        self,
        tmdb_id: int,
        provider_name: str,
        failure_type: str,
        retry_days: int | None = None,
    ) -> None:
        """Record a permanent/semi-permanent failure for a movie/provider pair.

        Args:
            tmdb_id: TMDB movie ID
            provider_name: Provider name (TMDB, IMDb, AppleTV)
            failure_type: Type of failure (404_not_found, no_match, etc.)
            retry_days: Days until retry (None = permanent, default 60 for 404s)
        """
        now = datetime.now(timezone.utc)

        if retry_days is not None:
            retry_after = now + timedelta(days=retry_days)
            retry_after_str = retry_after.isoformat()
        else:
            retry_after_str = None

        sql = """
            INSERT OR REPLACE INTO movie_provider_failures
            (tmdb_id, provider_name, failure_type, failed_at, retry_after_utc)
            VALUES (:tmdb_id, :provider, :failure_type, :failed_at, :retry_after)
        """

        data = {
            "tmdb_id": tmdb_id,
            "provider": provider_name,
            "failure_type": failure_type,
            "failed_at": now.isoformat(),
            "retry_after": retry_after_str,
        }

        try:
            with self.conn:
                self.conn.execute(sql, data)
            if retry_days:
                self.log.info(
                    "Recorded %s failure for tmdb_id=%d on %s (retry in %d days)",
                    failure_type, tmdb_id, provider_name, retry_days
                )
            else:
                self.log.info(
                    "Recorded permanent %s failure for tmdb_id=%d on %s",
                    failure_type, tmdb_id, provider_name
                )
        except sqlite3.OperationalError as e:
            self.log.error("Failed to record movie failure: %s", e)

    def should_skip_provider(self, tmdb_id: int, provider_name: str) -> tuple[bool, str | None]:
        """Check if provider should be skipped for this movie.

        Returns:
            (should_skip, reason): Tuple of boolean and skip reason (or None)
        """
        sql = """
            SELECT failure_type, retry_after_utc
            FROM movie_provider_failures
            WHERE tmdb_id = :tmdb_id AND provider_name = :provider
        """

        with self.conn:
            row = self.conn.execute(sql, {"tmdb_id": tmdb_id, "provider": provider_name}).fetchone()

        if not row:
            return False, None

        failure_type, retry_after = row

        # Check if retry period has expired
        if retry_after:
            try:
                retry_time = datetime.fromisoformat(retry_after)
                if retry_time.tzinfo is None:
                    retry_time = retry_time.replace(tzinfo=timezone.utc)

                now = datetime.now(timezone.utc)
                if now >= retry_time:
                    # Retry period expired, clear the failure
                    self.clear_movie_failure(tmdb_id, provider_name)
                    return False, None

                return True, f"{failure_type} (retry after {retry_time.strftime('%Y-%m-%d')})"
            except (ValueError, TypeError):
                self.log.warning("Invalid retry_after for tmdb_id=%d provider=%s", tmdb_id, provider_name)
                return False, None

        # Permanent failure (no retry_after)
        return True, f"{failure_type} (permanent)"

    def clear_movie_failure(self, tmdb_id: int, provider_name: str) -> None:
        """Clear a recorded failure (e.g., after retry period expires)."""
        sql = """
            DELETE FROM movie_provider_failures
            WHERE tmdb_id = :tmdb_id AND provider_name = :provider
        """

        try:
            with self.conn:
                self.conn.execute(sql, {"tmdb_id": tmdb_id, "provider": provider_name})
            self.log.debug("Cleared failure record for tmdb_id=%d provider=%s", tmdb_id, provider_name)
        except sqlite3.OperationalError as e:
            self.log.warning("Failed to clear movie failure: %s", e)
