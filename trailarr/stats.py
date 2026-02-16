"""Run statistics tracking for trailer processing."""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from trailarr.providers.state import ProviderRunState


@dataclass
class RunStats:
    """Statistics for current run."""

    movies_processed: int = 0
    trailers_added: int = 0
    trailers_upgraded: int = 0
    provider_states: dict[str, ProviderRunState] = field(default_factory=dict)
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def add_trailer(self) -> None:
        """Increment trailers added counter."""
        self.trailers_added += 1

    def upgrade_trailer(self) -> None:
        """Increment trailers upgraded counter."""
        self.trailers_upgraded += 1

    def total_transient_errors(self) -> int:
        """Get total count of transient errors across all providers."""
        return sum(state.transient_error_count for state in self.provider_states.values())
