"""Configuration package."""

from trailarr.config.models import Config
from trailarr.config.parser import get_config

__all__ = ["Config", "get_config"]
