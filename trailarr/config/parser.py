"""Trailarr Config Parser."""

import logging
from pathlib import Path
from configparser import ConfigParser

from trailarr.config.models import Config

log = logging.getLogger("TrailArr.Config")


def get_config(config_path: Path) -> Config:
    """Parse config file and return Config object."""
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

    if "TRAILERS" not in parser.sections():
        log.warning("No TRAILERS section found in %s", config_path)

    if "KODI" not in parser.sections():
        log.warning("No KODI section found in %s", config_path)
        return config

    config.log_level = parser["LOGS"].get("log_level", config.log_level)

    if "TRAILERS" in parser.sections():
        try:
            config.max_resolution = parser["TRAILERS"].getint("max_resolution", config.max_resolution)
        except ValueError:
            log.warning("Invalid max_resolution in config, using default: %d", config.max_resolution)

    if "YT_DLP" in parser.sections():
        config.pot_provider_url = parser["YT_DLP"].get("pot_provider_url", config.pot_provider_url).strip()

    config.kodi_name = parser["KODI"].get("kodi_name", config.kodi_name)
    config.kodi_ip = parser["KODI"].get("kodi_ip", config.kodi_ip)
    try:
        config.kodi_port = parser["KODI"].getint("kodi_port", config.kodi_port)
    except ValueError:
        log.warning("Invalid kodi_port in config, using default: %d", config.kodi_port)
    config.kodi_user = parser["KODI"].get("kodi_user", config.kodi_user)
    config.kodi_pass = parser["KODI"].get("kodi_pass", config.kodi_pass)
    try:
        config.kodi_notify = parser["KODI"].getboolean("kodi_notify", config.kodi_notify)
    except ValueError:
        log.warning("Invalid kodi_notify in config, using default: %s", config.kodi_notify)

    return config
