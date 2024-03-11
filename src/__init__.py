#!/usr/bin/env python
"""Trailarr package."""

import logging
import logging.config
from pathlib import Path
from .models.movies import Movie
from .models.tmdb import FileDetails, TMDBVideo, Download
from .models.kodi import RPCVersion, Platform, KodiResponse, Player, MOVIE_PROPERTIES, MovieDetails
from .db.db import DB
from .yt_dlp.ytdlp import YouTubeDLP, YTDLPError
from .ffmpeg.exceptions import FfmpegError
from .ffmpeg.ffmpeg import FfmpegAPI
from .tmdb.tmdb import TmdbApi
from .env.env import RadarrEnvironment, Events
from .radarr.radarr import RadarrApi
from .kodi.exceptions import KodiAPIError
from .kodi.kodi import KodiApi

__all__ = [
    "TMDBVideo",
    "Download",
    "FileDetails",
    "Movie",
    "DB",
    "YouTubeDLP",
    "YTDLPError",
    "TmdbApi",
    "RadarrEnvironment",
    "Events",
    "RadarrApi",
    "FfmpegAPI",
    "FfmpegError",
    "KodiApi",
    "KodiAPIError",
    "RPCVersion",
    "Platform",
    "KodiResponse",
    "Player",
    "MOVIE_PROPERTIES",
    "MovieDetails",
]

__app_name__ = "Trailarr"
__version__ = "0.1.0"
__author__ = "Justin Lawrence"
__email__ = "04reduramax@gmail.com"
__license__ = "MIT"
__maintainer__ = "Justin Lawrence"
__status__ = "Development"
__url__ = "https://github.com/jsaddiction/Trailarr"
__description__ = "Automatically download and manage movie trailers for Radarr."

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_FILE = ROOT_DIR / "trailarr.db"
LOG_DIR = Path("/config/logs") if Path("/config/logs").exists() else ROOT_DIR / "logs"
TEMP_DIR = ROOT_DIR / "temp"
VIDEO_EXTENSIONS = [
    ".mkv",
    ".iso",
    ".wmv",
    ".avi",
    ".mp4",
    ".m4v",
    ".img",
    ".divx",
    ".mov",
    ".flv",
    ".m2ts",
    ".ts",
    ".webm",
]

# Create log directory if it doesn't exist
if not LOG_DIR.exists():
    LOG_DIR.mkdir()
if not TEMP_DIR.exists():
    TEMP_DIR.mkdir()

# Configure logging
_log_config = {
    "version": 1,
    "disable_existing_loggers": True,
    "formatters": {
        "file": {
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        },
        "console": {
            "format": "%(name)s - %(levelname)s - %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "level": "WARNING",
            "formatter": "console",
            "stream": "ext://sys.stderr",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "INFO",
            "formatter": "file",
            "filename": LOG_DIR / "Trailarr.txt",
            "maxBytes": 100_000,
            "backupCount": 5,
        },
    },
    "loggers": {
        "root": {
            "handlers": ["console", "file"],
            "level": "DEBUG",
        }
    },
}

logging.config.dictConfig(_log_config)
