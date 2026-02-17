"""Logging configuration for Trailarr."""

import logging
import logging.config
import os
from pathlib import Path

from trailarr import LOG_DIR, TEMP_DIR
from trailarr.config.models import Config

LOG_FILE = LOG_DIR / "Trailarr.txt"
MAX_LOG_BYTES = 1_048_576  # 1 MB
BACKUP_COUNT = 5


def _set_log_ownership(path) -> None:
    """Set log file ownership using PUID/PGID environment variables."""
    uid = int(os.environ.get("PUID", -1))
    gid = int(os.environ.get("PGID", -1))
    if uid < 0 and gid < 0:
        return
    try:
        os.chown(path, uid, gid)
        os.chmod(path, 0o666)
    except OSError:
        pass


def _rotated_name(default_name: str) -> str:
    """Convert Trailarr.txt.1 -> Trailarr.1.txt for Radarr UI compatibility."""
    # default_name is like /config/logs/Trailarr.txt.1
    p = Path(default_name)
    backup_num = p.suffix.lstrip(".")  # "1", "2", etc.
    stem = p.stem  # "Trailarr.txt" (the .txt is part of stem since .1 is the suffix)
    base = Path(stem).stem  # "Trailarr"
    ext = Path(stem).suffix  # ".txt"
    return str(p.parent / f"{base}.{backup_num}{ext}")


class OwnedRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """RotatingFileHandler that sets PUID/PGID ownership and uses Radarr-compatible naming.

    Produces: Trailarr.txt, Trailarr.1.txt, Trailarr.2.txt (instead of .txt.1, .txt.2)
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.namer = _rotated_name

    def _open(self):
        stream = super()._open()
        _set_log_ownership(self.baseFilename)
        return stream

    def doRollover(self):
        super().doRollover()
        # Fix ownership on the new active file and rotated backups
        _set_log_ownership(self.baseFilename)
        for i in range(1, self.backupCount + 1):
            rotated = self.rotation_filename(f"{self.baseFilename}.{i}")
            if os.path.exists(rotated):
                _set_log_ownership(rotated)


def _fix_existing_ownership() -> None:
    """Fix ownership on any existing log files from previous runs."""
    _set_log_ownership(str(LOG_FILE))
    for i in range(1, BACKUP_COUNT + 1):
        _set_log_ownership(str(LOG_FILE.parent / f"Trailarr.{i}.txt"))


def configure_logging(cfg: Config) -> None:
    """Configure logging handlers. Call once from entry points."""
    if not TEMP_DIR.exists():
        TEMP_DIR.mkdir(parents=True, exist_ok=True)

    handlers = ["console"]

    log_config = {
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
        },
        "loggers": {
            "root": {
                "level": "DEBUG",
            },
        },
    }

    # Only add file handler if log directory exists
    if LOG_DIR.is_dir():
        _fix_existing_ownership()

        log_config["handlers"]["file"] = {
            "()": OwnedRotatingFileHandler,
            "level": cfg.log_level.upper(),
            "formatter": "file",
            "filename": str(LOG_FILE),
            "maxBytes": MAX_LOG_BYTES,
            "backupCount": BACKUP_COUNT,
        }
        handlers.append("file")

    log_config["loggers"]["root"]["handlers"] = handlers
    logging.config.dictConfig(log_config)
