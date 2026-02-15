"""Provider state management for tracking rate limits and run statistics."""

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime


@dataclass
class ProviderRunState:
    """In-memory state for current run only."""

    provider_name: str
    auth_failed: bool = False  # Set on 401/403
    request_count: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


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
