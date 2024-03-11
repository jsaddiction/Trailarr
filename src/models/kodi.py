#!/usr/bin/env python
"""Kodi JSON RPC Models"""

from pathlib import PurePath
from enum import Enum
from typing import Optional
from dataclasses import dataclass, field

MOVIE_PROPERTIES = [
    "file",
    "title",
    "year",
    "uniqueid",
    "trailer",
]


class Platform(Enum):
    """Kodi Platform enumeration"""

    ANDROID = "System.Platform.Android"
    DARWIN = "System.Platform.Darwin"
    IOS = "System.Platform.IOS"
    LINUX = "System.Platform.Linux"
    OSX = "System.Platform.OSX"
    TVOS = "System.Platform.TVOS"
    UWP = "System.Platform.UWP"
    WINDOWS = "System.Platform.Windows"
    UNKNOWN = "Unknown"


@dataclass(frozen=True, order=True)
class RPCVersion:
    """JSON-RPC Version info"""

    major: int
    minor: int
    patch: int = field(compare=False)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass
class KodiResponse:
    """Kodi JSON-RPC Response Model"""

    req_id: int
    jsonrpc: str
    result: Optional[dict] | None = field(default=None)


@dataclass
class Player:
    """A Content player"""

    player_id: int
    player_type: str
    type: str


@dataclass
class MovieDetails:
    """Details of a Movie"""

    movie_id: int = field(compare=False, hash=False)
    movie_path: PurePath = field(compare=False, hash=False)
    title: str = field(compare=False, hash=False)
    year: int = field(compare=False, hash=False)
    tmdb: str = field(default=None, compare=True, hash=False)
    trailer_path: PurePath = field(default=None, compare=True, hash=False)

    def __str__(self) -> str:
        return f"{self.title} ({self.year})"
