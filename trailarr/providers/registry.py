"""Provider registry that combines results from all trailer sources."""

import logging

from trailarr.providers.base import TrailerProvider
from trailarr.models.download import TMDBVideo


class ProviderRegistry:
    """Queries all registered providers and combines deduplicated results."""

    def __init__(self, state_manager=None, run_states: dict | None = None) -> None:
        self.log = logging.getLogger("TrailArr.Providers")
        self._providers: list[TrailerProvider] = []
        self.state_manager = state_manager
        self.run_states = run_states or {}

    def register(self, provider: TrailerProvider) -> None:
        """Add a provider to the registry."""
        self._providers.append(provider)
        self.log.info("Registered provider: %s", provider.name)

    def get_all_trailers(self, tmdb_id: int, imdb_id: str | None = None, db=None) -> tuple[list[TMDBVideo], set[str]]:
        """Query providers that should be queried for this movie, combine and deduplicate results.

        Args:
            tmdb_id: TMDB movie ID
            imdb_id: IMDb ID (optional)
            db: Database instance for checking query TTL

        Returns:
            (trailers, providers_succeeded): List of trailers and set of provider names that succeeded
        """
        all_trailers: list[TMDBVideo] = []
        seen_urls: set[str] = set()
        providers_succeeded: set[str] = set()

        for provider in self._providers:
            # Check if provider should be skipped (run-level state)
            run_state = self.run_states.get(provider.name)

            if run_state and run_state.auth_failed:
                self.log.info("Skipping %s - authentication failed earlier", provider.name)
                continue

            # Check rate limits (DB-persisted)
            if self.state_manager:
                is_limited, expires_at = self.state_manager.is_rate_limited(provider.name)
                if is_limited:
                    self.log.info("Skipping %s - rate limited until %s", provider.name, expires_at)
                    continue

                # Check movie-provider failures (DB-persisted)
                should_skip, reason = self.state_manager.should_skip_provider(tmdb_id, provider.name)
                if should_skip:
                    self.log.debug("Skipping %s for tmdb_id=%d - %s", provider.name, tmdb_id, reason)
                    continue

            # Check per-provider query TTL (DB-persisted)
            if db and not db.should_query_provider(tmdb_id, provider.name):
                self.log.debug("Skipping %s for tmdb_id=%d - within cache TTL", provider.name, tmdb_id)
                continue

            try:
                # Track transient errors BEFORE query
                transient_errors_before = run_state.transient_error_count if run_state else 0

                # Query provider
                trailers = provider.get_trailers(tmdb_id, imdb_id=imdb_id)

                # Check if transient errors occurred
                transient_errors_after = run_state.transient_error_count if run_state else 0
                had_transient_error = transient_errors_after > transient_errors_before

                if had_transient_error:
                    # Provider had transient error - don't mark as success
                    self.log.debug("Provider '%s' had transient error for tmdb_id=%d", provider.name, tmdb_id)
                else:
                    # Provider succeeded (even if no trailers found)
                    providers_succeeded.add(provider.name)

                    # Clear rate limit on successful query
                    if self.state_manager:
                        self.state_manager.clear_rate_limit(provider.name)

                # Add trailers to result
                added = 0
                for trailer in trailers:
                    if trailer.url and trailer.url not in seen_urls:
                        seen_urls.add(trailer.url)
                        all_trailers.append(trailer)
                        added += 1

                if added:
                    self.log.info(
                        "Provider '%s' returned %d trailers for tmdb_id=%d",
                        provider.name, added, tmdb_id,
                    )
                elif not had_transient_error:
                    # No trailers but query succeeded - this is fine (treat as success)
                    self.log.debug(
                        "Provider '%s' returned no trailers for tmdb_id=%d",
                        provider.name, tmdb_id,
                    )

            except Exception:
                self.log.exception("Unexpected error from provider '%s' for tmdb_id=%d", provider.name, tmdb_id)
                # Don't add to providers_succeeded

        return all_trailers, providers_succeeded

    def close(self) -> None:
        """Close all providers."""
        for provider in self._providers:
            try:
                provider.close()
            except Exception:
                self.log.exception("Error closing provider '%s'", provider.name)
