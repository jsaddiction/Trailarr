#!/usr/bin/env python
"""Movie model"""

from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class Movie:
    """Movie model"""

    tmdb_id: int = field(default=None)
    title: str = field(default=None)
    year: int = field(default=None)
    directory: Path = field(default=None)
    file_path: Path = field(default=None)

    def __str__(self) -> str:
        return f"{self.title} ({self.year})"
