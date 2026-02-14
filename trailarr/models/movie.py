"""Movie model."""

from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class Movie:
    """Movie model"""

    tmdb_id: int | None = field(default=None)
    title: str | None = field(default=None)
    year: int | None = field(default=None)
    directory: Path | None = field(default=None)
    file_path: Path | None = field(default=None)
    imdb_id: str | None = field(default=None)

    def __str__(self) -> str:
        return f"{self.title} ({self.year})"
