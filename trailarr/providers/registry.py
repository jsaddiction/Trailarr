"""Provider registry that combines results from all trailer sources."""

import logging

from trailarr.providers.base import TrailerProvider
from trailarr.models.download import TMDBVideo


class ProviderRegistry:
    """Queries all registered providers and combines deduplicated results."""

    def __init__(self) -> None:
        self.log = logging.getLogger("TrailArr.Providers")
        self._providers: list[TrailerProvider] = []

    def register(self, provider: TrailerProvider) -> None:
        """Add a provider to the registry."""
        self._providers.append(provider)
        self.log.info("Registered provider: %s", provider.name)

    def get_all_trailers(self, tmdb_id: int, imdb_id: str | None = None) -> list[TMDBVideo]:
        """Query ALL providers, combine and deduplicate results by URL."""
        all_trailers: list[TMDBVideo] = []
        seen_urls: set[str] = set()

        for provider in self._providers:
            try:
                trailers = provider.get_trailers(tmdb_id, imdb_id=imdb_id)
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
                self.log.exception("Provider '%s' failed for tmdb_id=%d", provider.name, tmdb_id)

        return all_trailers

    def close(self) -> None:
        """Close all providers."""
        for provider in self._providers:
            try:
                provider.close()
            except Exception:
                self.log.exception("Error closing provider '%s'", provider.name)
