#!/usr/bin/env python
"""Trailarr Config Parser"""

import logging
from pathlib import Path
from configparser import ConfigParser

from src import Config

log = logging.getLogger("Trailarr.Config")


def get_config(config_path: Path) -> Config:
    """Parse config file and return Config object"""
    config = Config()
    if not config_path.exists():
        log.warning("No config file found at %s", config_path)
        return config

    parser = ConfigParser()
    try:
        parser.read(config_path)
    except OSError as e:
        log.warning("Could not read %s. Error: %s", config_path, e)
        return config

    if "LOGS" not in parser.sections():
        log.warning("No LOGS section found in %s", config_path)
        return config

    if "KODI" not in parser.sections():
        log.warning("No KODI section found in %s", config_path)
        return config

    # Apply settings from config file, falling back to defaults if not found
    config.log_level = parser["LOGS"].get("log_level", config.log_level)
    config.kodi_name = parser["KODI"].get("kodi_name", config.kodi_name)
    config.kodi_ip = parser["KODI"].get("kodi_ip", config.kodi_ip)
    config.kodi_port = parser["KODI"].getint("kodi_port", config.kodi_port)
    config.kodi_user = parser["KODI"].get("kodi_user", config.kodi_user)
    config.kodi_pass = parser["KODI"].get("kodi_pass", config.kodi_pass)
    config.kodi_notify = parser["KODI"].getboolean("kodi_notify", config.kodi_notify)

    return config
