"""Data models package."""

from trailarr.models.movie import Movie
from trailarr.models.download import FileDetails, TMDBVideo, Download, CODEC_WEIGHTS
from trailarr.models.kodi import RPCVersion, Platform, KodiResponse, Player, MOVIE_PROPERTIES, MovieDetails

__all__ = [
    "Movie",
    "FileDetails",
    "TMDBVideo",
    "Download",
    "CODEC_WEIGHTS",
    "RPCVersion",
    "Platform",
    "KodiResponse",
    "Player",
    "MOVIE_PROPERTIES",
    "MovieDetails",
]
