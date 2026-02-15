"""Provider registry that combines results from all trailer sources."""

import logging

from trailarr.providers.base import TrailerProvider
from trailarr.models.download import TMDBVideo


class ProviderRegistry:
    """Queries all registered providers and combines deduplicated results."""

    def __init__(self, state_manager=None, run_states: dict = None) -> None:
        self.log = logging.getLogger("TrailArr.Providers")
        self._providers: list[TrailerProvider] = []
        self.state_manager = state_manager
        self.run_states = run_states or {}

    def register(self, provider: TrailerProvider) -> None:
        """Add a provider to the registry."""
        self._providers.append(provider)
        self.log.info("Registered provider: %s", provider.name)

    def get_all_trailers(self, tmdb_id: int, imdb_id: str | None = None) -> list[TMDBVideo]:
        """Query ALL providers, combine and deduplicate results by URL."""
        all_trailers: list[TMDBVideo] = []
        seen_urls: set[str] = set()

        for provider in self._providers:
            # Check if provider should be skipped
            run_state = self.run_states.get(provider.name)

            if run_state and run_state.auth_failed:
                self.log.info("Skipping %s - authentication failed earlier", provider.name)
                continue

            if self.state_manager:
                is_limited, expires_at = self.state_manager.is_rate_limited(provider.name)
                if is_limited:
                    self.log.info("Skipping %s - rate limited until %s", provider.name, expires_at)
                    continue

            try:
                trailers = provider.get_trailers(tmdb_id, imdb_id=imdb_id)

                # Clear rate limit on successful query with results
                if trailers and self.state_manager:
                    self.state_manager.clear_rate_limit(provider.name)

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
                else:
                    self.log.debug(
                        "Provider '%s' returned no new trailers for tmdb_id=%d",
                        provider.name, tmdb_id,
                    )
            except Exception:
                self.log.exception("Unexpected error from provider '%s' for tmdb_id=%d", provider.name, tmdb_id)

        return all_trailers

    def close(self) -> None:
        """Close all providers."""
        for provider in self._providers:
            try:
                provider.close()
            except Exception:
                self.log.exception("Error closing provider '%s'", provider.name)
