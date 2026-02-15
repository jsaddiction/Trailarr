"""Logging configuration for Trailarr."""

import logging
import logging.config
from trailarr import LOG_DIR, TEMP_DIR
from trailarr.config.models import Config


def configure_logging(cfg: Config) -> None:
    """Configure logging handlers. Call once from entry points."""
    if not LOG_DIR.exists():
        LOG_DIR.mkdir(parents=True, exist_ok=True)
    if not TEMP_DIR.exists():
        TEMP_DIR.mkdir(parents=True, exist_ok=True)

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
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": cfg.log_level.upper(),
                "formatter": "file",
                "filename": str(LOG_DIR / "Trailarr.txt"),
                "maxBytes": 100_000,
                "backupCount": 5,
            },
        },
        "loggers": {
            "root": {
                "handlers": ["console", "file"],
                "level": "DEBUG",
            },
        },
    }

    logging.config.dictConfig(log_config)
