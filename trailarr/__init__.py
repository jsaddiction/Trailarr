"""Trailarr — Automated movie trailer management for Radarr."""

from pathlib import Path

__app_name__ = "Trailarr"
__version__ = "0.2.0"
__author__ = "Justin Lawrence"
__email__ = "04reduramax@gmail.com"
__license__ = "MIT"
__maintainer__ = "Justin Lawrence"
__status__ = "Development"
__url__ = "https://github.com/jsaddiction/Trailarr"
__description__ = "Automatically download and manage movie trailers for Radarr."

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_FILE = ROOT_DIR / "trailarr.db"
CONFIG_FILE = ROOT_DIR / "settings.ini"
LOG_DIR = Path("/config/logs")
TEMP_DIR = ROOT_DIR / "temp"

VIDEO_EXTENSIONS = [
    ".mkv", ".iso", ".wmv", ".avi", ".mp4", ".m4v", ".img",
    ".divx", ".mov", ".flv", ".m2ts", ".ts", ".webm",
]
