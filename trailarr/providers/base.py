"""Trailer provider protocol."""

from typing import Protocol, runtime_checkable

from trailarr.models.download import TMDBVideo


@runtime_checkable
class TrailerProvider(Protocol):
    """Protocol that all trailer sources must implement."""

    @property
    def name(self) -> str:
        """Human-readable provider name for logging."""
        ...

    def get_trailers(self, tmdb_id: int, imdb_id: str | None = None) -> list[TMDBVideo]:
        """Return trailer metadata for a movie.

        Args:
            tmdb_id: The TMDB ID of the movie.
            imdb_id: Optional IMDb ID for providers that need it.

        Returns:
            List of TMDBVideo objects with populated url fields.
            Empty list if no trailers found.
        """
        ...

    def test(self) -> bool:
        """Verify the provider is operational."""
        ...

    def close(self) -> None:
        """Release resources (sessions, connections)."""
        ...
